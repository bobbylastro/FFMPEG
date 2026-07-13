"""
Scrape Reddit (r/GTA6, r/GTA, r/GTASeries) pour les théories et news GTA 6.
Pas d'auth requise — utilise l'API JSON publique de Reddit.
"""
import logging
import requests

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}
REDDIT_BASE = "https://old.reddit.com"

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


MOCK_POSTS = [
    {
        "title": "GTA 6 map is reportedly 3x bigger than GTA 5 — here's what we know",
        "body": "Multiple leakers have confirmed the map will feature Vice City, a large surrounding state, and possibly a second city. The map is said to include swamps, suburbs, highways and a massive downtown area.",
        "score": 12400, "comments": 847, "flair": "Theory", "url": "", "subreddit": "GTA6",
    },
    {
        "title": "The female protagonist Lucia's backstory — fan theories compiled",
        "body": "Based on the trailers, many fans believe Lucia is a criminal who got out of prison and is trying to start fresh with her partner Jason. The relationship dynamic seems central to the story.",
        "score": 8900, "comments": 612, "flair": "Discussion", "url": "", "subreddit": "GTA6",
    },
    {
        "title": "GTA 6 economy system explained — social media, influencers and stocks",
        "body": "Leaks suggest the game will feature a deep in-game social media system, a streaming platform parody, and a stock market. Players might be able to manipulate stocks like in GTA 5.",
        "score": 7300, "comments": 504, "flair": "Leak", "url": "", "subreddit": "GTA6",
    },
    {
        "title": "Every detail hidden in the GTA 6 trailers — frame by frame analysis",
        "body": "Fans have spotted: alligators in swamps, a GPS with a huge road network, female cop NPCs, a much more detailed crowd AI, and what appears to be a drug lab mission.",
        "score": 15600, "comments": 1200, "flair": "Analysis", "url": "", "subreddit": "GTA6",
    },
    {
        "title": "Will GTA 6 have the most realistic driving physics ever?",
        "body": "Based on the trailer footage, car handling looks significantly improved over GTA 5. Some insiders claim there are multiple driving physics modes. Motorcycles also look completely revamped.",
        "score": 5200, "comments": 389, "flair": "Discussion", "url": "", "subreddit": "GTA6",
    },
]


def fetch_reddit_posts(limit: int = 15, mock: bool = False) -> list[dict]:
    """Retourne les meilleurs posts GTA 6 de Reddit, dédupliqués et triés par score."""
    if mock:
        log.info("Mode mock — utilisation des posts test intégrés")
        return MOCK_POSTS[:limit]

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
