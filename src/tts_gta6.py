"""
Synthèse vocale via edge-tts (Microsoft Edge Neural TTS, gratuit, sans API key).
Génère l'audio MP3 + un fichier SRT synchronisé mot par mot.
"""
import asyncio
import logging
import os

import edge_tts

log = logging.getLogger(__name__)

VOICE_EN = "en-US-GuyNeural"
VOICE_FR = "fr-FR-HenriNeural"

# Légère accélération pour un rendu YouTube dynamique
RATE_EN = "+8%"
RATE_FR = "+5%"


def _fmt_srt_time(seconds: float) -> str:
    h   = int(seconds // 3600)
    m   = int((seconds % 3600) // 60)
    s   = int(seconds % 60)
    ms  = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _words_to_srt(words: list[dict], path: str, chunk_size: int = 1) -> None:
    """Écrit le fichier SRT (1 phrase par carte de sous-titre)."""
    if not words:
        return

    chunks = []
    for i in range(0, len(words), chunk_size):
        group = words[i : i + chunk_size]
        start = group[0]["start"]
        end   = group[-1]["start"] + group[-1]["duration"]
        text  = " ".join(w["word"] for w in group)
        chunks.append((start, end, text))

    with open(path, "w", encoding="utf-8") as f:
        for idx, (start, end, text) in enumerate(chunks, 1):
            f.write(f"{idx}\n{_fmt_srt_time(start)} --> {_fmt_srt_time(end)}\n{text}\n\n")

    log.info(f"SRT écrit : {path} ({len(chunks)} blocs)")


async def _synthesize(
    text: str,
    voice: str,
    rate: str,
    audio_path: str,
    srt_path: str | None,
) -> None:
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate)

    words: list[dict] = []
    audio_chunks: list[bytes] = []

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])
        elif chunk["type"] == "SentenceBoundary":
            words.append({
                "word":     chunk["text"],
                "start":    chunk["offset"]   / 10_000_000,
                "duration": chunk["duration"] / 10_000_000,
            })

    with open(audio_path, "wb") as f:
        for c in audio_chunks:
            f.write(c)
    log.info(f"Audio TTS : {audio_path} ({len(audio_chunks)} chunks, {len(words)} mots)")

    if srt_path is not None:
        _words_to_srt(words, srt_path)


def synthesize(
    text: str,
    voice: str,
    rate: str,
    audio_path: str,
    srt_path: str | None = None,
) -> None:
    asyncio.run(_synthesize(text, voice, rate, audio_path, srt_path))


def synthesize_en(text: str, audio_path: str, srt_path: str | None = None) -> None:
    synthesize(text, VOICE_EN, RATE_EN, audio_path, srt_path)


def synthesize_fr(text: str, audio_path: str, srt_path: str | None = None) -> None:
    synthesize(text, VOICE_FR, RATE_FR, audio_path, srt_path)
