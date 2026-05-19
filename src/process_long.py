import glob
import json
import logging
import os
import random
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from PIL import ImageFont

from config.settings import OUTPUT_LONG

MUSIC_DIR        = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "music"))
CLIP_AUDIO_VOL   = 0.40   # Sons du jeu (réduits mais audibles)
MUSIC_VOL        = 0.40   # Musique de fond

log = logging.getLogger(__name__)

_ASSETS = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")
FONT         = os.path.abspath(os.path.join(_ASSETS, "Ubuntu-B.ttf"))
FONT_REGULAR = os.path.abspath(os.path.join(_ASSETS, "OpenSans-Regular.ttf"))
LOGO_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "logo.png"))
# Logo source is 200×100 (2:1). Scale height to fit 2 text lines comfortably.
LOGO_W = 350
LOGO_H = 150
OVERLAY_DURATION = 5
FADE_DUR = 0.4
HOLD_END = OVERLAY_DURATION - FADE_DUR


LOGO_X = 20
TEXT_X = 85
_TEXT_MAX_PX = (LOGO_X + LOGO_W) - TEXT_X - 15   # right padding 15px


def _fit_text(text: str, font_path: str, fontsize: int, max_px: int) -> str:
    try:
        font = ImageFont.truetype(font_path, fontsize)
        if font.getlength(text) <= max_px:
            return text
        while text:
            text = text[:-1]
            if font.getlength(text + "…") <= max_px:
                return text + "…"
        return "…"
    except Exception:
        return text[:40]


def _sanitize(text: str) -> str:
    # Garde uniquement les caractères ASCII imprimables
    return re.sub(r'[^\x20-\x7E]', '', text).strip()


def _apply_overlay(clip: dict, output_path: str) -> None:
    raw_title = clip.get("title", "")
    raw_broadcaster = clip.get("broadcaster_name", "")
    title = _fit_text(_sanitize(raw_title), FONT, 28, _TEXT_MAX_PX)
    broadcaster = _fit_text(_sanitize(raw_broadcaster), FONT_REGULAR, 21, _TEXT_MAX_PX)

    # Écrire dans des fichiers temp — évite tout escaping dans filter_complex
    clip_id = clip.get("id", "clip")
    title_file = f"/tmp/dt_title_{clip_id}.txt"
    sub_file   = f"/tmp/dt_sub_{clip_id}.txt"
    with open(title_file, "w") as f:
        f.write(title)
    with open(sub_file, "w") as f:
        f.write(broadcaster)

    alpha = (
        f"if(lt(t\\,{FADE_DUR})\\,t/{FADE_DUR}"
        f"\\,if(lt(t\\,{HOLD_END})\\,1"
        f"\\,if(lt(t\\,{OVERLAY_DURATION})\\,({OVERLAY_DURATION}-t)/{FADE_DUR}\\,0)))"
    )
    slide = f"if(lt(t\\,{FADE_DUR})\\,(1-t/{FADE_DUR})*25\\,0)"

    encode_args = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
                   "-c:a", "aac", "-b:a", "128k", "-ar", "48000"]

    # Logo bottom margin: 12px from bottom of frame
    logo_y = 1080 - LOGO_H - 12

    # Text Y positions are fixed regardless of logo size
    ty_title = 968   # H-112
    ty_sub   = 1006  # H-74

    has_logo = os.path.exists(LOGO_PATH)

    if has_logo:
        # Single-pass filter_complex:
        # 1. Scale/pad/fps the raw clip → [base]
        # 2. Loop logo image, scale to LOGO_W×LOGO_H, fade in/out → [logo]
        # 3. Overlay logo on [base] → add drawtext on top → [out]
        logo_fc = (
            f"[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
            f"fps=30,setpts=PTS-STARTPTS[base];"

            f"[1:v]loop=loop=-1:size=1:start=0,"
            f"scale={LOGO_W}:{LOGO_H},format=rgba,"
            f"fade=type=in:start_time=0:duration={FADE_DUR}:alpha=1,"
            f"fade=type=out:start_time={HOLD_END}:duration={FADE_DUR}:alpha=1[logo];"

            f"[base][logo]overlay=x=20:y={logo_y}:shortest=1,"

            f"drawtext=fontfile={FONT}:textfile={title_file}:"
            f"x=85:y='{ty_title}+{slide}':"
            f"alpha='{alpha}':"
            f"fontsize=28:fontcolor=white:"
            f"shadowx=2:shadowy=2:shadowcolor=black@0.8,"

            f"drawtext=fontfile={FONT_REGULAR}:textfile={sub_file}:"
            f"x=85:y='{ty_sub}+{slide}':"
            f"alpha='{alpha}':"
            f"fontsize=21:fontcolor=white@0.9:"
            f"shadowx=2:shadowy=2:shadowcolor=black@0.8"

            f"[out]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", clip["local_path"],
            "-i", LOGO_PATH,
            "-filter_complex", logo_fc,
            "-map", "[out]",
            "-map", "0:a?",
            *encode_args,
            output_path,
        ]
    else:
        vf = (
            "scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
            "fps=30,setpts=PTS-STARTPTS,"

            f"drawtext=fontfile={FONT}:textfile={title_file}:"
            f"x=28:y='H-112+{slide}':"
            f"alpha='{alpha}':"
            f"fontsize=28:fontcolor=white:"
            f"box=1:boxcolor=black@0.55:boxborderw=6,"

            f"drawtext=fontfile={FONT_REGULAR}:textfile={sub_file}:"
            f"x=28:y='H-74+{slide}':"
            f"alpha='{alpha}':"
            f"fontsize=20:fontcolor=white@0.9:"
            f"box=1:boxcolor=black@0.55:boxborderw=5"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", clip["local_path"],
            "-vf", vf,
            *encode_args,
            output_path,
        ]

    result = subprocess.run(cmd, capture_output=True)
    for f in (title_file, sub_file):
        try:
            os.remove(f)
        except OSError:
            pass
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"Overlay failed for {clip['id']}: {result.stderr.decode()[-500:]}")


