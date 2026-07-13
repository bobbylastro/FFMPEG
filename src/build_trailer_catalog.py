"""
Génère assets/trailer_catalog.json en décrivant visuellement chaque moment des trailers GTA 6.
Extrait 1 frame / 3 secondes (en sautant l'intro noire), envoie des batchs à Claude Vision.

Usage :
  python src/build_trailer_catalog.py
"""
import base64
import glob
import json
import logging
import math
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import anthropic

from config.settings import ANTHROPIC_API_KEY

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

TRAILERS_DIR = "assets/gta6_trailers"
CATALOG_PATH = "assets/trailer_catalog.json"
FRAME_INTERVAL = 3       # secondes entre chaque frame capturée
INTRO_SKIP    = 8        # secondes à sauter en début de trailer (écrans Rockstar)
BATCH_SIZE    = 6        # frames envoyées par appel Claude Vision
MODEL         = "claude-haiku-4-5-20251001"


def _get_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def _extract_frames(trailer_path: str, out_dir: str, interval: int, skip: float) -> list[tuple[float, str]]:
    """Extrait des frames JPEG et retourne [(timestamp, filepath), ...]."""
    duration = _get_duration(trailer_path)
    timestamps = [skip + i * interval for i in range(int((duration - skip) / interval))]

    frames = []
    for ts in timestamps:
        out_path = os.path.join(out_dir, f"frame_{ts:.1f}.jpg")
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(ts), "-i", trailer_path,
            "-vframes", "1",
            "-q:v", "4",          # qualité correcte sans fichier trop lourd
            "-vf", "scale=640:-1",
            out_path,
        ]
        subprocess.run(cmd, capture_output=True)
        if os.path.exists(out_path):
            frames.append((ts, out_path))

    return frames


def _describe_batch(frames: list[tuple[float, str]], trailer_name: str, client: anthropic.Anthropic) -> list[dict]:
    """Envoie un batch de frames à Claude Vision et retourne les descriptions."""
    content = []

    for ts, path in frames:
        with open(path, "rb") as f:
            img_b64 = base64.standard_b64encode(f.read()).decode()
        content.append({
            "type": "text",
            "text": f"[Frame à t={ts:.1f}s]"
        })
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": img_b64,
            }
        })

    content.append({
        "type": "text",
        "text": (
            "Décris chaque frame ci-dessus en UNE phrase courte (15 mots max) en anglais. "
            "Sois précis et visuel : personnages, lieux, actions, ambiance. "
            "Réponds UNIQUEMENT avec ce JSON (tableau dans le même ordre que les frames) :\n"
            '["description1", "description2", ...]'
        )
    })

    resp = client.messages.create(
        model=MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": content}],
    )

    raw = resp.content[0].text.strip()
    # Extraire le JSON du texte
    import re
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        log.warning(f"JSON non trouvé dans la réponse : {raw[:200]}")
        return [{"trailer": trailer_name, "ts": ts, "description": ""} for ts, _ in frames]

    descriptions = json.loads(match.group())
    return [
        {"trailer": trailer_name, "ts": ts, "description": desc}
        for (ts, _), desc in zip(frames, descriptions)
    ]


def build_catalog() -> list[dict]:
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
            log.info(f"Extraction frames : {trailer_name}")

            frames = _extract_frames(trailer_path, tmp, FRAME_INTERVAL, INTRO_SKIP)
            log.info(f"  {len(frames)} frames extraites")

            # Envoi par batchs
            n_batches = math.ceil(len(frames) / BATCH_SIZE)
            for i in range(n_batches):
                batch = frames[i * BATCH_SIZE:(i + 1) * BATCH_SIZE]
                log.info(f"  Batch {i+1}/{n_batches} ({len(batch)} frames)...")
                entries = _describe_batch(batch, trailer_name, client)
                catalog.extend(entries)
                log.info(f"    ✓ {[e['description'][:50] for e in entries]}")

    catalog.sort(key=lambda x: (x["trailer"], x["ts"]))
    return catalog


if __name__ == "__main__":
    log.info("Construction du catalogue des trailers GTA 6...")
    catalog = build_catalog()

    os.makedirs(os.path.dirname(CATALOG_PATH), exist_ok=True)
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)

    log.info(f"\n✅ Catalogue sauvegardé : {CATALOG_PATH} ({len(catalog)} entrées)")
    for entry in catalog[:5]:
        log.info(f"  [{entry['trailer']} t={entry['ts']:.1f}s] {entry['description']}")
    log.info("  ...")
