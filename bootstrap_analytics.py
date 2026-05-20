"""
Récupère rétroactivement les vidéos déjà uploadées sur chaque chaîne YouTube
et les enregistre dans data/analytics/ pour initialiser le suivi.

Usage : python bootstrap_analytics.py
"""
import json
import logging
import os

from googleapiclient.discovery import build

from src.fetch_clips_medal import MEDAL_GAME_CATALOG
from src.upload_youtube import _get_credentials
from src.fetch_analytics import _load, _save, refresh_stats, print_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def _get_uploads_playlist(youtube) -> str:
    """Retourne l'ID de la playlist 'uploads' de la chaîne authentifiée."""
    resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    return resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]


def _fetch_playlist_videos(youtube, playlist_id: str, max_results: int = 50) -> list:
    """Récupère les dernières vidéos d'une playlist."""
    videos = []
    page_token = None

    while len(videos) < max_results:
        resp = youtube.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=playlist_id,
            maxResults=min(50, max_results - len(videos)),
            pageToken=page_token,
        ).execute()

        for item in resp.get("items", []):
            snip = item["snippet"]
            videos.append({
                "video_id":    item["contentDetails"]["videoId"],
                "title":       snip.get("title", ""),
                "published_at": snip.get("publishedAt", "")[:10],
            })

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return videos


def bootstrap(game_slug: str, game_name: str) -> None:
    log.info(f"Bootstrap analytics — {game_name}")

    try:
        creds   = _get_credentials(game_slug=game_slug)
        youtube = build("youtube", "v3", credentials=creds)
    except Exception as e:
        log.warning(f"  Auth échouée pour {game_name} : {e}")
        return

    try:
        playlist_id = _get_uploads_playlist(youtube)
        videos = _fetch_playlist_videos(youtube, playlist_id, max_results=50)
    except Exception as e:
        log.warning(f"  Impossible de récupérer les uploads de {game_name} : {e}")
        return

    records = _load(game_slug)
    existing_ids = {r["video_id"] for r in records}

    added = 0
    for v in videos:
        if v["video_id"] in existing_ids:
            continue
        # Détecter si c'est un Short (titre contient #Shorts)
        vtype = "short" if "#Shorts" in v["title"] or "#shorts" in v["title"] else "long"
        records.append({
            "video_id":    v["video_id"],
            "type":        vtype,
            "episode":     None,   # inconnu pour les vidéos rétroactives
            "game":        game_name,
            "title":       v["title"],
            "published_at": v["published_at"],
            "stats":       {},
        })
        existing_ids.add(v["video_id"])
        added += 1

    _save(game_slug, records)
    log.info(f"  {added} nouvelles vidéos ajoutées ({len(records)} total)")


if __name__ == "__main__":
    for slug, (name, _) in MEDAL_GAME_CATALOG.items():
        bootstrap(slug, name)

    print("\n=== Refresh des stats ===\n")
    for slug, (name, _) in MEDAL_GAME_CATALOG.items():
        refresh_stats(slug)
        print_report(slug, name)
