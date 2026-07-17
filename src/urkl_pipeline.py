#!/usr/bin/env python3
"""
Pipeline complet URKL (détection par IA) : nettoie R2, transcrit les rounds et upload
les clips détectés, en une seule commande.

Usage: python3 src/urkl_pipeline.py "<rounds_spec>" [whisper_model]
  rounds_spec: plages de rounds "MM:SS-MM:SS,MM:SS-MM:SS,..." ou "HH:MM:SS-HH:MM:SS,..."
  whisper_model: tiny|base|small|medium|large (défaut: small)

Étapes : nettoyage R2 -> urkl_transcribe_moments.py -> urkl_download.py 0
Ensuite : python3 src/urkl_validate.py 8888
"""
import sys, subprocess, os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "src"))
import urkl_r2 as r2lib


def clean_r2():
    r2 = r2lib.client()
    clips = r2lib.list_clips(r2)
    if clips:
        print(f"Nettoyage R2 ({len(clips)} clips)...")
        for c in clips:
            r2lib.delete_clip(c, r2)
        r2lib.save_state({}, r2)
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

    rounds_spec = sys.argv[1]
    whisper_model = sys.argv[2] if len(sys.argv) > 2 else "small"

    print("=== 1/3 : Nettoyage R2 ===")
    clean_r2()

    print("\n=== 2/3 : Transcription + détection IA ===")
    run(["python3", os.path.join(BASE_DIR, "src/urkl_transcribe_moments.py"), rounds_spec, whisper_model])

    print("\n=== 3/3 : Download + upload R2 ===")
    run(["python3", os.path.join(BASE_DIR, "src/urkl_download.py"), "0"])

    print("\nPipeline terminé. Lance le serveur de validation :")
    print(f"  python3 {os.path.join(BASE_DIR, 'src/urkl_validate.py')} 8888")


if __name__ == "__main__":
    main()
