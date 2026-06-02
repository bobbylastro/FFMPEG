import argparse
import json
import logging
import os
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from src.fetch_clips_medal import fetch_medal_clips, mark_clips_used, MEDAL_GAME_CATALOG
from src.fetch_clips_twitch import fetch_twitch_clips
from src.select_clips_ai import select_clips_ai, NoClipsSelectedError
from src.download_clips import download_clips
from src.process_long import build_long_video
from src.process_short import build_tiktoks_per_game
from src.generate_thumbnail import generate_thumbnail, bump_episode
from src.generate_content import get_youtube_title, get_youtube_description, generate_ai_content
from src.upload_youtube import upload_from_content, upload_shorts_from_content, QuotaExceededError
from src.fetch_analytics import refresh_stats, refresh_channel_stats, print_report, record_run
from src.generate_dashboard import generate as generate_dashboard
from config.settings import CLIPS_PER_VIDEO

# ── Args ───────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Run the clip pipeline for one game.")
parser.add_argument("--game", required=True,
                    choices=list(MEDAL_GAME_CATALOG.keys()),
                    help="Game slug (e.g. valorant, the-finals)")
parser.add_argument("--no-upload", action="store_true",
                    help="Process clips and save content JSON but skip YouTube upload")
parser.add_argument("--upload-only", action="store_true",
                    help="Skip processing, upload from existing content JSON")
args = parser.parse_args()

game_slug = args.game
game_name = MEDAL_GAME_CATALOG[game_slug][0]   # ex. "Valorant"

print(f"\n🎮  Game : {game_name}  ({game_slug})\n")

if not args.upload_only:
    # ── 0. Analytics du run précédent ─────────────────────────────────────────
    refresh_stats(game_slug)
    print_report(game_slug, game_name)

    # ── 1. Fetch candidates (Medal + Twitch) puis sélection IA combinée ────────
    medal_candidates  = fetch_medal_clips(slugs=[game_slug], select=False)
    twitch_candidates = fetch_twitch_clips(game_slug, game_name)

    all_candidates = medal_candidates + twitch_candidates
    print(f"\n  Medal : {len(medal_candidates)} candidats | Twitch : {len(twitch_candidates)} candidats")

    MIN_CLIPS = 6

    try:
        clips = select_clips_ai(all_candidates[:60], CLIPS_PER_VIDEO, game_name=game_name, game_slug=game_slug)
    except NoClipsSelectedError:
        clips = []

    if len(clips) < MIN_CLIPS and len(all_candidates) > 60:
        logging.warning(f"Seulement {len(clips)} clips — retry batch 2 ({len(all_candidates) - 60} candidats supplémentaires)")
        try:
            clips = select_clips_ai(all_candidates[60:120], CLIPS_PER_VIDEO, game_name=game_name, game_slug=game_slug)
        except NoClipsSelectedError:
            clips = []

    if len(clips) < MIN_CLIPS:
        logging.warning(f"Seulement {len(clips)} clips retenus (min={MIN_CLIPS}) — retry avec pool Twitch élargi (50 clips)")
        twitch_extended = fetch_twitch_clips(game_slug, game_name, limit=50)
        # Merge : clips déjà retenus + nouveaux candidats Twitch non encore vus
        seen_ids = {c["id"] for c in all_candidates}
        new_twitch = [c for c in twitch_extended if c["id"] not in seen_ids]
        retry_pool = all_candidates + new_twitch
        print(f"\n  Retry pool élargi : {len(retry_pool)} candidats ({len(new_twitch)} nouveaux Twitch)")
        try:
            clips = select_clips_ai(retry_pool[:60], CLIPS_PER_VIDEO, game_name=game_name, game_slug=game_slug)
        except NoClipsSelectedError:
            clips = []
        if len(clips) < MIN_CLIPS:
            logging.warning(f"Toujours seulement {len(clips)} clips après retry — on continue avec ce qu'on a")

    print(f"\n  {len(clips)} clips retenus après sélection IA combinée :\n")
    for i, c in enumerate(clips, 1):
        source = c.get("_source", "medal")
        print(f"{i:2}. [{source:<6}] [{c['_game']:<25}] {int(c['duration']):>3}s | {c['view_count']:>7} views | {c['title']}")

    downloaded = download_clips(clips)
    mark_clips_used(downloaded)

    # ── 2. Incrémenter l'épisode une seule fois ────────────────────────────────
    episode = bump_episode(game_name)

    # ── 3. Compilation longue YouTube ─────────────────────────────────────────
    compilation_path = build_long_video(downloaded)

    # ── 4. TikToks (top 2 clips, bruts verticaux, sans overlay) ───────────────
    shorts_results = build_tiktoks_per_game(downloaded)

    # ── 5. Miniature ──────────────────────────────────────────────────────────
    thumbnail_path = generate_thumbnail(downloaded, game_name, episode=episode)

    # ── 6. Titres & descriptions (un seul appel Haiku) ────────────────────────
    yt_title    = get_youtube_title(game_name, episode)
    short_clips = [clip for clip, _ in shorts_results]
    chapters, short_descs, short_titles = generate_ai_content(downloaded, short_clips)
    yt_desc     = chapters + "\n\n" + get_youtube_description(game_name, episode)

    date_str  = datetime.now().strftime("%Y-%m-%d")
    date_day2 = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    shorts_content = []
    for idx, ((clip, path), desc, title) in enumerate(zip(shorts_results, short_descs, short_titles), 1):
        shorts_content.append({
            "day":          idx,
            "publish_date": date_str if idx == 1 else date_day2,
            "clip_title":   title or clip.get("title", ""),
            "broadcaster":  clip.get("broadcaster_name", ""),
            "video_path":   path,
            "description":  desc,
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

    print(f"\n📄  Contenu sauvegardé : {content_path}")

    if args.no_upload:
        print(f"\n⏸️  {game_name} — traitement terminé, upload en attente (--no-upload)\n")
        raise SystemExit(0)

else:
    # Retrouve le content JSON existant
    import glob
    matches = sorted(glob.glob(f"output/content_*_{game_slug}.json"))
    if not matches:
        raise FileNotFoundError(f"Aucun content JSON trouvé pour {game_slug}")
    content_path = matches[-1]
    print(f"\n📄  Upload depuis : {content_path}")

# ── 8. Upload YouTube ─────────────────────────────────────────────────────
try:
    video_id  = upload_from_content(content_path, privacy="public")
    short_ids = upload_shorts_from_content(content_path)
except QuotaExceededError as e:
    logging.warning(str(e))
    print(f"\n⚠️  Quota YouTube dépassé pour {game_name} — relance avec --upload-only demain.\n")
    raise SystemExit(0)

# ── 9. Enregistrement analytics ───────────────────────────────────────────
with open(content_path, encoding="utf-8") as f:
    record_run(json.load(f), game_slug)
refresh_channel_stats(game_slug)
generate_dashboard()

# ── 10. Résumé ─────────────────────────────────────────────────────────────
short_urls = [f"https://youtu.be/{vid}" for vid in short_ids]
print(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅  {game_name} #{episode if not args.upload_only else '?'} — pipeline terminé
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📺  YouTube   : https://youtu.be/{video_id}
▶️  Short J1  : {short_urls[0] if len(short_urls) > 0 else 'N/A'}
▶️  Short J2  : {short_urls[1] if len(short_urls) > 1 else 'N/A'}
📄  Contenu   : {content_path}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━""")
