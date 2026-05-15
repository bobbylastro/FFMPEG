import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from src.fetch_clips import fetch_top_clips, mark_clips_used
from src.download_clips import download_clips
from src.process_long import build_long_video
from src.process_short import build_shorts, build_tiktok

clips = fetch_top_clips()
for i, c in enumerate(clips, 1):
    print(f"{i:2}. [{c['_game']:<22}] {c['title']}")

downloaded = download_clips(clips)
mark_clips_used(downloaded)

build_long_video(downloaded)
build_shorts(downloaded[:3])
build_tiktok(downloaded[0])

print("\nDone.")
