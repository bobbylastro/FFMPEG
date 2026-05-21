import json
import logging
import os
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
TOKEN_PATH    = "token.json"
CATEGORY_GAMING = "20"


def _get_credentials(game_slug: str = None) -> Credentials:
    """Charge les credentials pour le compte YouTube du jeu donné.

    Ordre de priorité :
    1. YOUTUBE_TOKEN_<GAME_SLUG> (ex. YOUTUBE_TOKEN_VALORANT)
    2. YOUTUBE_TOKEN (fallback générique)
    3. token.json (local)
    """
    token_data = None

    if game_slug:
        env_key = "YOUTUBE_TOKEN_" + game_slug.upper().replace("-", "_")
        env_token = os.getenv(env_key)
        if env_token:
            token_data = json.loads(env_token)
            log.info(f"Credentials chargées depuis {env_key}")

    if token_data is None:
        env_token = os.getenv("YOUTUBE_TOKEN")
        if env_token:
            token_data = json.loads(env_token)
            log.info("Credentials chargées depuis YOUTUBE_TOKEN")

    if token_data is None:
        if os.path.exists(TOKEN_PATH):
            with open(TOKEN_PATH) as f:
                token_data = json.load(f)
            log.info(f"Credentials chargées depuis {TOKEN_PATH}")
        else:
            raise FileNotFoundError(
                "Aucun token YouTube trouvé. Lance auth_youtube.py en local d'abord."
            )

    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data["refresh_token"],
        token_uri=token_data["token_uri"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=token_data["scopes"],
    )

    # Rafraîchir si expiré
    if not creds.valid:
        creds.refresh(Request())

    return creds


def upload_video(
    video_path: str,
    title: str,
    description: str,
    thumbnail_path: str = None,
    tags: list[str] = None,
    privacy: str = "public",
    game_slug: str = None,
    publish_at: str = None,
) -> str:
    """
    Upload une vidéo sur YouTube et retourne son video_id.

    privacy    : "public" | "unlisted" | "private"
    publish_at : ISO 8601 (ex. "2026-05-19T12:00:00Z") — programme la publication
                 automatiquement (status = "scheduled", basculera en public à cette heure)
    """
    creds   = _get_credentials(game_slug=game_slug)
    youtube = build("youtube", "v3", credentials=creds)

    status_body = {"selfDeclaredMadeForKids": False}
    if publish_at:
        status_body["privacyStatus"] = "private"
        status_body["publishAt"]     = publish_at
    else:
        status_body["privacyStatus"] = privacy

    body = {
        "snippet": {
            "title":       title[:100],
            "description": description,
            "tags":        tags or [],
            "categoryId":  CATEGORY_GAMING,
        },
        "status": status_body,
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=8 * 1024 * 1024,  # 8 MB chunks
    )

    log.info(f"Upload YouTube : {title}")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    video_id = None
    while video_id is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            log.info(f"  Upload : {pct}%")
        if response:
            video_id = response["id"]

    log.info(f"  Vidéo uploadée → https://youtu.be/{video_id}")

    # Thumbnail
    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
            ).execute()
            log.info(f"  Miniature uploadée")
        except HttpError as e:
            log.warning(f"  Miniature échouée : {e}")

    return video_id


def upload_from_content(content_path: str, privacy: str = "public", game_slug: str = None) -> str:
    """
    Charge un fichier content_*.json et upload la compilation YouTube.
    Retourne le video_id.
    """
    with open(content_path, encoding="utf-8") as f:
        content = json.load(f)

    yt = content["youtube"]
    game_slug = game_slug or content.get("game_slug")

    import re
    tags = re.findall(r"#(\w+)", yt["description"])[:15]

    video_id = upload_video(
        video_path=yt["video"],
        title=yt["title"],
        description=yt["description"],
        thumbnail_path=yt.get("thumbnail"),
        tags=tags,
        privacy=privacy,
        game_slug=game_slug,
    )

    content["youtube"]["video_id"] = video_id
    content["youtube"]["url"]      = f"https://youtu.be/{video_id}"
    with open(content_path, "w", encoding="utf-8") as f:
        json.dump(content, f, indent=2, ensure_ascii=False)

    return video_id


def upload_shorts_from_content(content_path: str) -> list[str]:
    """
    Upload tous les Shorts depuis un content_*.json.
    - Short J1 : schedulé +2h après l'upload
    - Short J2 : schedulé +24h après l'upload
    Retourne la liste des video_ids uploadés.
    """
    import re
    from datetime import datetime, timedelta, timezone

    with open(content_path, encoding="utf-8") as f:
        content = json.load(f)

    game_slug = content.get("game_slug")
    shorts    = content.get("shorts", [])

    if not shorts:
        log.info("Aucun Short à uploader.")
        return []

    now = datetime.now(timezone.utc)
    schedule = {
        1: (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        2: (now + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    video_ids = []
    for short in shorts:
        day         = short.get("day", 1)
        clip_title  = short.get("clip_title", "")
        description = short.get("description", "")
        video_path  = short.get("video_path", "")

        title      = f"{clip_title} #Shorts"[:100]
        tags       = re.findall(r"#(\w+)", description)[:15]
        publish_at = schedule.get(day)

        video_id = upload_video(
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            game_slug=game_slug,
            publish_at=publish_at,
        )

        short["video_id"] = video_id
        short["url"]      = f"https://youtu.be/{video_id}"
        video_ids.append(video_id)
        if publish_at:
            log.info(f"  Short J{day} schedulé → https://youtu.be/{video_id} (public le {publish_at})")
        else:
            log.info(f"  Short J{day} uploadé → https://youtu.be/{video_id}")

    with open(content_path, "w", encoding="utf-8") as f:
        json.dump(content, f, indent=2, ensure_ascii=False)

    return video_ids
