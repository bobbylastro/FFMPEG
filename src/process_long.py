import logging
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from config.settings import OUTPUT_LONG

log = logging.getLogger(__name__)

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
OVERLAY_DURATION = 5
FADE_DUR = 0.4
HOLD_END = OVERLAY_DURATION - FADE_DUR


def _escape(text: str) -> str:
    for ch, repl in [("\\", "\\\\"), ("'", "\\'"), (":", "\\:"), (",", "\\,"), ("[", "\\["), ("]", "\\]")]:
        text = text.replace(ch, repl)
    return text


def _apply_overlay(clip: dict, output_path: str) -> None:
    title = _escape(clip.get("title", "")[:45])
    broadcaster = _escape(clip.get("broadcaster_name", ""))
    game = _escape(clip.get("_game", ""))
    subline = f"{broadcaster}  •  {game}" if game else broadcaster

    # y animates upward (slide in), alpha fades in then out
    alpha = f"if(lt(t\\,{FADE_DUR})\\,t/{FADE_DUR}\\,if(lt(t\\,{HOLD_END})\\,1\\,if(lt(t\\,{OVERLAY_DURATION})\\,({OVERLAY_DURATION}-t)/{FADE_DUR}\\,0)))"
    slide = f"if(lt(t\\,{FADE_DUR})\\,(1-t/{FADE_DUR})*35\\,0)"

    vf = (
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"

        f"drawtext=fontfile={FONT}:text='{title}':"
        f"x=28:y='H-108+{slide}':"
        f"alpha='{alpha}':"
        f"fontsize=28:fontcolor=white:"
        f"box=1:boxcolor=black@0.55:boxborderw=6,"

        f"drawtext=fontfile={FONT_REGULAR}:text='{subline}':"
        f"x=28:y='H-70+{slide}':"
        f"alpha='{alpha}':"
        f"fontsize=20:fontcolor=white@0.9:"
        f"box=1:boxcolor=black@0.55:boxborderw=5"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", clip["local_path"],
        "-vf", vf,
        "-r", "30",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"Overlay failed for {clip['id']}: {result.stderr.decode()[-300:]}")


def build_long_video(clips: list[dict]) -> str:
    if not clips:
        raise ValueError("No clips to process")

    os.makedirs(OUTPUT_LONG, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = os.path.abspath(f"{OUTPUT_LONG}/{date_str}_compilation.mp4")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Apply overlays in parallel
        jobs = {i: f"{tmpdir}/clip_{i:02d}.mp4" for i in range(len(clips))}
        overlaid = [None] * len(clips)
        workers = min(len(clips), os.cpu_count() or 4)

        def _job(i):
            _apply_overlay(clips[i], jobs[i])
            return i

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_job, i): i for i in range(len(clips))}
            done = 0
            for f in as_completed(futures):
                i = f.result()
                done += 1
                overlaid[i] = jobs[i]
                log.info(f"Overlay [{done}/{len(clips)}]: {clips[i].get('title','')[:40]}")

        # Concat with stream copy (no re-encoding — clips already normalized)
        list_path = f"{tmpdir}/list.txt"
        with open(list_path, "w") as f:
            for p in overlaid:
                f.write(f"file '{p}'\n")

        log.info(f"Concatenating {len(clips)} clips → {output_path}")
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            "-movflags", "+faststart",
            output_path,
        ], capture_output=True)

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError("build_long_video failed")

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    log.info(f"Long video ready: {output_path} ({size_mb:.1f} MB)")
    return output_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    from src.fetch_clips import fetch_top_clips
    from src.download_clips import download_clips
    clips = fetch_top_clips(limit=3)
    downloaded = download_clips(clips)
    path = build_long_video(downloaded)
    print(f"Output: {path}")
