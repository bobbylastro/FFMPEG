"""
Upload clips vers Cloudflare R2 + ingest Supabase pour Ultimate Playground.
Gère aussi la suppression automatique des clips anciens à faible engagement.
"""
import logging
import os
import requests
import boto3
from botocore.config import Config
from datetime import datetime, timedelta, timezone

from config.settings import (
    R2_ENDPOINT, R2_ACCESS_KEY, R2_SECRET_KEY, R2_BUCKET,
    SUPABASE_URL, SUPABASE_SERVICE_KEY,
    INGEST_API_URL, INGEST_API_KEY,
)

log = logging.getLogger(__name__)


def _r2():
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def _sb_headers() -> dict:
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def upload_clip(game_slug: str, local_path: str, filename: str, title: str) -> bool:
    """Upload un clip dans R2 (<game>/<filename>) puis notifie l'API d'ingest."""
    if not R2_ACCESS_KEY or not R2_SECRET_KEY:
        log.warning("  R2 credentials manquants — upload skippé")
        return False

    r2_key = f"{game_slug}/{filename}"
    try:
        with open(local_path, "rb") as fh:
            _r2().put_object(
                Bucket=R2_BUCKET,
                Key=r2_key,
                Body=fh,
                ContentType="video/mp4",
            )
        log.info(f"    ☁️   R2 ← {r2_key}")
    except Exception as e:
        log.warning(f"    R2 upload failed ({r2_key}): {e}")
        return False

    try:
        resp = requests.post(
            INGEST_API_URL,
            headers={"x-ingest-key": INGEST_API_KEY, "Content-Type": "application/json"},
            json={"title": title, "game": game_slug, "filename": filename},
            timeout=15,
        )
        resp.raise_for_status()
        log.info(f"    ✅  Ingest OK → {filename}")
    except Exception as e:
        log.warning(f"    Ingest API failed ({filename}): {e}")

    return True


R2_PUBLIC_BASE = "https://clips.ultimate-playground.com"


def upload_public_file(local_path: str, r2_key: str, content_type: str = "video/mp4") -> str | None:
    """Upload un fichier vers R2 sous r2_key et renvoie son URL publique (sans passer par Supabase)."""
    if not R2_ACCESS_KEY or not R2_SECRET_KEY:
        log.warning("  R2 credentials manquants — upload skippé")
        return None
    try:
        with open(local_path, "rb") as fh:
            _r2().put_object(
                Bucket=R2_BUCKET,
                Key=r2_key,
                Body=fh,
                ContentType=content_type,
            )
    except Exception as e:
        log.warning(f"  R2 upload failed ({r2_key}): {e}")
        return None
    return f"{R2_PUBLIC_BASE}/{r2_key}"


def _r2_key_from_url(video_url: str) -> str:
    """Extrait le chemin R2 depuis l'URL publique (ex: 'valorant/Maus_ACE.mp4')."""
    prefix = R2_PUBLIC_BASE.rstrip("/") + "/"
    if video_url.startswith(prefix):
        return video_url[len(prefix):]
    # Fallback : on prend tout ce qui est après le domaine
    from urllib.parse import urlparse
    return urlparse(video_url).path.lstrip("/")


def delete_old_clips(age_days: int = 300, min_watch_ratio: float = 0.3, min_views: int = 50) -> None:
    """Supprime de Supabase + R2 les clips anciens à faible engagement."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        log.warning("  Supabase credentials manquants — cleanup skippé")
        return

    cutoff = (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()
    headers = _sb_headers()

    # Étape 1 : clips anciens (sans join pour éviter les problèmes de FK PostgREST)
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/clips",
            headers=headers,
            params={"select": "id,game,video_url,created_at", "created_at": f"lt.{cutoff}"},
            timeout=15,
        )
        resp.raise_for_status()
        old_clips = resp.json()
    except Exception as e:
        log.warning(f"  Supabase query failed: {e}")
        return

    if not old_clips:
        log.info("  Nettoyage : aucun clip ancien")
        return

    # Étape 2 : scores pour ces clips (requête séparée)
    clip_ids = [str(c["id"]) for c in old_clips]
    scores_by_id: dict = {}
    try:
        sr = requests.get(
            f"{SUPABASE_URL}/rest/v1/clip_scores",
            headers=headers,
            params={
                "select": "clip_id,avg_watch_ratio,view_count",
                "clip_id": f"in.({','.join(clip_ids)})",
            },
            timeout=15,
        )
        sr.raise_for_status()
        for row in sr.json():
            scores_by_id[str(row["clip_id"])] = row
    except Exception as e:
        log.warning(f"  Supabase scores query failed: {e} — cleanup skippé")
        return

    # Étape 3 : filtrer par engagement
    to_delete = []
    for clip in old_clips:
        score = scores_by_id.get(str(clip["id"]), {})
        if score.get("avg_watch_ratio", 1.0) < min_watch_ratio or score.get("view_count", 999) < min_views:
            to_delete.append(clip)

    if not to_delete:
        log.info("  Nettoyage : rien à supprimer")
        return

    log.info(f"  Nettoyage : {len(to_delete)} clips anciens à faible engagement")
    r2 = _r2() if R2_ACCESS_KEY and R2_SECRET_KEY else None

    for clip in to_delete:
        cid       = clip["id"]
        video_url = clip.get("video_url", "")

        # Supabase en premier — si ça fail, R2 reste intact
        try:
            requests.delete(
                f"{SUPABASE_URL}/rest/v1/clips",
                headers=headers,
                params={"id": f"eq.{cid}"},
                timeout=10,
            ).raise_for_status()
            log.info(f"    🗑️  Supabase: {cid}")
        except Exception as e:
            log.warning(f"    Supabase delete failed ({cid}): {e}")
            continue

        if r2 and video_url:
            r2_key = _r2_key_from_url(video_url)
            try:
                r2.delete_object(Bucket=R2_BUCKET, Key=r2_key)
                log.info(f"    🗑️  R2: {r2_key}")
            except Exception as e:
                log.warning(f"    R2 delete failed ({r2_key}): {e}")
