import argparse
import json
import logging
import os
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from src.fetch_clips_medal import fetch_medal_clips, mark_clips_used, MEDAL_GAME_CATALOG
from src.download_clips import download_clips
from src.process_long import build_long_video
from src.process_short import build_tiktoks_per_game
from src.generate_thumbnail import generate_thumbnail, bump_episode
from src.generate_content import get_youtube_title, get_youtube_description, get_shorts_description, generate_chapters
from src.upload_youtube import upload_from_content, upload_shorts_from_content

# ── Args ───────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Run the clip pipeline for one game.")
parser.add_argument("--game", required=True,
                    choices=list(MEDAL_GAME_CATALOG.keys()),
                    help="Game slug (e.g. valorant, counter-strike-2)")
args = parser.parse_args()

game_slug = args.game
game_name = MEDAL_GAME_CATALOG[game_slug][0]   # ex. "Valorant"

print(f"\n🎮  Game : {game_name}  ({game_slug})\n")

# ── 1. Fetch & download ────────────────────────────────────────────────────
clips = fetch_medal_clips(slugs=[game_slug])
for i, c in enumerate(clips, 1):
    print(f"{i:2}. [{c['_game']:<25}] {int(c['duration']):>3}s | {c['view_count']:>7} views | {c['title']}")

downloaded = download_clips(clips)
mark_clips_used(downloaded)

# ── 2. Incrémenter l'épisode une seule fois ────────────────────────────────
episode = bump_episode(game_name)

# ── 3. Compilation longue YouTube ─────────────────────────────────────────
compilation_path = build_long_video(downloaded)

# ── 4. TikToks (top 2 clips, bruts verticaux, sans overlay) ───────────────
shorts_results = build_tiktoks_per_game(downloaded)   # [(clip, path), ...]

# ── 5. Miniature ──────────────────────────────────────────────────────────
thumbnail_path = generate_thumbnail(downloaded, game_name, episode=episode)

# ── 6. Titres & descriptions ───────────────────────────────────────────────
yt_title   = get_youtube_title(game_name, episode)
chapters   = generate_chapters(downloaded)
yt_desc    = chapters + "\n\n" + get_youtube_description(game_name, episode)

date_str  = datetime.now().strftime("%Y-%m-%d")
date_day2 = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

shorts_content = []
for idx, (clip, path) in enumerate(shorts_results, 1):
    shorts_content.append({
        "day":          idx,
        "publish_date": date_str if idx == 1 else date_day2,
        "clip_title":   clip.get("title", ""),
        "broadcaster":  clip.get("broadcaster_name", ""),
        "video_path":   path,
        "description":  get_shorts_description(clip),
    })

# ── 7. Sauvegarde du contenu ───────────────────────────────────────────────
os.makedirs("output", exist_ok=True)
content = {
    "date":      date_str,
    "game":      game_name,
    "game_slug": game_slug,
    "episode":   episode,
    "youtube": {
        "video":       compilation_path,
        "thumbnail":   thumbnail_path,
        "title":       yt_title,
        "description": yt_desc,
    },
    "shorts": shorts_content,
}

content_path = f"output/content_{date_str}_{game_slug}.json"
with open(content_path, "w", encoding="utf-8") as f:
    json.dump(content, f, indent=2, ensure_ascii=False)

# ── 8. Upload YouTube ─────────────────────────────────────────────────────
video_id   = upload_from_content(content_path, privacy="public")
short_ids  = upload_shorts_from_content(content_path)

# ── 9. Résumé ──────────────────────────────────────────────────────────────
short_urls = [f"https://youtu.be/{vid}" for vid in short_ids]
print(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅  {game_name} #{episode} — pipeline terminé
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📺  YouTube   : https://youtu.be/{video_id}
▶️  Short J1  : {short_urls[0] if len(short_urls) > 0 else 'N/A'}
▶️  Short J2  : {short_urls[1] if len(short_urls) > 1 else 'N/A'}
🖼️   Miniature : {os.path.basename(thumbnail_path)}
📄  Contenu   : {content_path}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━""")
