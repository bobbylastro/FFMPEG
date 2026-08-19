#!/usr/bin/env python3
"""
Télécharge les clips d'une ligue de combat de robots (URKL, REK, ...) et les stocke dans
R2 (persistant).
Usage: python3 src/urkl_download.py [max_clips] [video_url] [league]
  max_clips: 0 = tous, sinon top N par dB (défaut 5 pour tests)
  video_url: URL de la vidéo source, YouTube ou X/Twitter broadcast (défaut : dernière connue)
  league: urkl|rek (défaut: urkl)
"""
import json, subprocess, os, sys, time, random, tempfile

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

PAD_END = 2.0  # marge de sécurité téléchargée en plus à la fin, retirée par un recadrage
               # local précis — --force-keyframes-at-cuts de yt-dlp tronque parfois la
               # toute fin de la piste audio sur des sources HLS (ex. broadcasts X)

def sec_to_hms(s):
    s = int(s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"

r2 = r2lib.client()
total = len(moments_selected)
failed = []

for i, m in enumerate(moments_selected):
    orig_idx  = all_starts.index(m["start"]) + 1
    fname     = f"clip_{orig_idx:02d}.mp4"
    duration  = m["end"] - m["start"]
    start_ts  = sec_to_hms(m["start"])
    end_ts    = sec_to_hms(m["end"])
    end_ts_dl = sec_to_hms(m["end"] + PAD_END)  # marge côté téléchargement

    if r2lib.clip_exists(fname, r2, LEAGUE):
        print(f"[{i+1:2d}/{total}] {fname} {start_ts}→{end_ts}  déjà dans R2 ✓")
        continue

    label = f"{m['db']:+.0f} dB" if "db" in m else m.get("reason", "")[:60]
    print(f"[{i+1:2d}/{total}] {fname} {start_ts}→{end_ts}  ({label}) ...", flush=True)

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path_raw = tmp.name
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd = [
            "yt-dlp",
            "--cookies", COOKIES,
            "--no-update",
            "--js-runtimes", "node",
            "--remote-components", "ejs:github",
            "--download-sections", f"*{start_ts}-{end_ts_dl}",
            "--force-keyframes-at-cuts",
            "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
            "--merge-output-format", "mp4",
            "--no-part",
            "-o", tmp_path_raw,
            URL
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        ok = os.path.exists(tmp_path_raw) and os.path.getsize(tmp_path_raw) > 200_000

        if not ok:
            cmd[cmd.index("-f") + 1] = "best[height<=1080]/bestvideo[height<=1080]+bestaudio/best"
            subprocess.run(cmd, capture_output=True, text=True)
            ok = os.path.exists(tmp_path_raw) and os.path.getsize(tmp_path_raw) > 200_000

        if ok:
            # Recadrage local à la durée exacte : la marge téléchargée en plus à la fin
            # absorbe la troncature audio de yt-dlp, ce recoupage ne touche plus le bord
            # problématique (il est maintenant bien après la fin réelle du clip).
            # Ré-encodage (pas -c copy) : couper à une durée arbitraire tombe rarement pile
            # sur une keyframe, et une copie de flux sur un point hors-GOP produit un arrêt
            # sur image en fin de clip (frames de référence manquantes pour le décodeur).
            trim = subprocess.run(
                ["ffmpeg", "-y", "-i", tmp_path_raw, "-t", str(duration),
                 "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                 "-c:a", "aac", "-b:a", "128k",
                 tmp_path, "-hide_banner", "-loglevel", "error"],
                capture_output=True, text=True,
            )
            ok = os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 100_000

        if ok:
            size_kb = os.path.getsize(tmp_path) // 1024
            print(f"  téléchargé ({size_kb}KB) → upload R2...", end=" ", flush=True)
            r2lib.upload_clip(tmp_path, fname, r2, LEAGUE)
            print("OK ✓")
            sleep = random.uniform(4, 9)
            time.sleep(sleep)
        else:
            print(f"  ERREUR download")
            if result.stderr:
                print(f"  {result.stderr.strip()[-200:]}")
            failed.append(orig_idx)
    finally:
        for p in (tmp_path_raw, tmp_path):
            if os.path.exists(p):
                os.unlink(p)

print(f"\n{'='*50}")
clips_in_r2 = r2lib.list_clips(r2, LEAGUE)
print(f"Clips dans R2 : {len(clips_in_r2)}")
if failed:
    print(f"Clips échoués : {failed}")
print(f"\nTéléchargement terminé. Lance le serveur :")
print(f"  python3 {os.path.join(BASE_DIR, 'src/urkl_validate.py')} 8888 {LEAGUE}")
