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

_NEWS_SOURCES_BASE = [
    # Sources fixes connues — feed URL validée manuellement
    ("GameSpot",     "https://www.gamespot.com/feeds/news/"),
    ("IGN",          "https://feeds.ign.com/ign/all"),
    ("GamesRadar",   "https://www.gamesradar.com/rss/"),
    ("PCGamer",      "https://www.pcgamer.com/rss/"),
    ("Destructoid",  "https://www.destructoid.com/feed/"),
    ("Eurogamer",    "https://www.eurogamer.net/feed"),
    ("RPS",          "https://www.rockpapershotgun.com/feed"),
    ("VG247",        "https://www.vg247.com/feed"),
    ("Push Square",  "https://www.pushsquare.com/feeds/latest"),
    ("Kotaku",       "https://kotaku.com/rss"),
    ("VGC",          "https://www.videogameschronicle.com/feed/"),
    ("GTA BOOM",     "https://www.gtaboom.com/feed/"),
    ("WhatIfGaming", "https://whatifgaming.com/feed/"),
    ("TechRadar",    "https://www.techradar.com/rss"),
    ("FandomWire",   "https://fandomwire.com/feed/"),
]

_GNEWS_QUERY = "https://news.google.com/rss/search?q=GTA+6+grand+theft+auto&hl=en-US&gl=US&ceid=US:en"
_RSS_PATTERNS = ["/feed/", "/feed", "/rss/", "/rss", "/rss.xml", "/feeds/rss2", "/feeds/latest"]
_DISCOVERED_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "gta6_discovered_feeds.json")


def _discover_sources_from_gnews() -> list[tuple[str, str]]:
    """Fetch Google News RSS pour GTA 6, extrait les domaines sources,
    tente de trouver leur feed RSS direct. Résultats mis en cache 24h."""
    import time
    from urllib.parse import urlparse
    from concurrent.futures import ThreadPoolExecutor

    # Cache 24h
    if os.path.exists(_DISCOVERED_CACHE_FILE):
        with open(_DISCOVERED_CACHE_FILE, encoding="utf-8") as f:
            cached = json.load(f)
        if time.time() - cached.get("ts", 0) < 86400:
            log.info(f"  Discovered feeds (cache) : {len(cached['feeds'])} sources")
            return [(name, url) for name, url in cached["feeds"]]

    log.info("  Découverte des sources via Google News RSS…")
    known_domains = {urlparse(url).netloc for _, url in _NEWS_SOURCES_BASE}

    try:
        req = urllib.request.Request(_GNEWS_QUERY, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            xml_data = r.read()
        root = ET.fromstring(xml_data)
        items = root.findall(".//item")
    except Exception as e:
        log.warning(f"  Google News RSS fetch failed : {e}")
        return []

    # Extraire les domaines uniques depuis <source url="...">
    new_domains: dict[str, str] = {}
    for item in items:
        src = item.find("source")
        if src is None:
            continue
        name = (src.text or "").strip()
        domain_url = src.get("url", "").strip()
        if not domain_url:
            continue
        domain = urlparse(domain_url).netloc
        if domain and domain not in known_domains and domain not in new_domains:
            new_domains[domain] = name

    log.info(f"  {len(new_domains)} nouveaux domaines à tester…")

    def probe_feed(domain_name: tuple[str, str]) -> tuple[str, str] | None:
        domain, name = domain_name
        for pat in _RSS_PATTERNS:
            url = f"https://{domain}{pat}"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    data = r.read(4000)
                if b"<rss" in data or b"<feed" in data or b"<channel" in data:
                    return (name, url)
            except Exception:
                continue
        return None

    discovered: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=10) as exc:
        for result in exc.map(probe_feed, new_domains.items()):
            if result:
                discovered.append(result)
                log.info(f"    ✓ {result[0]} → {result[1]}")

    log.info(f"  {len(discovered)} nouveaux feeds découverts")

    os.makedirs(os.path.dirname(os.path.abspath(_DISCOVERED_CACHE_FILE)), exist_ok=True)
    with open(_DISCOVERED_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"ts": time.time(), "feeds": discovered}, f, indent=2, ensure_ascii=False)

    return discovered

