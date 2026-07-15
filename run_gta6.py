"""
Pipeline GTA 6 — théories & news (avant lancement du jeu).

Génère par défaut 2 fichiers dans output/gta6/ (vidéo longue passée par défaut — utiliser --with-long pour la générer) :
  {date}_short_en.mp4  → YouTube Short 9:16, voix EN, sous-titres brûlés
  {date}_tiktok_fr.mp4 → TikTok 9:16, voix FR, sans sous-titres (à poster manuellement)
  {date}_long_en.mp4   → YouTube long 16:9, voix EN, sous-titres brûlés (avec --with-long)

Usage :
  python run_gta6.py
  python run_gta6.py --topic "GTA 6 map size comparison"
  python run_gta6.py --with-long   (génère aussi la vidéo longue, plus lent)
"""
import argparse
import json
import logging
import os
import tempfile
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

parser = argparse.ArgumentParser()
parser.add_argument("--topic",       default="", help="Angle/sujet à privilégier (optionnel)")
parser.add_argument("--with-long",   action="store_true", help="Générer aussi la vidéo longue")
parser.add_argument("--tiktok-only", action="store_true", help="Générer uniquement le TikTok (pas de short ni d'upload YT ni de miniature)")
parser.add_argument("--mock",        action="store_true", help="Utiliser le cache local (sans appel réseau)")
parser.add_argument("--reddit",      action="store_true", help="Forcer le scraping Reddit (bloqué en datacenter)")
args = parser.parse_args()
args.no_long = not args.with_long

date_str = datetime.now().strftime("%Y-%m-%d")
os.makedirs("output/gta6", exist_ok=True)


