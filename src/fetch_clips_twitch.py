import json
import logging
import os
import re
import requests
from datetime import datetime, timedelta, timezone

from config.settings import (
    TWITCH_CLIENT_ID,
    TWITCH_CLIENT_SECRET,
    MAX_CLIP_DURATION,
    MIN_CLIP_DURATION,
)

USED_CLIPS_DIR = "data/used_clips"

log = logging.getLogger(__name__)

TWITCH_AUTH_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_API_URL  = "https://api.twitch.tv/helix"

# Medal slug → Twitch game name (exact match required by the API)
TWITCH_GAME_CATALOG = {
    "valorant":          "VALORANT",
    "marvel-rivals":     "Marvel Rivals",
    "the-finals":        "The Finals",
    "rocket-league":     "Rocket League",
    "apex-legends":      "Apex Legends",
    "r6-siege":          "Rainbow Six Siege",
}

# Only keep clips whose title signals a concrete high-quality play
_HIGH_CONFIDENCE = re.compile(
    r"\b(ace|5\s*k|4\s*k|3\s*k|penta(kill)?|clutch|"
    r"1\s*v\s*[2-5]|collateral|wall\s*bang|no.?scope|"
    r"quick.?scope|flick|highlight|outplay|insane|"
    r"triple\s*kill|quad\s*kill|360|"
    r"team\s*wipe|wipe|ultimate|ult|mvp|potg|"
    r"play\s*of\s*the\s*game|combo|multi.?kill|cashout)\b",
    re.IGNORECASE,
)


def _get_token() -> str:
    resp = requests.post(TWITCH_AUTH_URL, params={
        "client_id":     TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type":    "client_credentials",
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()["access_token"]


def _get_game_id(token: str, twitch_name: str) -> str:
    resp = requests.get(f"{TWITCH_API_URL}/games", headers={
        "Client-ID":     TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}",
    }, params={"name": twitch_name}, timeout=10)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    if not data:
        raise ValueError(f"Twitch game not found: {twitch_name!r}")
    return data[0]["id"]


def _load_used_ids(game_slug: str) -> set:
    path = os.path.join(USED_CLIPS_DIR, f"{game_slug}.json")
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        raw = json.load(f)
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    used = set()
    for c in raw:
        if isinstance(c, str):
            used.add(c)
        else:
            used_at = c.get("used_at")
            if used_at and datetime.fromisoformat(used_at) < cutoff:
                continue
            used.add(c["id"])
    return used


def fetch_twitch_clips(
    game_slug: str,
    game_name: str,
    extra_used_ids: set | None = None,
    limit: int = 15,
    days: int = 14,
) -> list[dict]:
    """Fetch Twitch clips for one game, pre-filtered to high-confidence plays.

    Returns candidates (not yet AI-selected); caller merges with Medal pool.
    """
    used_ids = _load_used_ids(game_slug) | (extra_used_ids or set())

    if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        log.warning("Twitch credentials missing — skipping Twitch source")
        return []

    twitch_name = TWITCH_GAME_CATALOG.get(game_slug)
    if not twitch_name:
        log.warning(f"No Twitch mapping for slug '{game_slug}' — skipping")
        return []

    try:
        token   = _get_token()
        game_id = _get_game_id(token, twitch_name)
    except Exception as e:
        log.warning(f"Twitch setup failed: {e} — skipping Twitch source")
        return []

    headers    = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
    started_at = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    fetch_cap  = limit * 15   # over-fetch to compensate for keyword filter
    candidates = []
    cursor     = None

    while len(candidates) < fetch_cap:
        params = {"game_id": game_id, "first": 20, "started_at": started_at}
        if cursor:
            params["after"] = cursor

        try:
            resp = requests.get(f"{TWITCH_API_URL}/clips", headers=headers,
                                params=params, timeout=15)
            resp.raise_for_status()
            body = resp.json()
        except Exception as e:
            log.warning(f"Twitch clips API error: {e}")
            break

        page = body.get("data", [])
        if not page:
            break

        now = datetime.now(timezone.utc)
        for c in page:
            cid      = c.get("id", "")
            title    = c.get("title", "")
            duration = c.get("duration", 0)
            url      = c.get("url", "")

            if not cid or not url:
                continue
            if cid in used_ids:
                continue
            if not (MIN_CLIP_DURATION <= duration <= MAX_CLIP_DURATION):
                continue
            if not _HIGH_CONFIDENCE.search(title):
                continue

            created    = datetime.fromisoformat(c["created_at"].replace("Z", "+00:00"))
            days_alive = max((now - created).total_seconds() / 86400, 0.5)
            velocity   = c.get("view_count", 0) / days_alive

            candidates.append({
                "id":               cid,
                "title":            title,
                "url":              url,
                "view_count":       c.get("view_count", 0),
                "duration":         duration,
                "broadcaster_name": c.get("broadcaster_name", ""),
                "created_at":       c.get("created_at", ""),
                "_game":            game_name,
                "_source":          "twitch",
                "_velocity":        velocity,
            })

        cursor = body.get("pagination", {}).get("cursor")
        if not cursor:
            break

    candidates.sort(key=lambda c: c["_velocity"], reverse=True)
    selected = candidates[:limit]
    log.info(
        f"  [Twitch/{game_name}] {len(candidates)} candidats high-confidence "
        f"→ {len(selected)} transmis à l'IA"
    )
    return selected
