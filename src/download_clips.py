import logging
import os
import re
import yt_dlp

from config.settings import OUTPUT_LONG

log = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    return re.sub(r'[^\w\-.]', '_', name)[:50]


def download_clips(clips: list[dict]) -> list[dict]:
    os.makedirs(OUTPUT_LONG, exist_ok=True)
    downloaded = []

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "best[ext=mp4]/best",
        "outtmpl": f"{OUTPUT_LONG}/%(id)s.%(ext)s",
    }

    for clip in clips:
        clip_id = clip["id"]
        dest = f"{OUTPUT_LONG}/{clip_id}.mp4"

        if os.path.exists(dest):
            log.info(f"Already downloaded: {clip_id}")
            downloaded.append({**clip, "local_path": dest})
            continue

        log.info(f"Downloading: {clip['title'][:50]} ({clip['view_count']} views)")
        ydl_opts["outtmpl"] = f"{OUTPUT_LONG}/{clip_id}.%(ext)s"

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([clip["url"]])
            if os.path.exists(dest):
                downloaded.append({**clip, "local_path": dest})
            else:
                for f in os.listdir(OUTPUT_LONG):
                    if f.startswith(clip_id):
                        downloaded.append({**clip, "local_path": f"{OUTPUT_LONG}/{f}"})
                        break
        except Exception as e:
            log.warning(f"Failed to download {clip_id}: {e}")

    log.info(f"Downloaded {len(downloaded)}/{len(clips)} clips")
    return downloaded


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    from src.fetch_clips import fetch_top_clips
    clips = fetch_top_clips(limit=3)
    downloaded = download_clips(clips)
    for d in downloaded:
        size = os.path.getsize(d["local_path"]) // 1024
        print(f"  {d['local_path']} ({size} KB)")
