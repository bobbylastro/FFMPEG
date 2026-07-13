"""
Génère assets/trailer_catalog.json en décrivant visuellement chaque moment des trailers GTA 6.

Stratégie de segmentation :
  1. Détection des cuts de scène via FFmpeg (seuil configurable)
  2. Ajout de samples réguliers (toutes les REGULAR_INTERVAL s) pour couvrir les plans longs
  3. Déduplication des timestamps trop proches (< MIN_GAP s)

Usage :
  python src/build_trailer_catalog.py
  python src/build_trailer_catalog.py --threshold 0.2   (plus sensible)
  python src/build_trailer_catalog.py --interval 4      (samples réguliers toutes les 4s)
"""
import argparse
import base64
import glob
import json
import logging
import math
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import anthropic

from config.settings import ANTHROPIC_API_KEY

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

TRAILERS_DIR     = "assets/gta6_trailers"
CATALOG_PATH     = "assets/trailer_catalog.json"
SCENE_THRESHOLD  = 0.20   # seuil de détection de cut (0.1=sensible, 0.4=cuts francs seulement)
REGULAR_INTERVAL = 4      # secondes entre samples réguliers (filet de sécurité pour plans longs)
MIN_GAP          = 1.0    # gap minimum entre deux timestamps (évite doublons)
INTRO_SKIP       = 8.0    # secondes à sauter en début de trailer (écrans Rockstar)
BATCH_SIZE       = 6      # frames envoyées par appel Claude Vision
MODEL            = "claude-haiku-4-5-20251001"


def _get_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def _detect_scene_cuts(trailer_path: str, threshold: float, skip: float) -> list[float]:
    """Détecte les timestamps des cuts de scène via FFmpeg select+metadata."""
    with tempfile.NamedTemporaryFile(mode="r", suffix=".txt", delete=False) as mf:
        meta_path = mf.name

    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", trailer_path,
            "-vf", (
                f"select='gte(t,{skip})*gt(scene,{threshold})',"
                f"metadata=print:file={meta_path}"
            ),
            "-vsync", "vfr", "-f", "null", "-",
        ], capture_output=True)

        timestamps = []
        with open(meta_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = re.search(r"pts_time:([\d.]+)", line)
                if m:
                    ts = float(m.group(1))
                    if ts >= skip:
                        timestamps.append(ts)
    finally:
        try:
            os.unlink(meta_path)
        except OSError:
            pass

    return sorted(set(round(t, 2) for t in timestamps))


def _add_regular_samples(scene_ts: list[float], duration: float,
                          interval: float, skip: float) -> list[float]:
    """Ajoute des samples toutes les `interval` secondes pour couvrir les plans longs sans cut."""
    all_ts = set(scene_ts)
    t = skip
    while t <= duration:
        # Ajouter seulement si aucun sample existant n'est dans la fenêtre [t-interval/2, t+interval/2]
        if not any(abs(existing - t) < interval / 2 for existing in all_ts):
            all_ts.add(round(t, 2))
        t += interval
    return sorted(all_ts)


def _deduplicate(timestamps: list[float], min_gap: float) -> list[float]:
    """Supprime les timestamps trop proches (garde le premier de chaque groupe)."""
    result = []
    for ts in timestamps:
        if not result or ts - result[-1] >= min_gap:
            result.append(ts)
    return result


def _extract_frame(trailer_path: str, ts: float, out_dir: str) -> str | None:
    """Extrait une frame JPEG à `ts` secondes."""
    out_path = os.path.join(out_dir, f"frame_{ts:.2f}.jpg")
    subprocess.run([
        "ffmpeg", "-y",
        "-ss", f"{ts:.3f}", "-i", trailer_path,
        "-vframes", "1",
        "-q:v", "3",
        "-vf", "scale=640:-1",
        out_path,
    ], capture_output=True)
    return out_path if os.path.exists(out_path) else None


def _describe_batch(frames: list[tuple[float, str]], trailer_name: str,
                    client: anthropic.Anthropic) -> list[dict]:
    """Envoie un batch de frames à Claude Vision et retourne les descriptions."""
    content = []

    for ts, path in frames:
        with open(path, "rb") as f:
            img_b64 = base64.standard_b64encode(f.read()).decode()
        content.append({"type": "text", "text": f"[Frame t={ts:.1f}s]"})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64},
        })

    content.append({
        "type": "text",
        "text": (
            "These are frames from a GTA 6 trailer. Describe each frame in ONE precise sentence "
            "(20 words max) in English. Focus on: who is visible, location/setting, action happening, "
            "and mood/atmosphere — information useful for matching narration topics to visuals. "
            "Be specific: name characters if recognizable (Lucia, Jason), name locations if clear. "
            "Reply ONLY with this JSON array (same order as frames):\n"
            '["description1", "description2", ...]'
        )
    })

    resp = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        messages=[{"role": "user", "content": content}],
    )

    raw = resp.content[0].text.strip()
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        log.warning(f"JSON non trouvé dans la réponse : {raw[:200]}")
        return [{"trailer": trailer_name, "ts": ts, "description": ""} for ts, _ in frames]

    descriptions = json.loads(match.group())
    # Padding si Claude retourne moins de descriptions que de frames
    while len(descriptions) < len(frames):
        descriptions.append("")

    return [
        {"trailer": trailer_name, "ts": round(ts, 1), "description": desc}
        for (ts, _), desc in zip(frames, descriptions)
    ]


