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


TRAILER_INPOINT = 8.0  # secondes à sauter au début (écrans noirs Rockstar)


def _scale_filter(vertical: bool) -> str:
    w, h = (1080, 1920) if vertical else (1920, 1080)
    if vertical:
        return f"scale=-1:{h},crop={w}:{h},fps=24,format=yuv420p"
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps=24,format=yuv420p"
    )


def _build_base_video(
    audio_path: str,
    duration: float,
    output_path: str,
    vertical: bool,
    trailers: list[str],
) -> None:
    """Génère la vidéo de base : trailer concaténé (intro skippée) + audio TTS."""
    trailer = trailers[0]
    trailer_full_dur   = _get_audio_duration(trailer)
    trailer_usable_dur = max(trailer_full_dur - TRAILER_INPOINT, 10.0)
    loops = math.ceil(duration / trailer_usable_dur) + 1

    # concat avec inpoint pour sauter l'intro noire
    concat_file = output_path + ".concat.txt"
    with open(concat_file, "w") as f:
        for _ in range(loops):
            f.write(f"file '{trailer}'\n")
            f.write(f"inpoint {TRAILER_INPOINT}\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_file,
        "-i", audio_path,
        "-vf", _scale_filter(vertical),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0", "-map", "1:a:0",
        "-t", str(duration),
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    try:
        os.remove(concat_file)
    except OSError:
        pass

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"Base video failed (rc={result.returncode}): {result.stderr.decode()[-600:]}")


def _build_mixed_video(
    image_path: str,
    audio_path: str,
    duration: float,
    output_path: str,
    vertical: bool,
    trailers: list[str],
    image_duration: float = 10.0,
) -> None:
    """10s d'image Reddit en fond, puis trailer pour le reste."""
    trailer_dur = duration - image_duration
    if trailer_dur <= 2.0:
        # Vidéo trop courte pour le split — image seule
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", image_path,
            "-i", audio_path,
            "-vf", _scale_filter(vertical),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
            "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0", "-map", "1:a:0",
            "-t", str(duration), output_path,
        ]
        result = subprocess.run(cmd, capture_output=True)
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError(f"Image-only video failed (rc={result.returncode}): {result.stderr.decode()[-400:]}")
        return

    trailer = trailers[0]
    trailer_full_dur   = _get_audio_duration(trailer)
    trailer_usable_dur = max(trailer_full_dur - TRAILER_INPOINT, 10.0)
    loops = math.ceil(trailer_dur / trailer_usable_dur) + 1

    concat_file = output_path + ".concat.txt"
    with open(concat_file, "w") as f:
        for _ in range(loops):
            f.write(f"file '{trailer}'\n")
            f.write(f"inpoint {TRAILER_INPOINT}\n")

    scale = _scale_filter(vertical)
    filter_complex = (
        f"[0:v]{scale}[img];"
        f"[1:v]{scale}[trl];"
        f"[img][trl]concat=n=2:v=1:a=0[out]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", str(image_duration), "-i", image_path,
        "-f", "concat", "-safe", "0", "-i", concat_file,
        "-i", audio_path,
        "-filter_complex", filter_complex,
        "-map", "[out]", "-map", "2:a:0",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    try:
        os.remove(concat_file)
    except OSError:
        pass

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"Mixed video failed (rc={result.returncode}): {result.stderr.decode()[-600:]}")


_FONTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "fonts"))


def _burn_subtitles(input_path: str, srt_path: str, output_path: str, vertical: bool) -> None:
    """Brûle les sous-titres dans la vidéo. Supporte SRT (long) et ASS (short)."""
    sub_escaped = srt_path.replace("\\", "/").replace(":", "\\:")
    fonts_escaped = _FONTS_DIR.replace("\\", "/").replace(":", "\\:")

    if srt_path.endswith(".ass"):
        # ASS embarque son propre style — on pointe juste vers notre dossier de fonts
        sub_filter = f"subtitles={sub_escaped}:fontsdir={fonts_escaped}"
    else:
        font_size = 18 if vertical else 22
        margin_v  = 80 if vertical else 60
        sub_filter = (
            f"subtitles={sub_escaped}:force_style='"
            f"Fontname=Open Sans,"
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
    image_path: str | None = None,
) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    duration = _get_audio_duration(audio_path)

    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "base.mp4")

        trailers = _get_trailers()
        if image_path and os.path.exists(image_path):
            log.info(f"Fond image Reddit (10s) + trailer : {os.path.basename(image_path)}")
            _build_mixed_video(image_path, audio_path, duration, base, vertical, trailers)
        else:
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


def build_short_en(audio_path: str, srt_path: str, date_str: str,
                   image_path: str | None = None) -> str:
    out = os.path.join(OUTPUT_DIR, f"{date_str}_short_en.mp4")
    return build_video(audio_path, srt_path, out, vertical=True, image_path=image_path)


_BEBAS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "assets", "fonts", "BebasNeue-Regular.otf")
)


def _add_tiktok_hook(input_path: str, hook_text: str, output_path: str) -> None:
    """Overlay texte d'accroche centré en haut, visible les 3 premières secondes."""
    import tempfile
    font_esc = _BEBAS.replace(":", "\\:")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(hook_text.upper())
        txt_file = f.name
    txt_esc = txt_file.replace(":", "\\:")

    drawtext = (
        f"drawtext=fontfile={font_esc}:textfile={txt_esc}:"
        f"fontcolor=white:fontsize=85:"
        f"x=(w-text_w)/2:y=110:"
        f"box=1:boxcolor=0x000000@0.65:boxborderw=22:"
        f"enable='between(t,0,3)'"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", drawtext,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-c:a", "copy",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    try:
        os.unlink(txt_file)
    except OSError:
        pass

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        log.warning(f"Hook overlay failed: {result.stderr.decode()[-300:]}")
        shutil.copy(input_path, output_path)


def build_tiktok_fr(audio_path: str, date_str: str, hook_text: str = "") -> str:
    out = os.path.join(OUTPUT_DIR, f"{date_str}_tiktok_fr.mp4")
    if hook_text:
        tmp = out + ".raw.mp4"
        build_video(audio_path, None, tmp, vertical=True)
        _add_tiktok_hook(tmp, hook_text, out)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return out
    return build_video(audio_path, None, out, vertical=True)
