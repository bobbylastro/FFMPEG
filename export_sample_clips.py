"""
Exporte N clips par jeu en fetchant directement depuis Twitch.
Usage : python export_sample_clips.py [--per-game 5] [--out sample_clips]
"""
import argparse
import logging
import os
import re
import yt_dlp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

from src.fetch_clips_website import fetch_website_clips
from src.select_clips_website_ai import select_website_clips

GAMES = [
    "valorant",
    "apex-legends",
    "marvel-rivals",
    "the-finals",
    "rocket-league",
    "rainbow-six-siege",
]

parser = argparse.ArgumentParser()
parser.add_argument("--per-game", type=int, default=5)
parser.add_argument("--out", default="sample_clips")
args = parser.parse_args()


def sanitize(name: str) -> str:
    return re.sub(r"[^\w\-.]", "_", name)[:60]


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
            for f in os.listdir(os.path.dirname(dest)):
                if f.startswith(os.path.basename(base)):
                    os.rename(os.path.join(os.path.dirname(dest), f), dest)
                    break
        return os.path.exists(dest)
    except Exception as e:
        log.warning(f"    Download failed: {e}")
        return False


total_ok = 0
total_fail = 0

for game_slug in GAMES:
    log.info(f"\n  [{game_slug}] Fetch Twitch...")

    candidates = fetch_website_clips(game_slug, limit=30, days=150)
    if not candidates:
        log.warning(f"  [{game_slug}] Aucun candidat Twitch trouvé")
        continue

    selected = select_website_clips(candidates, n=args.per_game, game_slug=game_slug)
    if not selected:
        log.warning(f"  [{game_slug}] IA n'a rien retenu")
        continue

    out_dir = os.path.join(args.out, game_slug)
    os.makedirs(out_dir, exist_ok=True)

    ok = 0
    for clip in selected:
        title_safe = sanitize(clip.get("title", clip["id"]))
        dest = os.path.join(out_dir, f"{title_safe}.mp4")

        if os.path.exists(dest):
            log.info(f"    déjà présent : {dest}")
            ok += 1
            continue

        if download_twitch(clip["url"], dest):
            size_kb = os.path.getsize(dest) // 1024
            log.info(f"    ✅  {title_safe}.mp4  ({size_kb} KB)")
            ok += 1
        else:
            total_fail += 1

    total_ok += ok
    log.info(f"  [{game_slug}] {ok}/{len(selected)} téléchargés")

log.info(f"\nTotal : {total_ok} clips OK, {total_fail} échecs")
