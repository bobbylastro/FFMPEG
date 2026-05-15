import logging
import os
import subprocess
import tempfile
from datetime import datetime

from config.settings import OUTPUT_SHORTS, OUTPUT_TIKTOK

log = logging.getLogger(__name__)

SHORTS_MAX_SECONDS = 59
TIKTOK_MAX_SECONDS = 60

# Crop 16:9 → 9:16 (center crop) then scale to 1080x1920
VERTICAL_FILTER = "crop=ih*9/16:ih,scale=1080:1920"


def _crop_clip(input_path: str, output_path: str, max_seconds: int = None) -> str:
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", VERTICAL_FILTER,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
    ]
    if max_seconds:
        cmd += ["-t", str(max_seconds)]
    cmd.append(output_path)

    result = subprocess.run(cmd, capture_output=True)
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr.decode()[-500:]}")
    return output_path


def build_tiktok(clip: dict) -> str:
    os.makedirs(OUTPUT_TIKTOK, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = os.path.abspath(f"{OUTPUT_TIKTOK}/{date_str}_tiktok.mp4")

    log.info(f"Building TikTok clip from: {clip['title'][:50]}")
    _crop_clip(clip["local_path"], output_path, max_seconds=TIKTOK_MAX_SECONDS)

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    log.info(f"TikTok ready: {output_path} ({size_mb:.1f} MB)")
    return output_path


def build_shorts(clips: list[dict]) -> str:
    os.makedirs(OUTPUT_SHORTS, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = os.path.abspath(f"{OUTPUT_SHORTS}/{date_str}_shorts.mp4")

    log.info(f"Building Shorts from {len(clips)} clips")

    # Crop each clip to vertical, then concat
    cropped = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, clip in enumerate(clips):
            tmp_path = f"{tmpdir}/clip_{i}.mp4"
            _crop_clip(clip["local_path"], tmp_path)
            cropped.append(tmp_path)

        # Build concat list
        list_path = f"{tmpdir}/list.txt"
        with open(list_path, "w") as f:
            for p in cropped:
                f.write(f"file '{p}'\n")

        # Concat + trim to 59s max
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-t", str(SHORTS_MAX_SECONDS),
            "-c", "copy",
            output_path,
        ], capture_output=True)

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError("Shorts build failed")

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    log.info(f"Shorts ready: {output_path} ({size_mb:.1f} MB)")
    return output_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    from src.fetch_clips import fetch_top_clips
    from src.download_clips import download_clips

    clips = fetch_top_clips(limit=3)
    downloaded = download_clips(clips)

    tiktok_path = build_tiktok(downloaded[0])
    shorts_path = build_shorts(downloaded[:3])

    print(f"TikTok : {tiktok_path}")
    print(f"Shorts : {shorts_path}")