_MEDIA_NS   = {"media":   "http://search.yahoo.com/mrss/"}
_CONTENT_NS = {"content": "http://purl.org/rss/1.0/modules/content/"}

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


def _fetch_article_data(url: str) -> tuple[str, str]:
    """Fetch l'URL et retourne (og_image_url, article_body_text) via trafilatura.
    Trafilatura extrait le texte principal en ignorant nav/pubs/sidebar — bien plus fiable
    qu'un parsing regex naïf."""
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return "", ""

        # og:image depuis le HTML brut
        image_url = ""
        for pat in [
            r'property=["\']og:image["\']\s*content=["\']([^"\']+)',
            r'content=["\']([^"\']+)["\']\s*property=["\']og:image',
        ]:
            m = re.search(pat, downloaded)
            if m:
                image_url = _upgrade_image_url(m.group(1).strip())
                break

        # Corps de l'article via trafilatura
        body_text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        ) or ""
        body_text = re.sub(r'\s+', ' ', body_text).strip()[:2500]

        return image_url, body_text
    except Exception:
        return "", ""



# ── Blocklist articles déjà utilisés ─────────────────────────────────────────

_USED_ARTICLES_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "gta6_used_articles.json")
_MAX_ARTICLE_AGE_DAYS = 10


def _load_used_urls() -> set[str]:
    if not os.path.exists(_USED_ARTICLES_FILE):
        return set()
    with open(_USED_ARTICLES_FILE, encoding="utf-8") as f:
        return set(json.load(f))


def mark_articles_used(posts: list[dict]) -> None:
    """Ajoute les URLs des posts utilisés à la blocklist (à appeler après génération du script)."""
    used = _load_used_urls()
    for p in posts:
        if p.get("url") and "google.com" not in p["url"]:
            used.add(p["url"])
    os.makedirs(os.path.dirname(os.path.abspath(_USED_ARTICLES_FILE)), exist_ok=True)
    with open(_USED_ARTICLES_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(used), f, indent=2, ensure_ascii=False)


def _parse_pub_date(item: ET.Element) -> float:
    """Retourne le timestamp de pubDate, ou 0 si absent/non parsable."""
    from email.utils import parsedate_to_datetime
    raw = item.findtext("pubDate", "").strip()
    if not raw:
        return 0.0
    try:
        return parsedate_to_datetime(raw).timestamp()
    except Exception:
        return 0.0


def _enrich_articles(articles: list[dict], max_workers: int = 6) -> list[dict]:
    """Fetch le contenu complet de chaque article en parallèle (image + corps).
    Remplace l'extrait RSS par le vrai texte de l'article quand disponible."""
    from concurrent.futures import ThreadPoolExecutor

    def enrich(art: dict) -> dict:
        url = art.get("url", "")
        if not url or "google.com" in url:
            return art
        fetched_image, fetched_body = _fetch_article_data(url)
        result = dict(art)
        if fetched_image and not result.get("image_url"):
            result["image_url"] = fetched_image
        if fetched_body and len(fetched_body) > len(result.get("body", "")):
            result["body"] = fetched_body
            log.debug(f"  Corps enrichi ({len(fetched_body)} chars) : {art['title'][:60]}")
        return result

    log.info(f"  Fetch contenu complet des articles ({len(articles)} articles, {max_workers} workers)…")
    with ThreadPoolExecutor(max_workers=max_workers) as exc:
        enriched = list(exc.map(enrich, articles))
    full_count = sum(1 for a, b in zip(articles, enriched) if len(b.get("body", "")) > len(a.get("body", "")))
    log.info(f"  {full_count}/{len(articles)} articles enrichis avec le contenu complet")
    return enriched


