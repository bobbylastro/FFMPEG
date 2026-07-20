"""
Compile les clips URKL validés en vidéo YouTube (compilation longue + Short) et upload
les deux, avec titre/description/miniature générés comme pour les autres jeux.

- Compilation longue : tous les clips validés (overlay titre/logo + musique, comme R6)
- Short : les 4 premiers clips validés, concaténés en une seule vidéo verticale
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "src"))

import json as _json

import urkl_r2 as r2lib
from config.settings import OUTPUT_SHORTS
from generate_content import get_youtube_title, get_youtube_description, generate_ai_content
from generate_thumbnail import generate_thumbnail, bump_episode
from process_long import build_long_video
from upload_youtube import upload_video

MOMENTS_JSON = os.path.join(BASE_DIR, "data/urkl_moments.json")
GAME_SLUG    = "urkl"
SHORT_CLIP_COUNT = 4


def _load_moments_by_fname() -> dict:
    if not os.path.exists(MOMENTS_JSON):
        return {}
    with open(MOMENTS_JSON) as f:
        moments = _json.load(f)
    return {f"clip_{idx+1:02d}.mp4": m for idx, m in enumerate(moments)}


def _build_urkl_short(clips: list[dict], tmp_dir: str) -> str:
    """Concatène les N premiers clips en une seule vidéo verticale 9:16."""
    cropped = []
    for i, c in enumerate(clips):
        out = os.path.join(tmp_dir, f"short_part_{i}.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-i", c["local_path"],
            "-vf", "crop=ih*9/16:ih,scale=1080:1920,fps=30,setpts=PTS-STARTPTS",
            "-c:v", "libx264", "-preset", "fast", "-crf", "26",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            out,
        ], capture_output=True)
        if not os.path.exists(out) or os.path.getsize(out) == 0:
            raise RuntimeError(f"Crop vertical échoué pour {c['id']}")
        cropped.append(out)

    list_path = os.path.join(tmp_dir, "short_list.txt")
    with open(list_path, "w") as f:
        for p in cropped:
            f.write(f"file '{p}'\n")

    os.makedirs(OUTPUT_SHORTS, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_path = os.path.abspath(f"{OUTPUT_SHORTS}/{date_str}_urkl_short.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
        "-c", "copy", "-movflags", "+faststart", out_path,
    ], capture_output=True)

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError("build_urkl_short: concat échoué")
    return out_path


def compile_youtube(validated_files: list[str], log=print) -> dict:
    """Télécharge les clips validés, monte compilation + Short, génère le contenu et
    upload les deux sur YouTube. Retourne {"ok": bool, "long_url", "short_url", "error"}."""
    r2 = r2lib.client()
    moments_by_fname = _load_moments_by_fname()
    tmp_dir = tempfile.mkdtemp(prefix="urkl_yt_compile_")

    try:
        clips = []
        for fname in validated_files:
            local_path = os.path.join(tmp_dir, fname)
            log(f"Téléchargement {fname}...")
            r2lib.download_clip(fname, local_path, r2)

            moment = moments_by_fname.get(fname, {})
            score  = moment.get("score", 0) or 0
            reason = moment.get("reason") or "Robot combat moment"
            clips.append({
                "id":               fname.replace(".mp4", ""),
                "local_path":       local_path,
                "title":            reason[:80],
                "broadcaster_name": "URKL",
                "view_count":       int(score * 100),  # proxy pour choisir le meilleur clip (thumbnail)
                "duration":         10,
                "_game":            GAME_SLUG,
            })

        if not clips:
            return {"ok": False, "error": "Aucun clip validé"}

        short_clips = clips[:SHORT_CLIP_COUNT]

        log(f"Montage de la compilation longue ({len(clips)} clips)...")
        long_path = build_long_video(clips)

        log(f"Montage du Short ({len(short_clips)} premiers clips)...")
        short_path = _build_urkl_short(short_clips, tmp_dir)

        episode     = bump_episode(GAME_SLUG)
        title       = get_youtube_title(GAME_SLUG, episode)
        description = get_youtube_description(GAME_SLUG, episode)

        log("Génération des chapitres + titre/description du Short (Haiku)...")
        chapters, short_descs, short_titles = generate_ai_content(clips, short_clips)
        if chapters:
            description = description + f"\n\nCHAPITRES:\n{chapters}"

        log("Génération de la miniature...")
        thumb_path = generate_thumbnail(clips, GAME_SLUG, episode)

        tags = re.findall(r"#(\w+)", description)[:15]

        log("Upload YouTube — compilation longue...")
        long_id  = upload_video(
            video_path=long_path, title=title, description=description,
            thumbnail_path=thumb_path, tags=tags, privacy="public", game_slug=GAME_SLUG,
        )
        long_url = f"https://youtu.be/{long_id}"
        log(f"Compilation uploadée → {long_url}")

        short_title = short_titles[0] if short_titles else title
        short_desc  = short_descs[0] if short_descs else description
        short_tags  = re.findall(r"#(\w+)", short_desc)[:15]

        log("Upload YouTube — Short...")
        short_id  = upload_video(
            video_path=short_path, title=f"{short_title} #Shorts"[:100],
            description=short_desc, tags=short_tags, privacy="public", game_slug=GAME_SLUG,
        )
        short_url = f"https://youtu.be/{short_id}"
        log(f"Short uploadé → {short_url}")

        return {"ok": True, "long_url": long_url, "short_url": short_url}

    except Exception as e:
        log(f"ERREUR: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