def build_catalog(threshold: float = SCENE_THRESHOLD,
                  interval: float = REGULAR_INTERVAL) -> list[dict]:
    trailers = sorted(
        glob.glob(os.path.join(TRAILERS_DIR, "*.mp4"))
        + glob.glob(os.path.join(TRAILERS_DIR, "*.mov"))
    )
    if not trailers:
        raise FileNotFoundError(f"Aucun trailer dans {TRAILERS_DIR}")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    catalog = []

    with tempfile.TemporaryDirectory() as tmp:
        for trailer_path in trailers:
            trailer_name = os.path.splitext(os.path.basename(trailer_path))[0]
            duration = _get_duration(trailer_path)
            log.info(f"\nTrailer : {trailer_name} ({duration:.1f}s)")

            # 1. Détection des cuts de scène
            log.info(f"  Détection des cuts (seuil={threshold})...")
            scene_ts = _detect_scene_cuts(trailer_path, threshold, INTRO_SKIP)
            log.info(f"  → {len(scene_ts)} cuts détectés")

            # 2. Ajout des samples réguliers
            all_ts = _add_regular_samples(scene_ts, duration, interval, INTRO_SKIP)
            log.info(f"  → {len(all_ts)} timestamps après samples réguliers ({interval}s)")

            # 3. Déduplication
            timestamps = _deduplicate(all_ts, MIN_GAP)
            log.info(f"  → {len(timestamps)} timestamps après déduplication (gap={MIN_GAP}s)")

            # 4. Extraction des frames
            frames: list[tuple[float, str]] = []
            for ts in timestamps:
                path = _extract_frame(trailer_path, ts, tmp)
                if path:
                    frames.append((ts, path))
            log.info(f"  → {len(frames)} frames extraites")

            # 5. Description par batchs
            n_batches = math.ceil(len(frames) / BATCH_SIZE)
            for i in range(n_batches):
                batch = frames[i * BATCH_SIZE:(i + 1) * BATCH_SIZE]
                log.info(f"  Batch {i+1}/{n_batches} (t={batch[0][0]:.0f}s → t={batch[-1][0]:.0f}s)...")
                entries = _describe_batch(batch, trailer_name, client)
                catalog.extend(entries)
                log.info(f"    ✓ {entries[0]['description'][:60]}…")

    catalog.sort(key=lambda x: (x["trailer"], x["ts"]))
    return catalog


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=SCENE_THRESHOLD,
                        help="Seuil de détection de cut (défaut: 0.25)")
    parser.add_argument("--interval", type=float, default=REGULAR_INTERVAL,
                        help="Intervalle des samples réguliers en secondes (défaut: 5)")
    args = parser.parse_args()

    log.info(f"Construction du catalogue — seuil={args.threshold}, interval={args.interval}s")
    catalog = build_catalog(threshold=args.threshold, interval=args.interval)

    os.makedirs(os.path.dirname(os.path.abspath(CATALOG_PATH)), exist_ok=True)
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)

    t1 = [e for e in catalog if "Trailer 1" in e["trailer"]]
    t2 = [e for e in catalog if "Trailer 2" in e["trailer"]]
    log.info(f"\n✅ Catalogue sauvegardé : {CATALOG_PATH}")
    log.info(f"   T1 : {len(t1)} entrées  |  T2 : {len(t2)} entrées  |  Total : {len(catalog)}")
    log.info("\nExtraits :")
    for e in catalog[:6]:
        log.info(f"  [{('T1' if 'Trailer 1' in e['trailer'] else 'T2')} t={e['ts']:.0f}s] {e['description']}")
    log.info("  ...")
