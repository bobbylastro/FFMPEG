import json
import logging
import os
import unicodedata
import requests
from datetime import datetime, timedelta, timezone

from config.settings import (
    TWITCH_CLIENT_ID,
    TWITCH_CLIENT_SECRET,
    ANTHROPIC_API_KEY,
    GAMES,
    CLIPS_DAYS_AGO_START,
    CLIPS_DAYS_AGO_END,
    CLIPS_PER_VIDEO,
    MAX_CLIP_DURATION,
    MIN_CLIP_DURATION,
    MIN_VELOCITY,
    EXCLUDED_LANGUAGES,
    EXCLUDED_BROADCASTERS,
    ACTION_KEYWORDS,
)

log = logging.getLogger(__name__)

TWITCH_AUTH_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_API_URL = "https://api.twitch.tv/helix"
USED_CLIPS_PATH = "data/used_clips.json"


def _load_used_ids() -> set:
    if not os.path.exists(USED_CLIPS_PATH):
        return set()
    with open(USED_CLIPS_PATH) as f:
        raw = json.load(f)
    return {c if isinstance(c, str) else c["id"] for c in raw}


def mark_clips_used(clips: list[dict]) -> None:
    existing = []
    if os.path.exists(USED_CLIPS_PATH):
        with open(USED_CLIPS_PATH) as f:
            existing = json.load(f)
    existing_ids = {c if isinstance(c, str) else c["id"] for c in existing}
    new_entries = [
        {k: v for k, v in c.items() if k != "local_path"}
        for c in clips if c["id"] not in existing_ids
    ]
    with open(USED_CLIPS_PATH, "w") as f:
        json.dump(existing + new_entries, f, indent=2)
    log.info(f"Marked {len(clips)} clips as used ({len(existing_ids) + len(new_entries)} total in history)")


def _is_garbage_title(title: str) -> bool:
    """True si le titre a moins de 3 lettres Unicode — émojis seuls, ponctuation, gibberish."""
    return sum(1 for c in title if unicodedata.category(c).startswith("L")) < 3


def _is_latin_title(title: str) -> bool:
    if not title:
        return False
    latin = sum(1 for c in title if c.isascii() and c.isalpha())
    total = sum(1 for c in title if c.isalpha())
    return total == 0 or (latin / total) >= 0.5


def _has_action_keyword(title: str) -> bool:
    title_lower = title.lower()
    import re
    for kw in ACTION_KEYWORDS:
        # word boundary check for short/ambiguous keywords
        if re.search(r'\b' + re.escape(kw) + r'\b', title_lower):
            return True
    return False


def get_access_token() -> str:
    resp = requests.post(TWITCH_AUTH_URL, params={
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials",
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_game_id(token: str, game_name: str) -> str:
    resp = requests.get(f"{TWITCH_API_URL}/games", headers={
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}",
    }, params={"name": game_name})
    resp.raise_for_status()
    data = resp.json()["data"]
    if not data:
        raise ValueError(f"Game not found: {game_name}")
    return data[0]["id"]


def _fetch_clips_for_game(token: str, game_name: str, limit: int, used_ids: set) -> list[dict]:
    game_id = get_game_id(token, game_name)

    now = datetime.now(timezone.utc)
    started_at = (now - timedelta(days=CLIPS_DAYS_AGO_START)).isoformat()
    ended_at = (now - timedelta(days=CLIPS_DAYS_AGO_END)).isoformat()

    log.info(f"Fetching clips for {game_name} ({started_at[:10]} → {ended_at[:10]})")

    clips = []
    cursor = None
    fetch_limit = max(limit * 20, 100)  # toujours au moins 100 candidats par jeu

    while len(clips) < fetch_limit:
        params = {
            "game_id": game_id,
            "first": min(20, fetch_limit - len(clips)),
            "started_at": started_at,
            "ended_at": ended_at,
        }
        if cursor:
            params["after"] = cursor

        resp = requests.get(f"{TWITCH_API_URL}/clips", headers={
            "Client-ID": TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {token}",
        }, params=params)
        resp.raise_for_status()
        body = resp.json()

        page = body.get("data", [])
        if not page:
            break
        clips.extend(page)
        cursor = body.get("pagination", {}).get("cursor")
        if not cursor:
            break

    before = len(clips)
    clips = [
        c for c in clips
        if MIN_CLIP_DURATION <= c.get("duration", 0) <= MAX_CLIP_DURATION
        and c["id"] not in used_ids
        and _is_latin_title(c.get("title", ""))
        and not _is_garbage_title(c.get("title", ""))
    ]
    log.info(f"  {game_name}: {before} → {len(clips)} after duration/latin-title/history filter")

    now = datetime.now(timezone.utc)
    for c in clips:
        created = datetime.fromisoformat(c["created_at"].replace("Z", "+00:00"))
        days_alive = max((now - created).total_seconds() / 86400, 0.5)
        c["_velocity"] = c["view_count"] / days_alive
        c["_game"] = game_name

    before = len(clips)
    clips = [
        c for c in clips
        if c["_velocity"] >= MIN_VELOCITY
        and c.get("broadcaster_name", "").lower() not in EXCLUDED_BROADCASTERS
    ]
    log.info(f"  {game_name}: {before} → {len(clips)} after velocity/broadcaster filter")

    clips = sorted(clips, key=lambda c: c["_velocity"], reverse=True)

    if ANTHROPIC_API_KEY:
        from src.select_clips_ai import select_clips_ai
        clips = select_clips_ai(clips[:20], min(limit, 4), game_name=game_name)
    else:
        clips = [c for c in clips if _has_action_keyword(c.get("title", ""))]
        clips = clips[:limit]

    return clips


def fetch_top_clips(limit: int = None) -> list[dict]:
    total = limit or CLIPS_PER_VIDEO
    games = GAMES
    per_game = max(1, total // len(games))

    token = get_access_token()
    used_ids = _load_used_ids()

    all_clips = []
    for game in games:
        try:
            clips = _fetch_clips_for_game(token, game, per_game, used_ids)
            all_clips.extend(clips)
        except Exception as e:
            log.warning(f"Failed to fetch clips for {game}: {e}")

    if not all_clips:
        raise RuntimeError("No clips found for any game — widen the date range or relax filters")
    if len(all_clips) < total:
        log.warning(f"Only {len(all_clips)}/{total} clips available after filtering")

    log.info(f"Total: {len(all_clips)} clips across {len(games)} games")
    log.info(f"Top clip: '{all_clips[0]['title']}' ({all_clips[0]['view_count']} views, {all_clips[0]['_game']})")
    return all_clips


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    clips = fetch_top_clips()
    for i, c in enumerate(clips, 1):
        print(f"{i:2}. [{c['_velocity']:>7.0f} v/day | {c['view_count']:>6} views | {c['duration']:>4.0f}s | {c['language']}] {c['title'][:50]}")
