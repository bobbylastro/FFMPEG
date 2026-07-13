"""
Synthèse vocale via edge-tts (Microsoft Edge Neural TTS, gratuit, sans API key).
Génère l'audio MP3 + sous-titres SRT (long video) ou ASS (short/tiktok — style box dynamique).
"""
import asyncio
import logging
import os

import edge_tts

log = logging.getLogger(__name__)

VOICE_EN = "en-US-GuyNeural"
VOICE_FR = "fr-FR-RemyMultilingualNeural"
RATE_EN  = "+8%"
RATE_FR  = "+5%"

_FONTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "fonts"))


# ── SRT helpers (vidéo longue) ───────────────────────────────────────────────

def _fmt_srt_time(seconds: float) -> str:
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _words_to_srt(words: list[dict], path: str, chunk_size: int = 1) -> None:
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


# ── ASS helpers (short/tiktok — style TikTok dynamique) ──────────────────────

_ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: {res_x}
PlayResY: {res_y}
WrapStyle: 1
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Bebas Neue,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,10,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _fmt_ass_time(seconds: float) -> str:
    h   = int(seconds // 3600)
    m   = int((seconds % 3600) // 60)
    s   = seconds % 60
    cs  = int(round((s - int(s)) * 100))
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def _split_into_word_groups(sentences: list[dict], max_words: int = 3) -> list[dict]:
    """Découpe les phrases en groupes de max_words mots avec timing proportionnel."""
    result = []
    for sent in sentences:
        words    = sent["word"].split()
        n        = len(words)
        if n <= max_words:
            result.append(sent)
            continue
        per_word = sent["duration"] / n
        for i in range(0, n, max_words):
            group = words[i : i + max_words]
            result.append({
                "word":     " ".join(group),
                "start":    sent["start"] + i * per_word,
                "duration": len(group) * per_word,
            })
    return result


def _words_to_ass(sentences: list[dict], path: str,
                  max_words: int = 3, vertical: bool = True) -> None:
    """Génère un fichier ASS style TikTok : box semi-transparente, 2-3 mots dynamiques."""
    if not sentences:
        return

    chunks = _split_into_word_groups(sentences, max_words)

    res_x, res_y = (1080, 1920) if vertical else (1920, 1080)
    font_size     = 160 if vertical else 80
    margin_v      = 220 if vertical else 80

    header = _ASS_HEADER.format(
        res_x=res_x, res_y=res_y, font_size=font_size, margin_v=margin_v
    )

    lines = [header.rstrip()]
    for chunk in chunks:
        start = _fmt_ass_time(chunk["start"])
        end   = _fmt_ass_time(chunk["start"] + chunk["duration"])
        text  = chunk["word"].upper()
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    log.info(f"ASS écrit : {path} ({len(chunks)} blocs depuis {len(sentences)} phrases)")


# ── Synthèse ─────────────────────────────────────────────────────────────────

async def _synthesize(
    text:       str,
    voice:      str,
    rate:       str,
    audio_path: str,
    sub_path:   str | None = None,
    sub_format: str = "srt",  # "srt" ou "ass"
    vertical:   bool = False,
) -> None:
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate)

    sentences: list[dict] = []
    audio_chunks: list[bytes] = []

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])
        elif chunk["type"] == "SentenceBoundary":
            sentences.append({
                "word":     chunk["text"],
                "start":    chunk["offset"]   / 10_000_000,
                "duration": chunk["duration"] / 10_000_000,
            })

    with open(audio_path, "wb") as f:
        for c in audio_chunks:
            f.write(c)

    log.info(f"Audio TTS : {audio_path} ({len(audio_chunks)} chunks, {len(sentences)} phrases)")

    if sub_path is not None:
        if sub_format == "ass":
            _words_to_ass(sentences, sub_path, max_words=3, vertical=vertical)
        else:
            _words_to_srt(sentences, sub_path)


def synthesize(text: str, voice: str, rate: str, audio_path: str,
               srt_path: str | None = None) -> None:
    asyncio.run(_synthesize(text, voice, rate, audio_path, srt_path, sub_format="srt"))


def synthesize_en(text: str, audio_path: str, srt_path: str | None = None) -> None:
    synthesize(text, VOICE_EN, RATE_EN, audio_path, srt_path)


def synthesize_fr(text: str, audio_path: str, srt_path: str | None = None) -> None:
    synthesize(text, VOICE_FR, RATE_FR, audio_path, srt_path)


def synthesize_en_short(text: str, audio_path: str, ass_path: str) -> None:
    """Pour YouTube Short 9:16 — sous-titres ASS dynamiques 2-3 mots, box style."""
    asyncio.run(_synthesize(text, VOICE_EN, RATE_EN, audio_path,
                            sub_path=ass_path, sub_format="ass", vertical=True))


def synthesize_fr_short(text: str, audio_path: str, ass_path: str) -> None:
    """Variante FR pour TikTok — sous-titres ASS dynamiques 2-3 mots."""
    asyncio.run(_synthesize(text, VOICE_FR, RATE_FR, audio_path,
                            sub_path=ass_path, sub_format="ass", vertical=True))
