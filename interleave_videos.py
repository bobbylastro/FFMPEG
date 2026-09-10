#!/usr/bin/env python3
"""
Interleave deux vidéos : alterne des extraits entre les deux sources (A et B).

Par cycle, on prend `ratio_a` extraits de A puis `ratio_b` extraits de B (défaut 1:1).
Entre deux extraits consécutifs pris dans la MÊME source, on avance en plus d'un "gap"
(~3-4s par défaut) non utilisé dans le montage — pour éviter que le 2e extrait d'une
source ne soit perçu comme la simple suite du 1er.

`--focus` permet de sur-représenter une source pendant une plage de SA propre timeline
(ex. "beaucoup de A entre 0:40 et 1:15").

Usage:
  python interleave_videos.py <video_a> <video_b> [-o output.mp4]
    [--ratio 1:1] [--extract-min 5] [--extract-max 7] [--gap-min 3] [--gap-max 4]
    [--start-a 0] [--start-b 0] [--width 1920] [--height 1080] [--fps 30] [--seed N]
    [--focus <a|b> <start> <end> <ratio_a> <ratio_b>]   (répétable)

Exemples :
  python interleave_videos.py A.mp4 B.mp4 -o out.mp4
  python interleave_videos.py A.mp4 B.mp4 -o out.mp4 --ratio 1:2 --extract-max 5 \
    --focus a 0:40 1:15 3 1
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile


def parse_tc(s: str) -> float:
    """'75', '1:15' ou '0:01:15' -> secondes."""
    parts = [float(x) for x in str(s).split(":")]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse_ratio(s: str) -> tuple[int, int]:
    a, b = s.split(":")
    return max(0, int(a)), max(0, int(b))


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
    p.add_argument("--ratio", default="1:1", help="Extraits de A : extraits de B par cycle (défaut 1:1)")
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
    p.add_argument("--focus", action="append", nargs=5, default=[],
                   metavar=("SRC", "START", "END", "RA", "RB"),
                   help="Sur-représente SRC (a|b) quand SA position est dans [START,END] : ratio RA:RB")
    args = p.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    normal_ratio = parse_ratio(args.ratio)
    focus = []
    for src, start, end, ra, rb in args.focus:
        src = src.lower()
        if src not in ("a", "b"):
            p.error(f"--focus SRC doit être 'a' ou 'b', reçu '{src}'")
        focus.append({"src": src, "lo": parse_tc(start), "hi": parse_tc(end),
                      "ratio": (max(0, int(ra)), max(0, int(rb)))})

    dur = {"a": probe_duration(args.video_a), "b": probe_duration(args.video_b)}
    src_path = {"a": args.video_a, "b": args.video_b}
    pos = {"a": args.start_a, "b": args.start_b}
    print(f"A ({args.video_a}): {dur['a']:.1f}s   B ({args.video_b}): {dur['b']:.1f}s")
    if focus:
        for fw in focus:
            print(f"  focus {fw['src'].upper()} {fw['lo']:.0f}-{fw['hi']:.0f}s -> ratio {fw['ratio'][0]}:{fw['ratio'][1]}")

    segments = []
    tmp_dir = tempfile.mkdtemp(prefix="interleave_")
    i = 0
    done = False
    try:
        while not done:
            na, nb = normal_ratio
            for fw in focus:
                if fw["lo"] <= pos[fw["src"]] <= fw["hi"]:
                    na, nb = fw["ratio"]
                    break

            for src, count in (("a", na), ("b", nb)):
                for _ in range(count):
                    ext = random.uniform(args.extract_min, args.extract_max)
                    if pos[src] + ext > dur[src]:
                        print(f"[{i}] Fin de la vidéo {src.upper()} atteinte ({pos[src]:.1f}s).")
                        done = True
                        break
                    seg = os.path.join(tmp_dir, f"seg_{i:04d}_{src}.mp4")
                    print(f"[{i}] {src.upper()} {pos[src]:.1f}-{pos[src]+ext:.1f}s", flush=True)
                    extract_segment(src_path[src], pos[src], ext, seg,
                                    args.width, args.height, args.fps)
                    segments.append(seg)
                    pos[src] += ext + random.uniform(args.gap_min, args.gap_max)
                    i += 1
                if done:
                    break

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
        na_cnt = sum(1 for s in segments if s.endswith("_a.mp4"))
        nb_cnt = len(segments) - na_cnt
        print(f"\n✅ {args.out} généré — {len(segments)} extraits "
              f"({na_cnt} A / {nb_cnt} B), {total_dur:.1f}s au total")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
