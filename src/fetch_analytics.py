import json
import logging
import os
from datetime import datetime, timezone

from googleapiclient.discovery import build

from src.upload_youtube import _get_credentials

log = logging.getLogger(__name__)

ANALYTICS_DIR = "data/analytics"


def _path(game_slug: str) -> str:
    return os.path.join(ANALYTICS_DIR, f"{game_slug}.json")


def _load(game_slug: str) -> list:
    path = _path(game_slug)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def _save(game_slug: str, records: list) -> None:
    os.makedirs(ANALYTICS_DIR, exist_ok=True)
    with open(_path(game_slug), "w") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def record_run(content: dict, game_slug: str) -> None:
    """Enregistre les IDs vidéo après upload pour suivi analytics."""
    records = _load(game_slug)
    existing_ids = {r["video_id"] for r in records}

    yt_id = content.get("youtube", {}).get("video_id")
    if yt_id and yt_id not in existing_ids:
        records.append({
            "video_id":    yt_id,
            "type":        "long",
            "episode":     content.get("episode"),
            "game":        content.get("game"),
            "title":       content.get("youtube", {}).get("title", ""),
            "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "stats":       {},
        })

    for short in content.get("shorts", []):
        sid = short.get("video_id")
        if sid and sid not in existing_ids:
            existing_ids.add(sid)
            records.append({
                "video_id":    sid,
                "type":        "short",
                "episode":     content.get("episode"),
                "game":        content.get("game"),
                "title":       short.get("clip_title", ""),
                "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "stats":       {},
            })

    _save(game_slug, records)
    log.info(f"[analytics] {game_slug} : {len(records)} vidéos trackées")


def refresh_stats(game_slug: str) -> None:
    """Met à jour les stats YouTube pour toutes les vidéos du jeu."""
    records = _load(game_slug)
    if not records:
        return

    try:
        creds   = _get_credentials(game_slug=game_slug)
        youtube = build("youtube", "v3", credentials=creds)
    except Exception as e:
        log.warning(f"[analytics] Auth failed pour {game_slug} : {e}")
        return

    ids = [r["video_id"] for r in records if r.get("video_id")]
    # L'API accepte max 50 IDs par requête
    for chunk_start in range(0, len(ids), 50):
        chunk = ids[chunk_start:chunk_start + 50]
        try:
            resp = youtube.videos().list(
                part="statistics",
                id=",".join(chunk),
            ).execute()
        except Exception as e:
            log.warning(f"[analytics] videos.list failed : {e}")
            continue

        stats_by_id = {
            item["id"]: item.get("statistics", {})
            for item in resp.get("items", [])
        }

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for record in records:
            vid = record.get("video_id")
            if vid in stats_by_id:
                s = stats_by_id[vid]
                record["stats"] = {
                    "views":      int(s.get("viewCount",   0)),
                    "likes":      int(s.get("likeCount",   0)),
                    "comments":   int(s.get("commentCount", 0)),
                    "checked_at": now,
                }

    _save(game_slug, records)


def _channel_path() -> str:
    return os.path.join(ANALYTICS_DIR, "channels.json")


def _load_channels() -> dict:
    path = _channel_path()
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _save_channels(data: dict) -> None:
    os.makedirs(ANALYTICS_DIR, exist_ok=True)
    with open(_channel_path(), "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def refresh_channel_stats(game_slug: str) -> None:
    """Met à jour le nombre d'abonnés de la chaîne YouTube du jeu."""
    try:
        creds   = _get_credentials(game_slug=game_slug)
        youtube = build("youtube", "v3", credentials=creds)
        resp = youtube.channels().list(part="statistics", mine=True).execute()
    except Exception as e:
        log.warning(f"[analytics] channel stats failed pour {game_slug} : {e}")
        return

    items = resp.get("items", [])
    if not items:
        return

    s = items[0].get("statistics", {})
    channels = _load_channels()
    channels[game_slug] = {
        "subscribers":  int(s.get("subscriberCount", 0)),
        "total_views":  int(s.get("viewCount", 0)),
        "video_count":  int(s.get("videoCount", 0)),
        "checked_at":   datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    _save_channels(channels)
    log.info(f"[analytics] {game_slug} : {channels[game_slug]['subscribers']:,} abonnés")


def print_report(game_slug: str, game_name: str) -> None:
    """Affiche un rapport de performance pour les 10 dernières vidéos."""
    records = _load(game_slug)
    if not records:
        return

    with_stats = [r for r in records if r.get("stats", {}).get("views") is not None]
    if not with_stats:
        return

    longs  = [r for r in with_stats if r["type"] == "long"]
    shorts = [r for r in with_stats if r["type"] == "short"]

    print(f"\n{'─'*55}")
    print(f"  Analytics — {game_name}")
    print(f"{'─'*55}")

    if longs:
        recent = sorted(longs, key=lambda r: r["published_at"], reverse=True)[:5]
        avg_views = sum(r["stats"]["views"] for r in longs) / len(longs)
        print(f"  Compilations ({len(longs)} total, moy. {avg_views:,.0f} vues)")
        for r in recent:
            v   = r["stats"]["views"]
            bar = "▓" * min(int(v / max(avg_views, 1) * 10), 20)
            ep  = str(r["episode"]) if r.get("episode") is not None else r.get("published_at", "?")
            print(f"    #{ep:>6}  {v:>7,} vues  {bar}")

    if shorts:
        recent = sorted(shorts, key=lambda r: r["published_at"], reverse=True)[:5]
        avg_views = sum(r["stats"]["views"] for r in shorts) / len(shorts)
        print(f"  Shorts ({len(shorts)} total, moy. {avg_views:,.0f} vues)")
        for r in recent:
            v   = r["stats"]["views"]
            bar = "▓" * min(int(v / max(avg_views, 1) * 10), 20)
            ep  = str(r["episode"]) if r.get("episode") is not None else r.get("published_at", "?")
            print(f"    #{ep:>6}  {v:>7,} vues  {bar}")

    print(f"{'─'*55}\n")
