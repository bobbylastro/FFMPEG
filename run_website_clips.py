"""
Pipeline website : fetch 10 clips Twitch par jeu, sélection IA style TikTok,
téléchargement dans public/clips/<game-slug>/.

Usage : python run_website_clips.py [--games valorant cs2 ...] [--per-game 10]
"""
import argparse
import logging
import os
import re
import subprocess
import requests
import yt_dlp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

from src.fetch_clips_website import fetch_website_clips, mark_used, WEBSITE_GAME_CATALOG
from src.select_clips_website_ai import select_website_clips
from src.r2_manager import upload_clip, delete_old_clips

CLIPS_BASE_DIR = "public/clips"
DAYS           = 120

parser = argparse.ArgumentParser()
parser.add_argument("--games", nargs="+", default=list(WEBSITE_GAME_CATALOG.keys()),
                    help="Slugs des jeux à traiter (défaut : tous)")
parser.add_argument("--per-game", type=int, default=5,
                    help="Nombre de clips à sélectionner par jeu")
args = parser.parse_args()


def sanitize(name: str) -> str:
    return re.sub(r"[^\w\-.]", "_", name)[:60]


def compress_clip(src: str, dest: str) -> bool:
    """Re-encode avec H.264 CRF 20 + faststart. Retourne False si ffmpeg échoue."""
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-vf", "scale=-2:720",
        "-c:v", "libx264", "-crf", "23", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        dest,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        log.warning(f"    Compression failed: {e.stderr.decode()[-200:]}")
        return False


def download_twitch(url: str, dest: str) -> bool:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "best[ext=mp4]/best",
        "outtmpl": dest.replace(".mp4", ".%(ext)s"),
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if not os.path.exists(dest):
            base = dest.replace(".mp4", "")
            folder = os.path.dirname(dest)
            for f in os.listdir(folder):
                if f.startswith(os.path.basename(base)):
                    os.rename(os.path.join(folder, f), dest)
                    break
        return os.path.exists(dest)
    except Exception as e:
        log.warning(f"    Download failed: {e}")
        return False


log.info("Suppression des clips anciens à faible engagement...")
delete_old_clips()

total_ok = 0
total_fail = 0

for game_slug in args.games:
    if game_slug not in WEBSITE_GAME_CATALOG:
        log.warning(f"Slug inconnu : {game_slug} — skipped")
        continue

    game_name = WEBSITE_GAME_CATALOG[game_slug]
    log.info(f"\n{'─'*50}")
    log.info(f"  {game_name} ({game_slug})")
    log.info(f"{'─'*50}")

    # 1. Fetch candidats Twitch
    BATCH = 40
    candidates = fetch_website_clips(game_slug, limit=BATCH, days=DAYS)
    if not candidates:
        log.warning(f"  Aucun candidat trouvé pour {game_slug}")
        continue

    # 2. Sélection IA — boucle par batch jusqu'à avoir args.per_game clips
    selected = []
    offset = 0
    while len(selected) < args.per_game and offset < len(candidates):
        needed = args.per_game - len(selected)
        batch  = candidates[offset:offset + BATCH]
        new    = select_website_clips(batch, n=needed, game_slug=game_slug)
        selected.extend(new)
        offset += BATCH
        if not new:
            break  # l'IA ne trouve rien dans ce batch, inutile de continuer
    if not selected:
        log.warning(f"  IA n'a sélectionné aucun clip pour {game_slug}")
        continue
    if len(selected) < args.per_game:
        log.warning(f"  [{game_slug}] Seulement {len(selected)}/{args.per_game} clips trouvés après {offset // BATCH} batch(es)")

    # 3. Téléchargement
    out_dir = os.path.join(CLIPS_BASE_DIR, game_slug)
    os.makedirs(out_dir, exist_ok=True)

    downloaded = []
    for clip in selected:
        title_safe = sanitize(clip.get("title", clip["id"]))
        dest = os.path.join(out_dir, f"{title_safe}.mp4")

        if os.path.exists(dest):
            log.info(f"    déjà présent : {dest}")
            downloaded.append(clip)
            total_ok += 1
            continue

        ok = download_twitch(clip["url"], dest)
        if ok:
            # Compress avant upload
            compressed = dest.replace(".mp4", "_c.mp4")
            size_before = os.path.getsize(dest) // 1024
            if compress_clip(dest, compressed):
                size_after = os.path.getsize(compressed) // 1024
                if size_after < size_before:
                    saving = 100 - size_after * 100 // size_before
                    log.info(f"    🗜️  {size_before} KB → {size_after} KB (-{saving}%)")
                    os.replace(compressed, dest)
                else:
                    log.info(f"    🗜️  Compression ignorée (fichier déjà optimal) : {size_before} KB")
                    os.remove(compressed)
            else:
                log.warning(f"    Compression échouée — upload du fichier original ({size_before} KB)")

            filename = os.path.basename(dest)
            upload_clip(game_slug, dest, filename, clip.get("title", title_safe))
            downloaded.append(clip)
            total_ok += 1
        else:
            total_fail += 1

    # 4. Marquer comme utilisés
    mark_used(game_slug, downloaded)
    log.info(f"  → {len(downloaded)}/{len(selected)} clips téléchargés\n")

log.info(f"\n{'='*50}")
log.info(f"  Total : {total_ok} clips OK, {total_fail} échecs")
log.info(f"{'='*50}")
