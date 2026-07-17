#!/usr/bin/env python3
"""
Détecte les moments forts URKL par analyse audio RMS et sauvegarde dans R2 + local.
Usage: python3 src/urkl_detect.py [min_db] [min_gap] [pre] [post] [start_frac]
"""
import sys, json, subprocess, struct, math, os

COOKIES      = "/workspaces/FFMPEG/data/yt_cookies.txt"
MOMENTS_JSON = "/workspaces/FFMPEG/data/urkl_moments.json"
URL          = "https://www.youtube.com/watch?v=vpyO73jyx1g"

MIN_DB     = float(sys.argv[1]) if len(sys.argv) > 1 else -20.0
MIN_GAP    = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
PRE        = int(sys.argv[3])   if len(sys.argv) > 3 else 10
POST       = int(sys.argv[4])   if len(sys.argv) > 4 else 5
START_FRAC = float(sys.argv[5]) if len(sys.argv) > 5 else 0.125

print(f"Paramètres : MIN_DB={MIN_DB} dB, MIN_GAP={MIN_GAP}s, PRE={PRE}s, POST={POST}s, START_FRAC={START_FRAC}")

dur_cmd = ["yt-dlp", "--cookies", COOKIES, "--js-runtimes", "node",
           "--remote-components", "ejs:github", "--print", "duration", URL]
total_dur = float(subprocess.check_output(dur_cmd, text=True).strip())
start_offset = total_dur * START_FRAC
print(f"Durée totale : {total_dur:.0f}s ({total_dur/3600:.2f}h) — skip avant {start_offset:.0f}s")

print("Analyse audio en cours (yt-dlp | ffmpeg)...")
ytdlp_cmd = ["yt-dlp", "--cookies", COOKIES, "--js-runtimes", "node",
              "--remote-components", "ejs:github",
              "-f", "bestaudio", "-o", "-", "--quiet", URL]
ffmpeg_cmd = ["ffmpeg", "-i", "pipe:0",
              "-ar", "8000", "-ac", "1", "-f", "s16le", "-",
              "-hide_banner", "-loglevel", "error"]

ytdlp_proc = subprocess.Popen(ytdlp_cmd, stdout=subprocess.PIPE)
ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=ytdlp_proc.stdout, stdout=subprocess.PIPE)
ytdlp_proc.stdout.close()

raw = ffmpeg_proc.stdout.read()
ffmpeg_proc.wait(); ytdlp_proc.wait()

SR = 8000
samples = struct.unpack(f"<{len(raw)//2}h", raw)
print(f"Samples : {len(samples):,} ({len(samples)/SR:.0f}s)")

def rms_db(chunk):
    if not chunk: return -99
    sq = sum(s*s for s in chunk) / len(chunk)
    return 20 * math.log10(math.sqrt(sq) / 32768) if sq > 0 else -99

rms = [rms_db(samples[i*SR:(i+1)*SR]) for i in range(len(samples)//SR)]
smoothed = [sum(rms[max(0,i-1):i+2]) / len(rms[max(0,i-1):i+2]) for i in range(len(rms))]

moments = []
last_peak = -MIN_GAP - 1
for i, db in enumerate(smoothed):
    if db < MIN_DB or i < start_offset or i - last_peak < MIN_GAP:
        continue
    moments.append({"peak": i, "start": float(max(0, i - PRE)),
                    "end": float(min(len(smoothed)-1, i + POST)), "db": round(db, 1)})
    last_peak = i

def fmt(s):
    s=int(s); return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"

print(f"Moments détectés : {len(moments)}")
for j, m in enumerate(moments):
    print(f"  [{j+1:2d}] {fmt(m['start'])} → {fmt(m['end'])}  ({m['db']:+.0f} dB)")

os.makedirs(os.path.dirname(MOMENTS_JSON), exist_ok=True)
with open(MOMENTS_JSON, "w") as f:
    json.dump(moments, f, indent=2)
print(f"\nSauvegardé : {MOMENTS_JSON}")
print(f"Lance le download : python3 /workspaces/FFMPEG/src/urkl_download.py 5")
