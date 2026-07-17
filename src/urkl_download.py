#!/usr/bin/env python3
"""
Télécharge les clips URKL depuis YouTube et les stocke dans R2 (persistant).
Usage: python3 src/urkl_download.py [max_clips]
  max_clips: 0 = tous, sinon top N par dB (défaut 5 pour tests)
"""
import json, subprocess, os, sys, time, random, tempfile

sys.path.insert(0, "/workspaces/FFMPEG/src")
import urkl_r2 as r2lib

MOMENTS_JSON = "/workspaces/FFMPEG/data/urkl_moments.json"
COOKIES      = "/workspaces/FFMPEG/data/yt_cookies.txt"
URL          = "https://www.youtube.com/watch?v=vpyO73jyx1g"

MAX_CLIPS = int(sys.argv[1]) if len(sys.argv) > 1 else 5

with open(MOMENTS_JSON) as f:
    all_moments = json.load(f)

if MAX_CLIPS and MAX_CLIPS < len(all_moments):
    moments_selected = sorted(all_moments, key=lambda x: x["db"], reverse=True)[:MAX_CLIPS]
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

r2 = r2lib.client()
total = len(moments_selected)
failed = []

for i, m in enumerate(moments_selected):
    orig_idx = all_starts.index(m["start"]) + 1
    fname    = f"clip_{orig_idx:02d}.mp4"
    start_ts = sec_to_hms(m["start"])
    end_ts   = sec_to_hms(m["end"])

    if r2lib.clip_exists(fname, r2):
        print(f"[{i+1:2d}/{total}] {fname} {start_ts}→{end_ts}  déjà dans R2 ✓")
        continue

    print(f"[{i+1:2d}/{total}] {fname} {start_ts}→{end_ts}  ({m['db']:+.0f} dB) ...", flush=True)

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd = [
            "yt-dlp",
            "--cookies", COOKIES,
            "--no-update",
            "--js-runtimes", "node",
            "--remote-components", "ejs:github",
            "--download-sections", f"*{start_ts}-{end_ts}",
            "--force-keyframes-at-cuts",
            "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]",
            "--merge-output-format", "mp4",
            "--no-part",
            "-o", tmp_path,
            URL
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        ok = os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 200_000

        if not ok:
            cmd[cmd.index("-f") + 1] = "best[height<=720]/bestvideo[height<=720]+bestaudio/best"
            subprocess.run(cmd, capture_output=True, text=True)
            ok = os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 200_000

        if ok:
            size_kb = os.path.getsize(tmp_path) // 1024
            print(f"  téléchargé ({size_kb}KB) → upload R2...", end=" ", flush=True)
            r2lib.upload_clip(tmp_path, fname, r2)
            print("OK ✓")
            sleep = random.uniform(4, 9)
            time.sleep(sleep)
        else:
            print(f"  ERREUR download")
            if result.stderr:
                print(f"  {result.stderr.strip()[-200:]}")
            failed.append(orig_idx)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

print(f"\n{'='*50}")
clips_in_r2 = r2lib.list_clips(r2)
print(f"Clips dans R2 : {len(clips_in_r2)}")
if failed:
    print(f"Clips échoués : {failed}")
print(f"\nTéléchargement terminé. Lance le serveur :")
print(f"  python3 /workspaces/FFMPEG/src/urkl_validate.py 8888")
