#!/usr/bin/env python3
"""
Pipeline complet de détection par IA pour une ligue de combat de robots (URKL, REK, ...) :
nettoie R2, transcrit les rounds et upload les clips détectés, en une seule commande.

Usage: python3 src/urkl_pipeline.py <video_url> ["<rounds_spec>"] [whisper_model] [league]
  video_url: URL de la vidéo/stream à analyser (YouTube, X/Twitter broadcast, ...)
  rounds_spec: plages de rounds "MM:SS-MM:SS,MM:SS-MM:SS,..." ou "HH:MM:SS-HH:MM:SS,..."
               (vide ou omis = toute la vidéo)
  whisper_model: tiny|base|small|medium|large (défaut: small)
  league: urkl|rek (défaut: urkl) — sépare les données/clips par ligue

Étapes : nettoyage R2 -> urkl_transcribe_moments.py -> urkl_download.py 0
Ensuite : python3 src/urkl_validate.py 8888 <league>
"""
import sys, subprocess, os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "src"))
import urkl_r2 as r2lib


def clean_r2(league: str = "urkl"):
    r2 = r2lib.client()
    clips = r2lib.list_clips(r2, league)
    if clips:
        print(f"Nettoyage R2 ({len(clips)} clips)...")
        for c in clips:
            r2lib.delete_clip(c, r2, league)
        r2lib.save_state({}, r2, league)
        print("R2 nettoyé.")
    else:
        print("R2 déjà vide.")


def run(cmd):
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"ERREUR: {cmd[0]} a échoué (code {result.returncode})")
        sys.exit(result.returncode)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    video_url     = sys.argv[1]
    rounds_spec   = sys.argv[2] if len(sys.argv) > 2 else ""
    whisper_model = sys.argv[3] if len(sys.argv) > 3 else "small"
    league        = sys.argv[4] if len(sys.argv) > 4 else "urkl"

    print(f"=== 1/3 : Nettoyage R2 ({r2lib.display_name(league)}) ===")
    clean_r2(league)

    print("\n=== 2/3 : Transcription + détection IA ===")
    run(["python3", os.path.join(BASE_DIR, "src/urkl_transcribe_moments.py"),
         video_url, rounds_spec, whisper_model, league])

    print("\n=== 3/3 : Download + upload R2 ===")
    run(["python3", os.path.join(BASE_DIR, "src/urkl_download.py"), "0", video_url, league])

    print("\nPipeline terminé. Lance le serveur de validation :")
    print(f"  python3 {os.path.join(BASE_DIR, 'src/urkl_validate.py')} 8888 {league}")


if __name__ == "__main__":
    main()
