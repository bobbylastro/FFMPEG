import logging
import os
import re
import requests
import yt_dlp

from config.settings import OUTPUT_LONG

log = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    return re.sub(r'[^\w\-.]', '_', name)[:50]


def _download_direct(url: str, dest: str) -> None:
    r = requests.get(url, stream=True, timeout=60, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(65536):
            f.write(chunk)


def download_clips(clips: list[dict]) -> list[dict]:
    os.makedirs(OUTPUT_LONG, exist_ok=True)
    downloaded = []

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "best[ext=mp4]/best",
    }

    for clip in clips:
        clip_id = clip["id"]
        dest = f"{OUTPUT_LONG}/{clip_id}.mp4"

        if os.path.exists(dest):
            log.info(f"Already downloaded: {clip_id}")
            downloaded.append({**clip, "local_path": dest})
            continue

        log.info(f"Downloading: {clip['title'][:50]} ({clip['view_count']} views)")

        try:
            if clip.get("_source") == "medal":
                _download_direct(clip["url"], dest)
            else:
                ydl_opts["outtmpl"] = f"{OUTPUT_LONG}/{clip_id}.%(ext)s"
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([clip["url"]])
                if not os.path.exists(dest):
                    for f in os.listdir(OUTPUT_LONG):
                        if f.startswith(clip_id):
                            dest = f"{OUTPUT_LONG}/{f}"
                            break

            if os.path.exists(dest):
                downloaded.append({**clip, "local_path": dest})
            else:
                log.warning(f"File not found after download: {dest}")
        except Exception as e:
            log.warning(f"Failed to download {clip_id}: {e}")

    log.info(f"Downloaded {len(downloaded)}/{len(clips)} clips")
    return downloaded

