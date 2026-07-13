"""
Assemble les vidéos GTA 6 avec FFmpeg :
  - Fond : trailer en boucle (assets/gta6_trailers/)
  - Audio : voix TTS
  - Sous-titres brûlés dans la vidéo (sauf TikTok)
  - Long YouTube  → 16:9 1920×1080
  - Short YouTube → 9:16 1080×1920
  - TikTok        → 9:16 1080×1920, sans sous-titres
"""
import glob
import json
import logging
import math
import os
import shutil
import subprocess
import tempfile
from datetime import datetime

log = logging.getLogger(__name__)

TRAILERS_DIR = os.path.abspath("assets/gta6_trailers")
OUTPUT_DIR   = "output/gta6"


def _get_audio_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def _get_trailers() -> list[str]:
    trailers = sorted(
        glob.glob(os.path.join(TRAILERS_DIR, "*.mp4"))
        + glob.glob(os.path.join(TRAILERS_DIR, "*.mov"))
        + glob.glob(os.path.join(TRAILERS_DIR, "*.mkv"))
    )
    if not trailers:
        raise FileNotFoundError(f"Aucun trailer trouvé dans {TRAILERS_DIR}")
    return trailers


def _build_base_video(
    audio_path: str,
    duration: float,
    output_path: str,
    vertical: bool,
    trailers: list[str],
) -> None:
    """Génère la vidéo de base : trailer concaténé + audio TTS + overlay sombre."""
    w, h = (1080, 1920) if vertical else (1920, 1080)

    if vertical:
        scale = f"scale=-1:{h},crop={w}:{h}"
    else:
        scale = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        )

    vf = (
        f"{scale},"
        f"fps=24,"
        f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.45:t=fill,"
        f"format=yuv420p"
    )

    # Calculer combien de boucles du trailer sont nécessaires pour couvrir l'audio
    trailer = trailers[0]
    trailer_dur = _get_audio_duration(trailer)
    loops = math.ceil(duration / trailer_dur) + 1

    # Fichier concat : trailer répété N fois
    concat_file = output_path + ".concat.txt"
    with open(concat_file, "w") as f:
        for _ in range(loops):
            f.write(f"file '{trailer}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_file,
        "-i", audio_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v", "-map", "1:a",
        "-shortest",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    try:
        os.remove(concat_file)
    except OSError:
        pass

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"Base video failed: {result.stderr.decode()[-600:]}")


def _burn_subtitles(input_path: str, srt_path: str, output_path: str, vertical: bool) -> None:
    """Brûle les sous-titres SRT dans la vidéo."""
    font_size = 18 if vertical else 22
    margin_v  = 80 if vertical else 60

    # Escape du chemin pour le filtre subtitles (Linux)
    srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")

    sub_filter = (
        f"subtitles={srt_escaped}:force_style='"
        f"Fontname=Arial,"
        f"Fontsize={font_size},"
        f"Bold=1,"
        f"PrimaryColour=&H00FFFFFF,"
        f"OutlineColour=&H00000000,"
        f"Outline=2,"
        f"Shadow=1,"
        f"Alignment=2,"
        f"MarginV={margin_v}'"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", sub_filter,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        log.warning(f"Subtitle burn failed: {result.stderr.decode()[-400:]}")
        shutil.copy(input_path, output_path)


def build_video(
    audio_path: str,
    srt_path: str | None,
    output_path: str,
    vertical: bool = False,
) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    trailers = _get_trailers()
    duration = _get_audio_duration(audio_path)

    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "base.mp4")
        _build_base_video(audio_path, duration, base, vertical, trailers)

        if srt_path and os.path.exists(srt_path):
            _burn_subtitles(base, srt_path, output_path, vertical)
        else:
            shutil.copy(base, output_path)

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    log.info(f"Vidéo prête : {output_path} ({size_mb:.1f} MB, {duration:.0f}s)")
    return output_path


def build_long_en(audio_path: str, srt_path: str, date_str: str) -> str:
    out = os.path.join(OUTPUT_DIR, f"{date_str}_long_en.mp4")
    return build_video(audio_path, srt_path, out, vertical=False)


def build_short_en(audio_path: str, srt_path: str, date_str: str) -> str:
    out = os.path.join(OUTPUT_DIR, f"{date_str}_short_en.mp4")
    return build_video(audio_path, srt_path, out, vertical=True)


def build_tiktok_fr(audio_path: str, date_str: str) -> str:
    out = os.path.join(OUTPUT_DIR, f"{date_str}_tiktok_fr.mp4")
    return build_video(audio_path, None, out, vertical=True)
