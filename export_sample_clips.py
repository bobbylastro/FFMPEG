"""
Exporte 5 clips par jeu depuis l'historique used_clips.
Usage : python export_sample_clips.py [--per-game 5] [--out sample_clips]
"""
import argparse
import json
import logging
import os
import re
import time
import requests
import yt_dlp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

GAMES = [
    "valorant",
    "apex-legends",
    "marvel-rivals",
    "the-finals",
    "rocket-league",
    "r6-siege",
]

parser = argparse.ArgumentParser()
parser.add_argument("--per-game", type=int, default=5)
parser.add_argument("--out", default="sample_clips")
args = parser.parse_args()


def sanitize(name: str) -> str:
    return re.sub(r"[^\w\-.]", "_", name)[:60]


def download_direct(url: str, dest: str) -> None:
    r = requests.get(url, stream=True, timeout=60, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(65536):
            f.write(chunk)


def download_twitch(url: str, dest: str) -> None:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "best[ext=mp4]/best",
        "outtmpl": dest.replace(".mp4", ".%(ext)s"),
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    # yt-dlp peut changer l'extension
    if not os.path.exists(dest):
        base = dest.replace(".mp4", "")
        for f in os.listdir(os.path.dirname(dest)):
            if f.startswith(os.path.basename(base)):
                os.rename(os.path.join(os.path.dirname(dest), f), dest)
                break


total_ok = 0
total_fail = 0

for game in GAMES:
    history_path = f"data/used_clips/{game}.json"
    if not os.path.exists(history_path):
        log.warning(f"  [{game}] Pas d'historique trouvé, skipped")
        continue

    with open(history_path) as f:
        clips = json.load(f)

    # Exclure les clips Medal dont l'URL est expirée
    now = time.time()
    valid = []
    for c in clips:
        if c.get("_source") == "medal":
            m = re.search(r"exp=(\d+)", c.get("url", ""))
            if m and int(m.group(1)) < now:
                continue
        valid.append(c)

    # Prend les N clips avec le plus de vues parmi les URLs valides
    clips_sorted = sorted(valid, key=lambda c: c.get("view_count", 0), reverse=True)
    selected = clips_sorted[:args.per_game]
    log.info(f"  [{game}] {len(valid)}/{len(clips)} clips avec URL valide")

    out_dir = os.path.join(args.out, game)
    os.makedirs(out_dir, exist_ok=True)

    log.info(f"  [{game}] {len(selected)} clips sélectionnés")
    ok = 0
    for clip in selected:
        title_safe = sanitize(clip.get("title", clip["id"]))
        dest = os.path.join(out_dir, f"{title_safe}.mp4")

        if os.path.exists(dest):
            log.info(f"    déjà présent : {dest}")
            ok += 1
            continue

        try:
            source = clip.get("_source", "medal")
            if source == "medal":
                download_direct(clip["url"], dest)
            else:
                download_twitch(clip["url"], dest)

            size_kb = os.path.getsize(dest) // 1024
            log.info(f"    ✅ {title_safe}.mp4  ({size_kb} KB)")
            ok += 1
        except Exception as e:
            log.warning(f"    ❌ {clip['title'][:50]} — {e}")
            total_fail += 1

    total_ok += ok
    log.info(f"  [{game}] {ok}/{len(selected)} téléchargés\n")

log.info(f"Total : {total_ok} clips téléchargés, {total_fail} échecs")