def _get_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def _add_background_music(video_path: str) -> str:
    """Mix musique de fond royalty-free avec l'audio des clips. Retourne le nouveau chemin."""
    music_files = sorted(glob.glob(os.path.join(MUSIC_DIR, "*.mp3")) +
                         glob.glob(os.path.join(MUSIC_DIR, "*.wav")))
    if not music_files:
        log.warning("Aucune musique trouvée dans assets/music/, skip")
        return video_path

    video_duration = _get_duration(video_path)

    # Sélectionner des morceaux aléatoires jusqu'à couvrir la durée
    random.shuffle(music_files)
    selected, total = [], 0.0
    while total < video_duration:
        for m in music_files:
            selected.append(m)
            total += _get_duration(m)
            if total >= video_duration:
                break

    # Fichier de concat pour la musique
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        music_list = f.name
        for m in selected:
            f.write(f"file '{m}'\n")

    out_path = video_path.replace(".mp4", "_music.mp4")
    result = subprocess.run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-f", "concat", "-safe", "0", "-i", music_list,
        "-filter_complex",
        f"[0:a]volume={CLIP_AUDIO_VOL}[orig];"
        f"[1:a]atrim=0:{video_duration:.3f},asetpts=PTS-STARTPTS,volume={MUSIC_VOL}[music];"
        f"[orig][music]amix=inputs=2:duration=first[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        out_path,
    ], capture_output=True)

    os.remove(music_list)

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        log.warning(f"Mix musique échoué : {result.stderr.decode()[-300:]}")
        return video_path

    os.replace(out_path, video_path)
    log.info(f"Musique mixée ({len(selected)} morceaux, clip={CLIP_AUDIO_VOL}, music={MUSIC_VOL})")
    return video_path


def build_long_video(clips: list[dict]) -> str:
    if not clips:
        raise ValueError("No clips to process")

    os.makedirs(OUTPUT_LONG, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = os.path.abspath(f"{OUTPUT_LONG}/{date_str}_compilation.mp4")

    with tempfile.TemporaryDirectory() as tmpdir:
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

    output_path = _add_background_music(output_path)

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    log.info(f"Long video ready: {output_path} ({size_mb:.1f} MB)")
    return output_path
