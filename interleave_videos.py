#!/usr/bin/env python3
"""
Interleave deux vidéos : alterne des extraits (~5-7s par défaut) entre les deux
sources. Entre deux extraits consécutifs pris dans la MÊME source, on avance en plus
d'un "gap" (~3-4s par défaut) non utilisé dans le montage — pour éviter que le 2e
extrait d'une source ne soit perçu comme la simple suite du 1er.

Usage:
  python interleave_videos.py <video_a> <video_b> [-o output.mp4]
    [--extract-min 5] [--extract-max 7] [--gap-min 3] [--gap-max 4]
    [--start-a 0] [--start-b 0] [--width 1920] [--height 1080] [--fps 30]

Exemple :
  python interleave_videos.py clipA.mp4 clipB.mp4 -o interleaved.mp4
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile


def probe_duration(path: str) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", path,
    ])
    return float(json.loads(out)["format"]["duration"])


def extract_segment(src: str, start: float, dur: float, out_path: str,
                     width: int, height: int, fps: int):
    """Découpe + normalise un extrait (résolution/fps/codec communs, requis pour un
    concat propre entre deux sources potentiellement hétérogènes)."""
    subprocess.run([
        "ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", src, "-t", f"{dur:.2f}",
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-hide_banner", "-loglevel", "error",
        out_path,
    ], check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video_a")
    p.add_argument("video_b")
    p.add_argument("-o", "--out", default="interleaved.mp4")
    p.add_argument("--extract-min", type=float, default=5, help="Durée mini d'un extrait (s)")
    p.add_argument("--extract-max", type=float, default=7, help="Durée maxi d'un extrait (s)")
    p.add_argument("--gap-min", type=float, default=3, help="Saut mini (non utilisé) entre 2 extraits d'une même source (s)")
    p.add_argument("--gap-max", type=float, default=4, help="Saut maxi (non utilisé) entre 2 extraits d'une même source (s)")
    p.add_argument("--start-a", type=float, default=0, help="Point de départ dans la vidéo A (s)")
    p.add_argument("--start-b", type=float, default=0, help="Point de départ dans la vidéo B (s)")
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--seed", type=int, default=None, help="Graine aléatoire (pour reproduire un montage)")
    args = p.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    dur_a = probe_duration(args.video_a)
    dur_b = probe_duration(args.video_b)
    print(f"{args.video_a}: {dur_a:.1f}s   {args.video_b}: {dur_b:.1f}s")

    pos_a, pos_b = args.start_a, args.start_b
    segments = []
    tmp_dir = tempfile.mkdtemp(prefix="interleave_")
    i = 0
    try:
        while True:
            ext_a = random.uniform(args.extract_min, args.extract_max)
            if pos_a + ext_a > dur_a:
                print(f"[{i}] Fin de la vidéo A atteinte ({pos_a:.1f}s).")
                break
            ext_b = random.uniform(args.extract_min, args.extract_max)
            if pos_b + ext_b > dur_b:
                print(f"[{i}] Fin de la vidéo B atteinte ({pos_b:.1f}s).")
                break

            seg_a = os.path.join(tmp_dir, f"seg_{i:03d}_a.mp4")
            seg_b = os.path.join(tmp_dir, f"seg_{i:03d}_b.mp4")
            print(f"[{i}] A {pos_a:.1f}-{pos_a+ext_a:.1f}s   B {pos_b:.1f}-{pos_b+ext_b:.1f}s", flush=True)
            extract_segment(args.video_a, pos_a, ext_a, seg_a, args.width, args.height, args.fps)
            extract_segment(args.video_b, pos_b, ext_b, seg_b, args.width, args.height, args.fps)
            segments += [seg_a, seg_b]

            pos_a += ext_a + random.uniform(args.gap_min, args.gap_max)
            pos_b += ext_b + random.uniform(args.gap_min, args.gap_max)
            i += 1

        if not segments:
            print("Aucun extrait généré — vidéos trop courtes pour les paramètres donnés ?")
            sys.exit(1)

        list_path = os.path.join(tmp_dir, "concat.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for s in segments:
                f.write(f"file '{s}'\n")

        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
            "-c", "copy", "-movflags", "+faststart",
            "-hide_banner", "-loglevel", "error",
            args.out,
        ], check=True)

        total_dur = probe_duration(args.out)
        print(f"\n✅ {args.out} généré — {len(segments)} extraits ({i} paires A/B), {total_dur:.1f}s au total")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
