"""
Scrape Reddit (r/GTA6, r/GTA, r/GTASeries) pour les théories et news GTA 6.
Utilise PRAW (OAuth) avec les credentials REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET.
"""
import logging
import os

import praw

from config.settings import REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET

log = logging.getLogger(__name__)

GTA6_KEYWORDS = {"gta 6", "gta6", "gta vi", "grand theft auto 6", "grand theft auto vi"}

SOURCES = [
    # (subreddit, sort, time_filter)
    ("GTA6",      "hot",  None),
    ("GTA6",      "top",  "week"),
    ("GTA6",      "top",  "month"),
    ("GTA",       "hot",  None),
    ("GTASeries", "hot",  None),
]


def _is_gta6_relevant(title: str, subreddit: str) -> bool:
    if subreddit == "GTA6":
        return True
    return any(kw in title.lower() for kw in GTA6_KEYWORDS)


MOCK_POSTS = [
    {
        "title": "GTA 6 map is reportedly 3x bigger than GTA 5 — here's what we know",
        "body": "Multiple leakers have confirmed the map will feature Vice City, a large surrounding state, and possibly a second city. The map is said to include swamps, suburbs, highways and a massive downtown area.",
        "score": 12400, "comments": 847, "flair": "Theory", "url": "", "subreddit": "GTA6", "image_url": "",
    },
    {
        "title": "The female protagonist Lucia's backstory — fan theories compiled",
        "body": "Based on the trailers, many fans believe Lucia is a criminal who got out of prison and is trying to start fresh with her partner Jason. The relationship dynamic seems central to the story.",
        "score": 8900, "comments": 612, "flair": "Discussion", "url": "", "subreddit": "GTA6", "image_url": "",
    },
    {
        "title": "GTA 6 economy system explained — social media, influencers and stocks",
        "body": "Leaks suggest the game will feature a deep in-game social media system, a streaming platform parody, and a stock market. Players might be able to manipulate stocks like in GTA 5.",
        "score": 7300, "comments": 504, "flair": "Leak", "url": "", "subreddit": "GTA6", "image_url": "",
    },
    {
        "title": "Every detail hidden in the GTA 6 trailers — frame by frame analysis",
        "body": "Fans have spotted: alligators in swamps, a GPS with a huge road network, female cop NPCs, a much more detailed crowd AI, and what appears to be a drug lab mission.",
        "score": 15600, "comments": 1200, "flair": "Analysis", "url": "", "subreddit": "GTA6", "image_url": "",
    },
    {
        "title": "Will GTA 6 have the most realistic driving physics ever?",
        "body": "Based on the trailer footage, car handling looks significantly improved over GTA 5. Some insiders claim there are multiple driving physics modes. Motorcycles also look completely revamped.",
        "score": 5200, "comments": 389, "flair": "Discussion", "url": "", "subreddit": "GTA6", "image_url": "",
    },
]


def _make_reddit() -> praw.Reddit:
    return praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent="gta6-pipeline/1.0 by bobbylastro",
    )


def fetch_reddit_posts(limit: int = 15, mock: bool = False) -> list[dict]:
    """Retourne les meilleurs posts GTA 6 de Reddit, dédupliqués et triés par score."""
    if mock:
        log.info("Mode mock — utilisation des posts test intégrés")
        return MOCK_POSTS[:limit]

    reddit = _make_reddit()
    seen_titles: set[str] = set()
    posts: list[dict] = []

    for sub_name, sort, time_filter in SOURCES:
        try:
            subreddit = reddit.subreddit(sub_name)
            if sort == "hot":
                listing = subreddit.hot(limit=30)
            elif sort == "top":
                listing = subreddit.top(time_filter=time_filter or "week", limit=30)
            else:
                listing = subreddit.new(limit=30)

            for submission in listing:
                title = submission.title.strip()

                if not _is_gta6_relevant(title, sub_name):
                    continue
                if submission.score < 30:
                    continue
                if title in seen_titles:
                    continue

                # Image associée au post
                image_url = ""
                url = getattr(submission, "url", "") or ""
                hint = getattr(submission, "post_hint", "") or ""

                if hint == "image" and "i.redd.it" in url:
                    # Post image simple hébergé sur Reddit
                    image_url = url
                elif getattr(submission, "is_gallery", False):
                    # Post galerie : prendre la première image
                    meta = getattr(submission, "media_metadata", {}) or {}
                    for item in meta.values():
                        src = (item.get("s") or {}).get("u", "")
                        if src:
                            image_url = src.replace("&amp;", "&")
                            break
                elif url and any(url.lower().endswith(e) for e in (".jpg", ".jpeg", ".png")):
                    if "i.redd.it" in url or "imgur.com" in url:
                        image_url = url

                # Corps texte (vide pour les posts image, OK)
                body = (getattr(submission, "selftext", "") or "")[:800]

                seen_titles.add(title)
                posts.append({
                    "title":     title,
                    "body":      body,
                    "score":     submission.score,
                    "comments":  submission.num_comments,
                    "flair":     submission.link_flair_text or "",
                    "url":       f"https://reddit.com{submission.permalink}",
                    "subreddit": sub_name,
                    "image_url": image_url,
                })

        except Exception as e:
            log.warning(f"Reddit fetch failed ({sub_name}/{sort}): {e}")
            continue

    posts.sort(key=lambda x: x["score"], reverse=True)
    log.info(f"Reddit: {len(posts)} posts GTA 6 collectés")
    return posts[:limit]
