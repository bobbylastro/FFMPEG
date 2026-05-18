import base64
import http.cookiejar
import json
import logging
import os
import re

import requests

from config.settings import ANTHROPIC_API_KEY, CLIPS_PER_VIDEO, MAX_CLIP_DURATION, MIN_CLIP_DURATION

log = logging.getLogger(__name__)

MEDAL_API = "https://medal.tv/api"
MEDAL_COOKIES_PATH = "medal_cookies.txt"
USED_CLIPS_DIR = "data/used_clips"


def _used_path(slug: str) -> str:
    return os.path.join(USED_CLIPS_DIR, f"{slug}.json")

# slug → (display_name, category_id)
MEDAL_GAME_CATALOG = {
    "valorant":          ("Valorant",               "fW3AZxHf_c"),
    "counter-strike-2":  ("Counter-Strike 2",       "1giLEcuGln2"),
    "league-of-legends": ("League of Legends",      "bQnfO2HXP"),
    "rocket-league":     ("Rocket League",          "adufon9HW"),
    "apex-legends":      ("Apex Legends",           "5FsRVgww4b"),
}

EDITED_PATTERNS = re.compile(
    r'\bpart\s+\d+\b'
    r'|\bepisode\b|\bep\.?\s*\d+\b'
    r'|\bvol\.?\s*\d+\b|\bvolume\s+\d+\b'
    r'|\bmontage\b|\bcompilation\b'
    r'|\b#\d{2,}\b'
    r'|\bseries\b|\bseason\b',
    re.IGNORECASE,
)


def _build_session() -> requests.Session:
    jar = http.cookiejar.MozillaCookieJar()
    jar.load(MEDAL_COOKIES_PATH, ignore_discard=True, ignore_expires=True)

    medal_auth = next((c.value for c in jar if c.name == "medal-auth"), None)
    if not medal_auth:
        raise RuntimeError("medal-auth cookie not found in medal_cookies.txt")

    padded = medal_auth + "=" * (-len(medal_auth) % 4)
    auth_data = json.loads(base64.b64decode(padded))
    x_auth = f"{auth_data['userId']},{auth_data['key']}"

    session = requests.Session()
    session.cookies = jar  # type: ignore[assignment]
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "x-authentication": x_auth,
        "Accept": "application/json",
        "Referer": "https://medal.tv/",
    })
    return session


def _resolve_category_id(session: requests.Session, slug: str) -> str:
    r = session.get(f"{MEDAL_API}/categories/slug/{slug}", timeout=10)
    r.raise_for_status()
    return r.json()["categoryId"]


def _fetch_game_clips(
    session: requests.Session,
    slug: str,
    game_name: str,
    cat_id: str,
    limit: int,
    used_ids: set,
) -> list[dict]:
    headers = {"Referer": f"https://medal.tv/games/{slug}"}
    base_params = {
        "categoryId": cat_id,
        "limit": 50,
        "sortDirection": "DESC",
        "newPagination": "true",
        "sortBy": "agedScore",
        "metaPagination": 1,
    }

    MIN_CANDIDATES = max(30, limit * 2)
    MAX_PAGES = 6

    seen_ids: set = set()
    items: list = []
    clips: list = []  # filtered so far — checked after each page

    for page_num in range(MAX_PAGES):
        offset = page_num * 50
        r = session.get(
            f"{MEDAL_API}/content",
            params={**base_params, "offset": offset},
            headers=headers,
            timeout=15,
        )
        r.raise_for_status()
        page = r.json().get("items", [])

        new_items = [i for i in page if i.get("contentId") not in seen_ids]
        seen_ids.update(i.get("contentId") for i in new_items)
        items.extend(new_items)

        # Filter the new page and add to running candidates
        for item in new_items:
            cid = item.get("contentId")
            title = item.get("contentTitle", "")
            duration = item.get("videoLengthSeconds", 0)
            views = item.get("views", 0)
            url = (
                item.get("contentUrl1080p")
                or item.get("contentUrl720p")
                or item.get("contentUrl", "")
            )
            if not cid or not url: continue
            if str(cid) in used_ids: continue
            if not (MIN_CLIP_DURATION <= duration <= MAX_CLIP_DURATION): continue
            if views < 200: continue
            if item.get("orientation", "landscape") != "landscape": continue
            if item.get("sourceHeight", 1080) > item.get("sourceWidth", 1920): continue
            if EDITED_PATTERNS.search(title): continue
            clips.append({
                "id": str(cid), "title": title, "url": url,
                "view_count": views, "duration": duration,
                "broadcaster_name": item.get("poster", {}).get("displayName", ""),
                "language": "en", "_game": game_name,
                "_velocity": views, "_source": "medal",
            })

        log.info(f"  {game_name}: page {page_num+1} → {len(clips)} candidats après filtres")

        if len(page) < 50:
            break  # plus de résultats disponibles
        if len(clips) >= MIN_CANDIDATES:
            break  # assez de candidats, inutile de charger plus

    if len(clips) < MIN_CANDIDATES:
        log.warning(
            f"  {game_name}: seulement {len(clips)} candidats après {MAX_PAGES} pages "
            f"(seuil={MIN_CANDIDATES}) — le pool de clips frais s'épuise"
        )

    clips.sort(key=lambda c: c["view_count"], reverse=True)
    return clips


