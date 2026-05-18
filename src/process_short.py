import logging
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from config.settings import OUTPUT_TIKTOK

log = logging.getLogger(__name__)

TIKTOK_MAX_SECONDS = 59

# Center-crop 16:9 → 9:16, scale to 1080×1920
VERTICAL_CROP = "crop=ih*9/16:ih,scale=1080:1920"


def _safe_game_name(game: str) -> str:
    return re.sub(r"[^\w]", "_", game).strip("_")


def _build_tiktok(clip: dict, output_path: str) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-i", clip["local_path"],
        "-t", str(TIKTOK_MAX_SECONDS),
        "-vf", f"{VERTICAL_CROP},fps=30,setpts=PTS-STARTPTS",
        "-c:v", "libx264", "-preset", "fast", "-crf", "26",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-movflags", "+faststart",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"TikTok encode failed for {clip['id']}: {result.stderr.decode()[-300:]}")


def build_tiktoks_per_game(clips: list[dict], date_str: str = None) -> list[tuple[dict, str]]:
    """Build the top 2 vertical TikTok videos per game (day1 + day2)."""
    if not clips:
        raise ValueError("No clips provided")

    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    os.makedirs(OUTPUT_TIKTOK, exist_ok=True)

    # Top 2 clips per game by view count
    by_game: dict[str, list[dict]] = {}
    for clip in clips:
        game = clip.get("_game", "unknown")
        by_game.setdefault(game, []).append(clip)

    jobs: list[tuple[dict, str]] = []
    for game, game_clips in by_game.items():
        top2 = sorted(game_clips, key=lambda c: c.get("view_count", 0), reverse=True)[:2]
        safe = _safe_game_name(game)
        for idx, clip in enumerate(top2, 1):
            out = os.path.abspath(f"{OUTPUT_TIKTOK}/{date_str}_{safe}_day{idx}.mp4")
            jobs.append((clip, out))

    log.info(f"Building {len(jobs)} TikToks ({len(by_game)} game(s) × 2)")

    results: list[tuple[dict, str]] = []

    def _job(clip_path):
        clip, out = clip_path
        _build_tiktok(clip, out)
        return clip, out

    with ThreadPoolExecutor(max_workers=min(len(jobs), 4)) as ex:
        futures = {ex.submit(_job, j): j for j in jobs}
        for f in as_completed(futures):
            clip, out = f.result()
            size_mb = os.path.getsize(out) / 1024 / 1024
            log.info(f"  [{clip['_game']}] {clip['title'][:40]} → {os.path.basename(out)} ({size_mb:.1f} MB)")
            results.append((clip, out))

    return sorted(results, key=lambda x: x[1])