def _make_player_html(video_url: str, title: str) -> str:
    """Page HTML légère pour sauvegarder le TikTok dans Photos sur iPhone."""
    import json as _json
    v = _json.dumps(video_url)
    t = _json.dumps(title)
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>{title}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%;background:#0a0a0a;color:#fff;font-family:-apple-system,BlinkMacSystemFont,sans-serif}}
body{{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:22px;padding:24px;min-height:100vh}}
video{{width:100%;max-width:360px;max-height:62vh;border-radius:14px;background:#111}}
.title{{font-size:14px;font-weight:600;text-align:center;opacity:.7;max-width:320px}}
.btn{{width:100%;max-width:320px;background:#ff2d55;color:#fff;border:none;border-radius:14px;padding:18px;font-size:17px;font-weight:700;cursor:pointer}}
.btn:disabled{{opacity:.5}}
.hint{{font-size:12px;color:#666;text-align:center;max-width:280px;line-height:1.5}}
</style>
</head>
<body>
<video id="v" playsinline controls preload="auto"></video>
<p class="title" id="ttl"></p>
<button class="btn" id="btn" disabled>Chargement…</button>
<p class="hint" id="hint">Si ça ne marche pas : appuie longuement sur la vidéo → "Enregistrer dans Photos"</p>
<script>
const videoUrl={v},videoTitle={t};
const btn=document.getElementById('btn'),hint=document.getElementById('hint');
document.getElementById('v').src=videoUrl;
document.getElementById('ttl').textContent=videoTitle;
let readyBlob=null;
fetch(videoUrl).then(r=>r.blob()).then(b=>{{
  readyBlob=b;
  btn.disabled=false;btn.textContent='Enregistrer dans Photos';
}}).catch(()=>{{
  btn.disabled=false;btn.textContent='Enregistrer dans Photos';
  hint.textContent='Appuie longuement sur la vidéo → "Enregistrer dans Photos"';
}});
function saveVideo(){{
  if(!readyBlob){{hint.textContent='Encore en chargement…';return;}}
  const file=new File([readyBlob],'gta6_tiktok.mp4',{{type:'video/mp4'}});
  if(navigator.share&&navigator.canShare&&navigator.canShare({{files:[file]}})){{
    navigator.share({{files:[file],title:videoTitle}}).catch(()=>{{
      hint.textContent='Appuie longuement sur la vidéo → "Enregistrer dans Photos"';
    }});
  }}else{{
    const a=document.createElement('a');
    a.href=URL.createObjectURL(readyBlob);
    a.download='gta6_tiktok.mp4';
    document.body.appendChild(a);a.click();
    setTimeout(()=>{{URL.revokeObjectURL(a.href);document.body.removeChild(a)}},1000);
  }}
}}
btn.onclick=saveVideo;
</script>
</body>
</html>"""
# ── 1. Scraping Reddit ────────────────────────────────────────────────────────
from src.fetch_gta6_content import fetch_reddit_posts, fetch_news_posts, mark_articles_used

if args.mock:
    log.info("Mode mock — chargement du cache local...")
    posts = fetch_reddit_posts(limit=15, mock=True)
elif args.reddit:
    log.info("Scraping Reddit (r/GTA6, r/GTA, r/GTASeries)...")
    posts = fetch_reddit_posts(limit=15, mock=False)
else:
    log.info("Collecte des flux RSS gaming (GameSpot, IGN, RPS, PCGamer…)...")
    posts = fetch_news_posts(limit=15)

if not posts:
    log.error("Aucun post Reddit trouvé — vérifier la connexion ou les subreddits")
    raise SystemExit(1)

log.info(f"  {len(posts)} posts collectés")
for p in posts[:5]:
    log.info(f"    [{p['score']:>6}] {p['title'][:70]}")

# ── 2. Génération des scripts IA ──────────────────────────────────────────────
from src.generate_gta6_script import generate_scripts, load_topic_history, save_topic, load_trailer_catalog

log.info("\nGénération des scripts (Claude Haiku)...")
history = load_topic_history()
if history:
    log.info(f"  {len(history)} sujets déjà couverts en mémoire")
catalog = load_trailer_catalog()
if catalog:
    log.info(f"  Catalogue trailer : {len(catalog)} moments visuels disponibles")
scripts = generate_scripts(posts, topic=args.topic, history=history, catalog=catalog)

# Enregistrer le sujet dans l'historique + marquer les articles comme utilisés
save_topic(scripts, date_str, posts=posts)
if not args.mock:
    mark_articles_used(posts)
log.info(f"  Sujet sauvegardé : {scripts.get('thumbnail_title', '')}")

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

    shots = scripts.get("shots") or []
    if shots:
        log.info(f"  Shot list IA : {len(shots)} plans visuels")

    if not args.tiktok_only:
        log.info("  TTS short EN...")
        synthesize_en_short(scripts["short_en"], audio_short, ass_short)

        # Image de fond : post sélectionné par l'IA, uniquement si elle juge l'image pertinente
        image_short = None
        post_idx = int(scripts.get("short_post_index", 0))
        if not scripts.get("use_post_image", True):
            log.info("  Image fond ignorée (IA : non pertinente pour la narration)")
        elif 0 <= post_idx < len(posts):
            post = posts[post_idx]

            local_img = post.get("local_image", "")
            if local_img and os.path.exists(local_img):
                image_short = local_img
                log.info(f"  Image fond (locale) : {post['title'][:60]}")
            elif post.get("image_url"):
                import urllib.request
                img_url  = post["image_url"]
                img_ext  = os.path.splitext(img_url.split("?")[0])[1] or ".jpg"
                if img_ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                    img_ext = ".jpg"
                img_path = os.path.join(tmp, f"post_image{img_ext}")
                try:
                    req = urllib.request.Request(img_url, headers={
                        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                        "Referer": post.get("url", img_url),
                    })
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        with open(img_path, "wb") as f:
                            f.write(resp.read())
                    image_short = img_path
                    log.info(f"  Image fond (remote) : {post['title'][:60]}")
                except Exception as e:
                    log.warning(f"  Image téléchargement échoué ({img_url}): {e}")

        if shots:
            log.info("  Montage short EN...")
            paths["short"] = build_short_en(audio_short, ass_short, date_str,
                                            image_path=image_short, shots=shots)

    log.info("  TTS TikTok FR...")
    synthesize_fr(scripts["tiktok_fr"], audio_tiktok)
    log.info("  Montage TikTok FR...")
    paths["tiktok"] = build_tiktok_fr(audio_tiktok, date_str,
                                       hook_text=scripts.get("tiktok_hook", ""),
                                       shots=shots)

# ── 4. Miniature (uniquement si on génère le short YouTube) ───────────────────
if not args.tiktok_only:
    from src.generate_thumbnail_gta6 import generate_thumbnail_gta6
    log.info("\nGénération de la miniature...")
    thumb_path = generate_thumbnail_gta6(scripts["thumbnail_title"], date_str)
    paths["thumbnail"] = thumb_path

# ── 4bis. Upload YouTube Short ──────────────────────────────────────────────
if not args.tiktok_only and "short" in paths:
    from src.upload_youtube import upload_video, QuotaExceededError
    short_description = (
        f"{scripts.get('thumbnail_title', '')}\n\n"
        "GTA 6 sort le 19 novembre 2026.\n\n"
        "#GTA6 #GTAVI #Shorts #RockstarGames #Gaming"
    )
    try:
        short_video_id = upload_video(
            video_path=paths["short"],
            title=f"{scripts.get('thumbnail_title', '')} #Shorts"[:100],
            description=short_description,
            thumbnail_path=paths.get("thumbnail"),
            tags=["gta6", "gtavi", "rockstargames", "shorts"],
            privacy="public",
            game_slug="gta",
        )
        paths["short_url"] = f"https://youtu.be/{short_video_id}"
        log.info(f"  Short uploadé → {paths['short_url']}")
    except QuotaExceededError as e:
        log.warning(f"  Quota YouTube dépassé — short non uploadé : {e}")
    except FileNotFoundError as e:
        log.warning(f"  Token YouTube GTA 6 manquant — short non uploadé (configurer YOUTUBE_TOKEN_GTA) : {e}")
    except Exception as e:
        log.warning(f"  Upload YouTube échoué — short non uploadé : {e}")

# ── 4ter. Upload TikTok vers R2 + page player pour iPhone ─────────────────────
from src.r2_manager import delete_prefix, upload_public_file

tiktok_caption = scripts.get("tiktok_caption", "")
tiktok_filename = os.path.basename(paths["tiktok"])
delete_prefix("gta6-tiktok/")

# Vidéo en inline (pas Content-Disposition: attachment) pour que le player HTML puisse la fetch
tiktok_url = upload_public_file(paths["tiktok"], f"gta6-tiktok/{tiktok_filename}", download=False)
if tiktok_url:
    log.info(f"  TikTok uploadé → {tiktok_url}")

# Page HTML player : bouton "Enregistrer dans Photos" qui fonctionne sur iPhone
player_url = None
if tiktok_url:
    html_content = _make_player_html(tiktok_url, scripts.get("thumbnail_title", "TikTok GTA 6"))
    html_path = os.path.join("output/gta6", f"{date_str}_player.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    player_url = upload_public_file(html_path, "gta6-tiktok/player.html", content_type="text/html; charset=utf-8")
    if player_url:
        log.info(f"  Player page → {player_url}")

meta_path = os.path.join("output/gta6", f"{date_str}_tiktok_meta.json")
with open(meta_path, "w", encoding="utf-8") as f:
    json.dump({
        "tiktok_url":  tiktok_url  or "",
        "player_url":  player_url  or "",
        "tiktok_caption": tiktok_caption,
    }, f, ensure_ascii=False, indent=2)
paths["tiktok_meta"] = meta_path

# ── 5. Résumé ─────────────────────────────────────────────────────────────────
lines = [
    "",
    "━" * 50,
    "✅  GTA 6 pipeline terminé",
    "━" * 50,
]
if "long" in paths:
    lines.append(f"📺  YouTube long  → {paths['long']}")
if "short_url" in paths:
    lines.append(f"▶️   YouTube Short → {paths['short_url']}")
elif "short" in paths:
    lines.append(f"▶️   YouTube Short → {paths['short']}  (upload échoué, fichier local)")
lines.append(f"🎵  TikTok FR     → {paths['tiktok']}  (poster manuellement)")
if "thumbnail" in paths:
    lines.append(f"🖼️   Miniature     → {paths['thumbnail']}")
lines.append("━" * 50)
log.info("\n".join(lines))
