"""
Compilation par jeu : python run_game.py valorant
Génère une vidéo de ~10 min avec les meilleurs clips du jeu sur les 14 derniers jours.
"""
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

from src.fetch_clips_twitch import TWITCH_GAME_CATALOG, fetch_twitch_clips, mark_clips_used
from src.select_clips_ai import select_clips_ai, NoClipsSelectedError
from src.download_clips import download_clips
from src.process_long import build_long_video

CLIPS_PER_GAME_VIDEO = 20  # ~20 clips × ~20s = ~7-10 min

# Résoudre le slug depuis l'argument
if len(sys.argv) < 2:
    print("Usage: python run_game.py <slug>")
    print("Jeux disponibles:")
    for slug, name in TWITCH_GAME_CATALOG.items():
        print(f"  {slug}  ({name})")
    sys.exit(1)

slug = sys.argv[1].lower()
if slug not in TWITCH_GAME_CATALOG:
    matches = [s for s in TWITCH_GAME_CATALOG if slug in s]
    if len(matches) == 1:
        slug = matches[0]
    else:
        print(f"Jeu inconnu : {slug}")
        print(f"Disponibles : {', '.join(TWITCH_GAME_CATALOG.keys())}")
        sys.exit(1)

game_name = TWITCH_GAME_CATALOG[slug]
log.info(f"=== Compilation {game_name} ===")

candidates = fetch_twitch_clips(slug, game_name, limit=80, days=14)
if len(candidates) < CLIPS_PER_GAME_VIDEO * 2:
    log.warning(f"Seulement {len(candidates)} candidats — extension à 30 jours")
    seen = {c["id"] for c in candidates}
    more = fetch_twitch_clips(slug, game_name, limit=80, days=30)
    candidates += [c for c in more if c["id"] not in seen]

try:
    clips = select_clips_ai(candidates[:60], CLIPS_PER_GAME_VIDEO, game_name=game_name, game_slug=slug)
except NoClipsSelectedError:
    clips = candidates[:CLIPS_PER_GAME_VIDEO]

log.info(f"\n{len(clips)} clips sélectionnés :")
for i, c in enumerate(clips, 1):
    print(f"  {i:2}. {int(c['duration']):>3}s | {c['view_count']:>7} views | {c['title']}")

downloaded = download_clips(clips)
log.info(f"\n{len(downloaded)}/{len(clips)} clips téléchargés")

if not downloaded:
    log.error("Aucun clip téléchargé — abandon")
    sys.exit(1)

mark_clips_used(downloaded)

out = build_long_video(downloaded)
size_mb = os.path.getsize(out) / 1024 / 1024
print(f"\nVidéo : {out} ({size_mb:.1f} MB)")
