#!/usr/bin/env python3
"""
Télécharge les clips d'une ligue de combat de robots (URKL, REK, ...) et les stocke dans
R2 (persistant).
Usage: python3 src/urkl_download.py [max_clips] [video_url] [league]
  max_clips: 0 = tous, sinon top N par dB (défaut 5 pour tests)
  video_url: URL de la vidéo source, YouTube ou X/Twitter broadcast (défaut : dernière connue)
  league: urkl|rek|divers (défaut: urkl)

Télécharge la vidéo source EN UNE SEULE FOIS (comme urkl_transcribe_moments.py pour
l'audio), puis découpe tous les clips localement avec ffmpeg. Avant, chaque clip déclenchait
son propre appel yt-dlp --download-sections — sur une vidéo avec beaucoup de clips (20+),
ça fait autant de requêtes d'extraction d'infos rapprochées à YouTube depuis la même
source, un pattern qui ressemble à du scraping automatisé et se fait bloquer bien plus
sévèrement qu'un simple rate-limit, quelle que soit l'IP. Un seul téléchargement complet
élimine ce risque pour la partie découpage, qui devient un traitement 100% local.
"""
import json, subprocess, os, sys, time, random, tempfile, glob, hashlib

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "src"))
import urkl_r2 as r2lib

COOKIES      = os.path.join(BASE_DIR, "data/yt_cookies.txt")
DEFAULT_URL  = "https://www.youtube.com/watch?v=vpyO73jyx1g"

MAX_CLIPS = int(sys.argv[1]) if len(sys.argv) > 1 else 5
URL       = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_URL
LEAGUE    = sys.argv[3] if len(sys.argv) > 3 else "urkl"
MOMENTS_JSON = os.path.join(BASE_DIR, f"data/{LEAGUE}_moments.json")

with open(MOMENTS_JSON, encoding="utf-8") as f:
    all_moments = json.load(f)

if MAX_CLIPS and MAX_CLIPS < len(all_moments):
    moments_selected = sorted(all_moments, key=lambda x: x.get("db", 0), reverse=True)[:MAX_CLIPS]
    moments_selected.sort(key=lambda x: x["start"])
    print(f"=== Mode test : {MAX_CLIPS} meilleurs clips sur {len(all_moments)} ===\n")
else:
    moments_selected = all_moments
    print(f"=== Téléchargement de {len(all_moments)} clips URKL → R2 ===\n")

all_starts = [m["start"] for m in all_moments]


def sec_to_hms(s):
    s = int(s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


def _cache_path_for(url: str) -> str:
    """Base de cache par URL (sans extension) — même logique que
    urkl_transcribe_moments.py, évite de réutiliser la vidéo d'une autre source."""
    h = hashlib.md5(url.encode()).hexdigest()[:12]
    return f"/tmp/urkl_full_video_cache_{h}"


def download_full_video(url: str) -> str:
    """Télécharge la vidéo (vidéo+audio) complète UNE SEULE FOIS. Fallback vers un
    format muxé générique si bestvideo+bestaudio n'est pas disponible pour cette source."""
    cache_base = _cache_path_for(url)
    cached = glob.glob(cache_base + ".*")
    if cached and os.path.getsize(cached[0]) > 1_000_000:
        print(f"Vidéo complète déjà en cache ({os.path.getsize(cached[0])/1024/1024:.0f} MB), skip download")
        return cached[0]

    print("Téléchargement de la vidéo complète (une seule fois)...", flush=True)
    cmd = [
        "yt-dlp", "--cookies", COOKIES, "--no-update",
        "--js-runtimes", "node", "--remote-components", "ejs:github",
        # Pas de plafond de résolution : on prend la meilleure qualité source disponible
        # (jusqu'à 4K) — le ré-encodage se fait sans downscale, donc tout ce qu'on jette
        # ici est perdu définitivement pour la compilation finale.
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
        "--merge-output-format", "mp4",
        "-o", cache_base + ".%(ext)s", "--no-part", url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    downloaded = glob.glob(cache_base + ".*")
    if not downloaded:
        cmd[cmd.index("-f") + 1] = "best/bestvideo+bestaudio"
        result = subprocess.run(cmd, capture_output=True, text=True)
        downloaded = glob.glob(cache_base + ".*")
    if not downloaded:
        raise RuntimeError(f"Download vidéo complète échoué: {result.stderr[-500:]}")
    path = downloaded[0]
    print(f"  Vidéo complète téléchargée ({os.path.getsize(path)/1024/1024:.0f} MB)")
    return path


def cut_clip(full_video: str, start: float, duration: float, out_path: str) -> bool:
    """Découpe + ré-encode un clip directement depuis la vidéo complète locale —
    aucune requête réseau. -ss avant -i (seek rapide) reste précis au ré-encodage (ffmpeg
    décode depuis la keyframe précédente jusqu'au point exact avant d'encoder).
    CRF bas + preset lent : qualité correcte malgré la 2e génération de compression."""
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(start), "-i", full_video, "-t", str(duration),
         "-c:v", "libx264", "-preset", "slow", "-crf", "16",
         "-c:a", "aac", "-b:a", "192k",
         out_path, "-hide_banner", "-loglevel", "error"],
        capture_output=True, text=True,
    )
    return os.path.exists(out_path) and os.path.getsize(out_path) > 100_000


full_video = download_full_video(URL)

r2 = r2lib.client()
total = len(moments_selected)
failed = []

for i, m in enumerate(moments_selected):
    orig_idx = all_starts.index(m["start"]) + 1
    fname    = f"clip_{orig_idx:02d}.mp4"
    duration = m["end"] - m["start"]
    start_ts = sec_to_hms(m["start"])
    end_ts   = sec_to_hms(m["end"])

    if r2lib.clip_exists(fname, r2, LEAGUE):
        print(f"[{i+1:2d}/{total}] {fname} {start_ts}→{end_ts}  déjà dans R2 ✓")
        continue

    label = f"{m['db']:+.0f} dB" if "db" in m else m.get("reason", "")[:60]
    print(f"[{i+1:2d}/{total}] {fname} {start_ts}→{end_ts}  ({label}) ...", flush=True)

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        ok = cut_clip(full_video, m["start"], duration, tmp_path)
        if ok:
            size_kb = os.path.getsize(tmp_path) // 1024
            print(f"  découpé ({size_kb}KB) → upload R2...", end=" ", flush=True)
            r2lib.upload_clip(tmp_path, fname, r2, LEAGUE)
            print("OK ✓")
        else:
            print("  ERREUR découpage ffmpeg")
            failed.append(orig_idx)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

print(f"\n{'='*50}")
clips_in_r2 = r2lib.list_clips(r2, LEAGUE)
print(f"Clips dans R2 : {len(clips_in_r2)}")
if failed:
    print(f"Clips échoués : {failed}")
print(f"\nTéléchargement terminé. Lance le serveur :")
print(f"  python3 {os.path.join(BASE_DIR, 'src/urkl_validate.py')} 8888 {LEAGUE}")
