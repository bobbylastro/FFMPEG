#!/usr/bin/env python3
"""
Filtre les moments détectés pour ne garder que ceux dans les rounds de combat.
Nettoie R2 et relance le download sur les moments filtrés.

Usage: python3 src/urkl_filter_rounds.py <rounds_spec>
  rounds_spec: liste de plages "MM:SS-MM:SS,MM:SS-MM:SS,..."
               ou "HH:MM:SS-HH:MM:SS,..."

Exemple (URKL 2026-07-17):
  python3 src/urkl_filter_rounds.py "48:00-56:00,1:08:00-1:16:00,1:22:00-1:30:00,1:37:00-1:45:00,1:49:00-1:57:00,1:58:00-2:08:00"
"""
import json, sys, os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "src"))
import urkl_r2 as r2lib

MOMENTS_JSON = os.path.join(BASE_DIR, "data/urkl_moments.json")


def parse_ts(s: str) -> int:
    parts = s.strip().split(":")
    parts = [int(p) for p in parts]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def fmt(s):
    s = int(s)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"


if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

rounds_raw = sys.argv[1].split(",")
windows = []
for r in rounds_raw:
    start_str, end_str = r.strip().split("-")
    windows.append((parse_ts(start_str), parse_ts(end_str)))

print(f"Plages de rounds ({len(windows)}) :")
for lo, hi in windows:
    print(f"  {fmt(lo)} → {fmt(hi)}")

with open(MOMENTS_JSON) as f:
    moments = json.load(f)

filtered = [m for m in moments if any(lo <= m["start"] <= hi for lo, hi in windows)]
print(f"\nMoments : {len(moments)} → {len(filtered)} dans les rounds")
for m in filtered:
    print(f"  {fmt(m['start'])} → {fmt(m['end'])}  ({m['db']:+.0f} dB)")

with open(MOMENTS_JSON, "w") as f:
    json.dump(filtered, f, indent=2)
print(f"\nSauvegardé : {MOMENTS_JSON}")

# Nettoyer les clips R2 qui ne sont plus dans la liste
r2 = r2lib.client()
clips_in_r2 = r2lib.list_clips(r2)
if clips_in_r2:
    print(f"\nNettoyage R2 ({len(clips_in_r2)} clips)...")
    for c in clips_in_r2:
        r2lib.delete_clip(c, r2)
    r2lib.save_state({}, r2)
    print("R2 nettoyé.")

print(f"\nRelance le download :")
print(f"  python3 {os.path.join(BASE_DIR, 'src/urkl_download.py')} 0")
