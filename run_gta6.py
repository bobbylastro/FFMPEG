"""
Pipeline GTA 6 — théories & news (avant lancement du jeu).

Génère 3 fichiers dans output/gta6/ :
  {date}_long_en.mp4   → YouTube long 16:9, voix EN, sous-titres brûlés
  {date}_short_en.mp4  → YouTube Short 9:16, voix EN, sous-titres brûlés
  {date}_tiktok_fr.mp4 → TikTok 9:16, voix FR, sans sous-titres (à poster manuellement)

Usage :
  python run_gta6.py
  python run_gta6.py --topic "GTA 6 map size comparison"
  python run_gta6.py --no-long   (skip la vidéo longue, plus rapide)
"""
import argparse
import logging
import os
import tempfile
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

parser = argparse.ArgumentParser()
parser.add_argument("--topic",   default="", help="Angle/sujet à privilégier (optionnel)")
parser.add_argument("--no-long", action="store_true", help="Passer la vidéo longue")
parser.add_argument("--mock",    action="store_true", help="Utiliser des posts test (sans Reddit)")
args = parser.parse_args()

date_str = datetime.now().strftime("%Y-%m-%d")
os.makedirs("output/gta6", exist_ok=True)

# ── 1. Scraping Reddit ────────────────────────────────────────────────────────
from src.fetch_gta6_content import fetch_reddit_posts

log.info("Scraping Reddit (r/GTA6, r/GTA, r/GTASeries)...")
posts = fetch_reddit_posts(limit=15, mock=args.mock)

if not posts:
    log.error("Aucun post Reddit trouvé — vérifier la connexion ou les subreddits")
    raise SystemExit(1)

log.info(f"  {len(posts)} posts collectés")
for p in posts[:5]:
    log.info(f"    [{p['score']:>6}] {p['title'][:70]}")

# ── 2. Génération des scripts IA ──────────────────────────────────────────────
from src.generate_gta6_script import generate_scripts

log.info("\nGénération des scripts (Claude Haiku)...")
scripts = generate_scripts(posts, topic=args.topic)

# ── 3. TTS ────────────────────────────────────────────────────────────────────
from src.tts_gta6 import synthesize_en, synthesize_en_short, synthesize_fr
from src.build_gta6_video import build_long_en, build_short_en, build_tiktok_fr

log.info("\nSynthèse vocale + montage vidéo...")

with tempfile.TemporaryDirectory() as tmp:
    audio_long   = os.path.join(tmp, "long_en.mp3")
    srt_long     = os.path.join(tmp, "long_en.srt")
    audio_short  = os.path.join(tmp, "short_en.mp3")
    ass_short    = os.path.join(tmp, "short_en.ass")   # ASS — style TikTok dynamique
    audio_tiktok = os.path.join(tmp, "tiktok_fr.mp3")

    paths = {}

    if not args.no_long:
        log.info("  TTS long EN...")
        synthesize_en(scripts["long_en"], audio_long, srt_long)
        log.info("  Montage long EN...")
        paths["long"] = build_long_en(audio_long, srt_long, date_str)

    log.info("  TTS short EN...")
    synthesize_en_short(scripts["short_en"], audio_short, ass_short)
    log.info("  Montage short EN...")
    paths["short"] = build_short_en(audio_short, ass_short, date_str)

    log.info("  TTS TikTok FR...")
    synthesize_fr(scripts["tiktok_fr"], audio_tiktok)
    log.info("  Montage TikTok FR...")
    paths["tiktok"] = build_tiktok_fr(audio_tiktok, date_str,
                                       hook_text=scripts.get("tiktok_hook", ""))

# ── 4. Miniature ──────────────────────────────────────────────────────────────
from src.generate_thumbnail_gta6 import generate_thumbnail_gta6

log.info("\nGénération de la miniature...")
thumb_path = generate_thumbnail_gta6(scripts["thumbnail_title"], date_str)
paths["thumbnail"] = thumb_path

# ── 5. Résumé ─────────────────────────────────────────────────────────────────
lines = [
    "",
    "━" * 50,
    "✅  GTA 6 pipeline terminé",
    "━" * 50,
]
if "long" in paths:
    lines.append(f"📺  YouTube long  → {paths['long']}")
lines.append(f"▶️   YouTube Short → {paths['short']}")
lines.append(f"🎵  TikTok FR     → {paths['tiktok']}  (poster manuellement)")
lines.append(f"🖼️   Miniature     → {paths['thumbnail']}")
lines.append("━" * 50)
log.info("\n".join(lines))
