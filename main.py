import logging
import os
from datetime import datetime

from config.settings import LOGS_DIR

os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(f"{LOGS_DIR}/{datetime.now().strftime('%Y-%m-%d')}.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


def run():
    log.info("=== Clipflow pipeline started ===")

    # Phase 1: Fetch clips
    from src.fetch_clips import fetch_top_clips
    clips = fetch_top_clips()
    log.info(f"Fetched {len(clips)} clips")

    # Phase 2: Download
    from src.download_clips import download_clips
    from src.fetch_clips import mark_clips_used
    downloaded = download_clips(clips)
    log.info(f"Downloaded {len(downloaded)} clips")
    mark_clips_used(downloaded)

    # Phase 3: Process
    from src.process_long import build_long_video
    from src.process_short import build_shorts, build_tiktok
    long_path = build_long_video(downloaded)
    shorts_path = build_shorts(downloaded[:3])
    tiktok_path = build_tiktok(downloaded[0])

    # Phase 4: Upload
    from src.upload_youtube import upload_long, upload_short
    from src.upload_tiktok import upload_tiktok
    upload_long(long_path)
    upload_short(shorts_path)
    upload_tiktok(tiktok_path)

    log.info("=== Pipeline complete ===")


if __name__ == "__main__":
    run()
