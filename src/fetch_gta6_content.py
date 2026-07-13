"""
Scrape Reddit (r/GTA6, r/GTA, r/GTASeries) pour les théories et news GTA 6.
Pas d'auth requise — utilise l'API JSON publique de Reddit.
"""
import logging
import requests

log = logging.getLogger(__name__)

HEADERS    = {"User-Agent": "GTA6ContentBot/1.0 (automated content pipeline)"}
REDDIT_BASE = "https://www.reddit.com"

GTA6_KEYWORDS = {"gta 6", "gta6", "gta vi", "grand theft auto 6", "grand theft auto vi"}

SOURCES = [
    # (subreddit, sort, time_filter)
    ("GTA6",       "hot",  None),
    ("GTA6",       "top",  "week"),
    ("GTA6",       "top",  "month"),
    ("GTA",        "hot",  None),
    ("GTASeries",  "hot",  None),
]


def _is_gta6_relevant(title: str, subreddit: str) -> bool:
    if subreddit == "GTA6":
        return True
    return any(kw in title.lower() for kw in GTA6_KEYWORDS)


def fetch_reddit_posts(limit: int = 15) -> list[dict]:
    """Retourne les meilleurs posts GTA 6 de Reddit, dédupliqués et triés par score."""
    seen_titles: set[str] = set()
    posts: list[dict] = []

    for sub, sort, time_filter in SOURCES:
        params: dict = {"limit": 25, "raw_json": 1}
        if time_filter:
            params["t"] = time_filter

        try:
            resp = requests.get(
                f"{REDDIT_BASE}/r/{sub}/{sort}.json",
                headers=HEADERS,
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            children = resp.json()["data"]["children"]
        except Exception as e:
            log.warning(f"Reddit fetch failed ({sub}/{sort}): {e}")
            continue

        for item in children:
            p = item["data"]
            title = p.get("title", "").strip()

            if not _is_gta6_relevant(title, sub):
                continue
            if p.get("score", 0) < 30:
                continue
            # Ignorer les posts image/vidéo sans texte
            if p.get("is_video") or (
                p.get("post_hint", "") in ("image", "link")
                and not p.get("selftext")
            ):
                continue
            if title in seen_titles:
                continue

            seen_titles.add(title)
            posts.append({
                "title":     title,
                "body":      (p.get("selftext") or "")[:800],
                "score":     p.get("score", 0),
                "comments":  p.get("num_comments", 0),
                "flair":     p.get("link_flair_text") or "",
                "url":       f"{REDDIT_BASE}{p.get('permalink', '')}",
                "subreddit": sub,
            })

    posts.sort(key=lambda x: x["score"], reverse=True)
    log.info(f"Reddit: {len(posts)} posts GTA 6 collectés")
    return posts[:limit]