def fetch_news_posts(limit: int = 15) -> list[dict]:
    """
    Collecte des articles GTA 6 depuis des flux RSS gaming.
    - Sources fixes (_NEWS_SOURCES_BASE) + sources dynamiques découvertes via Google News RSS
    - Ignore les articles déjà utilisés (blocklist data/gta6_used_articles.json)
    - Ignore les articles de plus de MAX_ARTICLE_AGE_DAYS jours
    - Enrichit chaque article avec le contenu complet (content:encoded ou trafilatura)
    Retourne dans le même format que fetch_reddit_posts().
    """
    import time
    used_urls  = _load_used_urls()
    cutoff     = time.time() - _MAX_ARTICLE_AGE_DAYS * 86400
    seen_titles: set[str] = set()
    articles: list[dict] = []

    # Sources fixes + sources découvertes dynamiquement depuis Google News
    discovered = _discover_sources_from_gnews()
    all_sources = _NEWS_SOURCES_BASE + discovered
    log.info(f"  {len(_NEWS_SOURCES_BASE)} sources fixes + {len(discovered)} découvertes = {len(all_sources)} total")

    for source_name, feed_url in all_sources:
        try:
            req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)

            items = root.findall(".//item")
            gta6_count = 0
            for item in items:
                title = _clean_html(item.findtext("title", ""))
                desc_raw     = _clean_html(item.findtext("description", ""))
                link  = item.findtext("link", "").strip()

                # Filtre GTA 6 sur titre + 300 premiers chars de la desc (évite les faux positifs
                # quand GTA 6 est juste mentionné en passant dans un long article sur autre chose)
                if not title or not _is_gta6_news(title, desc_raw[:300]):
                    continue

                # Enrich body : préfère content:encoded (texte complet) à la description courte
                content_node = item.find("content:encoded", _CONTENT_NS)
                content_full = _clean_html(content_node.text or "") if content_node is not None else ""
                desc = content_full[:2500] if len(content_full) > len(desc_raw) else desc_raw[:2500]

                # Filtre : article déjà utilisé
                if link in used_urls:
                    continue

                # Filtre : article trop vieux
                pub_ts = _parse_pub_date(item)
                if pub_ts and pub_ts < cutoff:
                    continue

                # Déduplication par titre normalisé
                key = re.sub(r"\W+", "", title.lower())[:60]
                if key in seen_titles:
                    continue
                seen_titles.add(key)

                articles.append({
                    "title":     title,
                    "body":      desc,
                    "score":     0,
                    "comments":  0,
                    "flair":     source_name,
                    "url":       link,
                    "subreddit": "news",
                    "image_url": _feed_image(item),
                })
                gta6_count += 1
                if gta6_count >= 5:  # max 5 articles par source pour garder la diversité
                    break

            if gta6_count:
                log.info(f"  {source_name}: {gta6_count} articles GTA 6")

        except Exception as e:
            log.warning(f"News fetch failed ({source_name}): {e}")

    skipped = len(used_urls)
    log.info(f"  ({skipped} articles déjà utilisés ignorés, fenêtre {_MAX_ARTICLE_AGE_DAYS}j)")

    # Trier : contenu jeu en premier, industrie/people en dernier
    _INDUSTRY_KW = [
        "houser", "layoff", "crunch", "overtime", "developer left", "fired", "quit",
        "take-two", "take two", "ceo", "executive", "studio head", "job cut", "union",
        "strike", "analyst", "investor", "stock", "earnings", "acquisition", "ipo",
        "lawsuit", "settlement", "discrimination", "harassment",
    ]
    def _is_industry(art: dict) -> bool:
        text = (art.get("title", "") + " " + art.get("body", "")[:300]).lower()
        return any(kw in text for kw in _INDUSTRY_KW)

    articles.sort(key=lambda x: (
        1 if _is_industry(x) else 0,   # industrie/people → fin
        0 if x["image_url"] else 1,    # avec image → avant sans image
    ))
    # Limiter avant d'enrichir (évite de fetch 40 articles)
    articles = articles[:limit]

    # Fallback : fetch page HTML pour les articles dont le body RSS est encore court
    thin = [a for a in articles if len(a.get("body", "")) < 300 and a.get("url") and "google.com" not in a.get("url", "")]
    if thin:
        log.info(f"  {len(thin)} articles avec body court → fetch page HTML…")
        articles = _enrich_articles(articles)

    log.info(f"News: {len(articles)} articles GTA 6 collectés ({sum(1 for a in articles if a['image_url'])} avec image)")
    if articles:
        _save_posts_cache(articles)
    return articles
