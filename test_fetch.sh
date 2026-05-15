#!/bin/bash
echo "[]" > data/used_clips.json
rm -f output/long/*.mp4 output/shorts/*.mp4 output/tiktok/*.mp4

python3 -c "
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
from src.fetch_clips import fetch_top_clips
from src.download_clips import download_clips
from src.process_long import build_long_video
from src.process_short import build_shorts, build_tiktok

clips = fetch_top_clips()
print()
for i, c in enumerate(clips, 1):
    print(f\"{i:2}. [{c['_velocity']:>6.0f} v/day | {c['view_count']:>6} views | {int(c['duration'])}s | {c['language']}] {c['title']}\")
print()

downloaded = download_clips(clips)
print(f'\n{len(downloaded)} clips téléchargés — compilation en cours...\n')

build_long_video(downloaded)
build_shorts(downloaded[:3])
build_tiktok(downloaded[0])

print('\nDispo dans output/long/, output/shorts/, output/tiktok/')
" 2>&1 | grep -v "^\[download\]"