def fetch_medal_clips(limit: int = None, slugs: list[str] = None) -> list[dict]:
    total = limit or CLIPS_PER_VIDEO
    catalog = {
        slug: (name, cat_id)
        for slug, (name, cat_id) in MEDAL_GAME_CATALOG.items()
        if slugs is None or slug in slugs
    }
    per_game = max(1, total // len(catalog))

    used_ids: set = set()
    for slug in catalog:
        path = _used_path(slug)
        if os.path.exists(path):
            with open(path) as f:
                raw = json.load(f)
            used_ids.update(c if isinstance(c, str) else c["id"] for c in raw)

    session = _build_session()

    all_clips: list[dict] = []
    for slug, (game_name, cat_id) in catalog.items():
        try:
            clips = _fetch_game_clips(session, slug, game_name, cat_id, per_game, used_ids)

            # En mode multi-jeux on plafonne à 4/jeu pour diversité.
            # En mode mono-jeu (per_game élevé) on laisse l'IA sélectionner librement.
            ai_cap = per_game if len(catalog) == 1 else min(per_game, 4)
            if ANTHROPIC_API_KEY:
                from src.select_clips_ai import select_clips_ai
                clips = select_clips_ai(clips[:50], ai_cap, game_name=game_name)
            else:
                clips = clips[:ai_cap]

            log.info(f"  {game_name}: keeping {len(clips)} clips")
            all_clips.extend(clips)
        except Exception as e:
            log.warning(f"Failed to fetch Medal clips for {game_name}: {e}")

    if not all_clips:
        raise RuntimeError("No Medal.tv clips found — cookies may have expired or all games failed")

    log.info(f"Total: {len(all_clips)} Medal clips across {len(catalog)} games")
    return all_clips


def mark_clips_used(clips: list[dict]) -> None:
    """Sauvegarde les clips utilisés dans data/used_clips/{slug}.json."""
    os.makedirs(USED_CLIPS_DIR, exist_ok=True)

    # Reverse map game_name → slug
    name_to_slug = {name: slug for slug, (name, _) in MEDAL_GAME_CATALOG.items()}

    by_slug: dict[str, list] = {}
    for clip in clips:
        slug = name_to_slug.get(clip.get("_game", ""), "unknown")
        by_slug.setdefault(slug, []).append(clip)

    for slug, slug_clips in by_slug.items():
        path = _used_path(slug)
        existing = []
        if os.path.exists(path):
            with open(path) as f:
                existing = json.load(f)
        existing_ids = {c if isinstance(c, str) else c["id"] for c in existing}
        new_entries = [
            {k: v for k, v in c.items() if k != "local_path"}
            for c in slug_clips if c["id"] not in existing_ids
        ]
        with open(path, "w") as f:
            json.dump(existing + new_entries, f, indent=2)
        log.info(f"  [{slug}] {len(new_entries)} clips ajoutés à l'historique ({len(existing_ids) + len(new_entries)} total)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    clips = fetch_medal_clips()
    for i, c in enumerate(clips, 1):
        print(f"{i:2}. [{c['_game']:<25}] {int(c['duration']):>3}s | {c['view_count']:>7} views | {c['title'][:50]}")
