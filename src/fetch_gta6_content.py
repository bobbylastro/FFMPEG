"""
Scrape Reddit (r/GTA6, r/GTA, r/GTASeries) ou les flux RSS gaming pour les news GTA 6.
Reddit : PRAW OAuth avec REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET.
News    : flux RSS gaming (GameSpot, RPS, PCGamer, Push Square…) + og:image fallback.
"""
import html
import json
import logging
import os
import re
import urllib.request
import xml.etree.ElementTree as ET

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


POSTS_CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "gta6_last_posts.json")


def _save_posts_cache(posts: list[dict]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(POSTS_CACHE)), exist_ok=True)
    with open(POSTS_CACHE, "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)


def _load_posts_cache() -> list[dict]:
    if os.path.exists(POSTS_CACHE):
        with open(POSTS_CACHE, encoding="utf-8") as f:
            return json.load(f)
    return []


def fetch_reddit_posts(limit: int = 15, mock: bool = False) -> list[dict]:
    """Retourne les meilleurs posts GTA 6 de Reddit, dédupliqués et triés par score."""
    if mock:
        cached = _load_posts_cache()
        if cached:
            log.info(f"Mode mock — {len(cached[:limit])} posts du dernier vrai scrap")
            return cached[:limit]
        log.info("Mode mock — utilisation des posts test intégrés (pas de cache)")
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
    result = posts[:limit]
    log.info(f"Reddit: {len(result)} posts GTA 6 collectés")
    if result:
        _save_posts_cache(result)
    return result


# ── News RSS ──────────────────────────────────────────────────────────────────

_NEWS_SOURCES = [
    # (nom, flux RSS)
    ("GameSpot",    "https://www.gamespot.com/feeds/news/"),
    ("IGN",         "https://feeds.ign.com/ign/all"),
    ("GamesRadar",  "https://www.gamesradar.com/rss/"),
    ("PCGamer",     "https://www.pcgamer.com/rss/"),
    ("Eurogamer",   "https://www.eurogamer.net/feed"),
    ("RPS",         "https://www.rockpapershotgun.com/feed"),
    ("VG247",       "https://www.vg247.com/feed"),
    ("Push Square", "https://www.pushsquare.com/feeds/latest"),
    ("Kotaku",      "https://kotaku.com/rss"),
    ("Destructoid", "https://www.destructoid.com/feed/"),
    ("VGC",         "https://www.videogameschronicle.com/feed/"),
    # Google News pour le volume (titre + description, pas d'image directe)
    ("Google News", "https://news.google.com/rss/search?q=GTA+6+grand+theft+auto&hl=en-US&gl=US&ceid=US:en"),
]

_MEDIA_NS = {"media": "http://search.yahoo.com/mrss/"}

_GTA6_ONLY = {"gta 6", "gta6", "gta vi", "grand theft auto 6", "grand theft auto vi"}
_GTA6_EXCLUDE = {"gta 5", "gta5", "gta v ", " gta v,", "gta iv", "gta 4", "red dead"}


def _is_gta6_news(title: str, body: str = "") -> bool:
    text = (title + " " + body).lower()
    if not any(k in text for k in _GTA6_ONLY):
        return False
    if any(k in text for k in _GTA6_EXCLUDE):
        return False
    return True


def _clean_html(raw: str) -> str:
    """Supprime les balises HTML et décode les entités."""
    cleaned = re.sub(r"<[^>]+>", " ", raw)
    return html.unescape(cleaned).strip()


def _feed_image(item: ET.Element) -> str:
    """Extrait l'image depuis les tags media: ou enclosure du flux RSS."""
    for tag in ("media:thumbnail", "media:content"):
        node = item.find(tag, _MEDIA_NS)
        if node is not None:
            url = node.get("url", "")
            if url:
                return _upgrade_image_url(url)
    enc = item.find("enclosure")
    if enc is not None and "image" in enc.get("type", ""):
        return _upgrade_image_url(enc.get("url", ""))
    return ""


def _upgrade_image_url(url: str) -> str:
    """Remplace les paramètres de taille basse résolution par la pleine résolution."""
    if not url:
        return url
    # Supprime ou remplace les params de taille basse (w=300, width=690, size=small…)
    url = re.sub(r'([?&])w=\d+', r'\1w=1280', url)
    url = re.sub(r'([?&])width=\d+', r'\1width=1280', url)
    url = re.sub(r'([?&])size=\w+', '', url)
    url = re.sub(r'-\d+x\d+(\.\w+)$', r'\1', url)   # WordPress: image-300x200.jpg → image.jpg
    url = re.sub(r'[?&]$', '', url)
    return url


def _og_image(url: str, timeout: int = 6) -> str:
    """Fetch l'URL et extrait og:image (fallback quand le flux n'a pas d'image)."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120",
            "Accept": "text/html",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_html = resp.read(80000).decode("utf-8", errors="ignore")
        for pat in [
            r'property=["\']og:image["\']\s*content=["\']([^"\']+)',
            r'content=["\']([^"\']+)["\']\s*property=["\']og:image',
        ]:
            m = re.search(pat, raw_html)
            if m:
                return _upgrade_image_url(m.group(1).strip())
    except Exception:
        pass
    return ""


def fetch_news_posts(limit: int = 15) -> list[dict]:
    """
    Collecte des articles GTA 6 depuis des flux RSS gaming + Google News.
    Retourne dans le même format que fetch_reddit_posts().
    """
    seen: set[str] = set()
    articles: list[dict] = []

    for source_name, feed_url in _NEWS_SOURCES:
        try:
            req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)

            items = root.findall(".//item")
            gta6_count = 0
            for item in items:
                title = _clean_html(item.findtext("title", ""))
                desc  = _clean_html(item.findtext("description", ""))[:600]
                link  = item.findtext("link", "").strip()

                if not title or not _is_gta6_news(title, desc):
                    continue
                # Déduplication par titre normalisé
                key = re.sub(r"\W+", "", title.lower())[:60]
                if key in seen:
                    continue
                seen.add(key)

                image_url = _feed_image(item)

                # Fallback og:image uniquement pour les sources gaming (pas Google News)
                if not image_url and link.startswith("http") and source_name != "Google News":
                    image_url = _og_image(link)

                articles.append({
                    "title":     title,
                    "body":      desc,
                    "score":     0,
                    "comments":  0,
                    "flair":     source_name,
                    "url":       link,
                    "subreddit": "news",
                    "image_url": image_url,
                })
                gta6_count += 1

            if gta6_count:
                log.info(f"  {source_name}: {gta6_count} articles GTA 6")

        except Exception as e:
            log.warning(f"News fetch failed ({source_name}): {e}")

    # Trier : articles avec image en premier, puis par source (Google News en dernier)
    articles.sort(key=lambda x: (0 if x["image_url"] else 1, x["flair"] == "Google News"))
    result = articles[:limit]
    log.info(f"News: {len(result)} articles GTA 6 collectés ({sum(1 for a in result if a['image_url'])} avec image)")
    if result:
        _save_posts_cache(result)
    return result
