"""
Fetch Twitch clips pour le pipeline website (14 jeux, fenêtre large, pas de filtre keyword).
Historique séparé du pipeline YouTube dans data/used_clips_website/.
"""
import json
import logging
import os
import re
import unicodedata
import requests
from datetime import datetime, timedelta, timezone

_NON_LATIN_RE = re.compile(
    r'['
    r'Ѐ-ӿ'   # Cyrillic
    r'؀-ۿ'   # Arabic
    r'ऀ-ॿ'   # Devanagari
    r'฀-๿'   # Thai
    r'぀-ヿ'   # Hiragana + Katakana
    r'㐀-䶿'   # CJK Extension A
    r'一-鿿'   # CJK Unified Ideographs
    r'가-힯'   # Korean Hangul
    r']'
)

# Titres formatés avec underscores comme séparateurs (ex: "Who_s_your_friend")
_UNDERSCORE_TITLE_RE = re.compile(r'\b\w+_\w+')

# Questions biographiques sur une personnalité (ex: "Is Mr Wizard's Name Actually Pandolfo?")
# Cible: "Is [Name]'s...", "What is [Name]'s...", "Who is [Name]", "What's [Name]'s real name"
_BIO_QUESTION_RE = re.compile(
    r"^(is\s+\w[\w\s]*'s\s+\w|what\s+(is|was)\s+\w[\w\s]*'s|what's\s+\w[\w\s]*'s|who\s+(is|was)\s+\w[\w\s]*(real|actual|true|full))",
    re.IGNORECASE,
)

from config.settings import TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, MIN_CLIP_DURATION, MAX_CLIP_DURATION

USED_CLIPS_DIR  = "data/used_clips_website"
TWITCH_AUTH_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_API_URL  = "https://api.twitch.tv/helix"

log = logging.getLogger(__name__)


def _is_garbage_title(title: str) -> bool:
    """True si le titre est inutilisable : trop court, underscores partout, ou question biographique."""
    if sum(1 for c in title if unicodedata.category(c).startswith("L")) < 3:
        return True
    # Titre formaté avec underscores comme séparateurs (ex: "Who_s_your_friend")
    if _UNDERSCORE_TITLE_RE.search(title):
        return True
    # Question biographique sur une personne (ex: "Is Mr Wizard's Name Actually Pandolfo?")
    if _BIO_QUESTION_RE.match(title.strip()):
        return True
    return False


WEBSITE_GAME_CATALOG = {
    "valorant":           "VALORANT",
    "apex-legends":       "Apex Legends",
    "marvel-rivals":      "Marvel Rivals",
    "the-finals":         "The Finals",
    "rocket-league":      "Rocket League",
    "rainbow-six-siege":  "Rainbow Six Siege",
    "league-of-legends":  "League of Legends",
    "cs2":                "Counter-Strike",
    "rust":               "Rust",
    "gta-v":              "Grand Theft Auto V",
    "minecraft":          "Minecraft",
    "overwatch":          "Overwatch 2",
    "arc-raiders":        "ARC Raiders",
}


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
    os.makedirs(USED_CLIPS_DIR, exist_ok=True)
    path = os.path.join(USED_CLIPS_DIR, f"{game_slug}.json")
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        raw = json.load(f)
    # Pas de purge temporelle : les clips du site restent exclus indéfiniment
    return {c["id"] if isinstance(c, dict) else c for c in raw}


def mark_used(game_slug: str, clips: list[dict]) -> None:
    os.makedirs(USED_CLIPS_DIR, exist_ok=True)
    path = os.path.join(USED_CLIPS_DIR, f"{game_slug}.json")
    existing = []
    if os.path.exists(path):
        with open(path) as f:
            existing = json.load(f)
    now = datetime.now(timezone.utc).isoformat()
    existing_ids = {c["id"] if isinstance(c, dict) else c for c in existing}
    for c in clips:
        if c["id"] not in existing_ids:
            existing.append({**c, "used_at": now})
    with open(path, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)


def fetch_website_clips(
    game_slug: str,
    limit: int = 30,
    days: int = 90,
) -> list[dict]:
    """Fetch Twitch clips pour un jeu, fenêtre large, sans filtre keyword.
    Retourne les clips triés par vélocité, dédupliqués vs historique website.
    """
    game_name   = WEBSITE_GAME_CATALOG.get(game_slug, game_slug)
    used_ids    = _load_used_ids(game_slug)

    if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        log.warning("Twitch credentials manquants")
        return []

    try:
        token   = _get_token()
        game_id = _get_game_id(token, game_name)
    except Exception as e:
        log.warning(f"[{game_slug}] Twitch setup failed: {e}")
        return []

    headers    = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
    started_at = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    fetch_cap  = limit * 10
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
            log.warning(f"[{game_slug}] Twitch API error: {e}")
            break

        page = body.get("data", [])
        if not page:
            break

        now = datetime.now(timezone.utc)
        for c in page:
            cid      = c.get("id", "")
            duration = c.get("duration", 0)
            url      = c.get("url", "")

            if not cid or not url:
                continue
            if cid in used_ids:
                continue
            if not (MIN_CLIP_DURATION <= duration <= MAX_CLIP_DURATION):
                continue
            if _is_garbage_title(c.get("title", "")):
                continue
            if _NON_LATIN_RE.search(c.get("title", "")):
                continue

            created    = datetime.fromisoformat(c["created_at"].replace("Z", "+00:00"))
            days_alive = max((now - created).total_seconds() / 86400, 0.5)
            velocity   = c.get("view_count", 0) / days_alive

            candidates.append({
                "id":               cid,
                "title":            c.get("title", ""),
                "url":              url,
                "view_count":       c.get("view_count", 0),
                "duration":         duration,
                "broadcaster_name": c.get("broadcaster_name", ""),
                "created_at":       c.get("created_at", ""),
                "_game":            game_name,
                "_game_slug":       game_slug,
                "_source":          "twitch",
                "_velocity":        velocity,
            })

        cursor = body.get("pagination", {}).get("cursor")
        if not cursor:
            break

    candidates.sort(key=lambda c: c["_velocity"], reverse=True)
    log.info(f"  [{game_slug}] {len(candidates)} candidats disponibles")
    return candidates
