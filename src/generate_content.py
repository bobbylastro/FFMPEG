import json
import logging
import os

import anthropic

from config.settings import ANTHROPIC_API_KEY

log = logging.getLogger(__name__)

CONTENT_DIR = "data/content"
COUNTER_PATH = "data/episode_counter.json"


def _load_content(game: str) -> dict:
    slug = game.lower().replace(" ", "-").replace(":", "")
    path = os.path.join(CONTENT_DIR, f"{slug}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No content file for game: {game} (expected {path})")
    with open(path) as f:
        return json.load(f)


def get_youtube_title(game: str, episode: int) -> str:
    content = _load_content(game)
    titles = content["youtube_long"]["titles"]
    return titles[(episode - 1) % len(titles)].format(episode=episode)


def get_youtube_description(game: str, episode: int) -> str:
    content = _load_content(game)
    descriptions = content["youtube_long"]["descriptions"]
    return descriptions[(episode - 1) % len(descriptions)]


def generate_ai_content(clips: list[dict], short_clips: list[dict]) -> tuple[str, list[str]]:
    """Un seul appel Haiku pour générer les chapitres YouTube et les descriptions Shorts.

    Retourne (chapters_block, [desc_short_1, desc_short_2, ...]).
    """
    if not clips:
        return "", []

    game = clips[0].get("_game", "Gaming")
    clips_block = "\n".join(f"{i+1}. {c['title']}" for i, c in enumerate(clips))
    shorts_block = "\n".join(
        f"SHORT_{i+1}: \"{c['title']}\""
        for i, c in enumerate(short_clips)
    )

    prompt = (
        f"You are generating content for a {game} YouTube compilation channel.\n\n"

        "## TASK 1 — CHAPTER LABELS\n"
        "Convert each clip title into a short action label (3-5 words max).\n"
        "Rules: no player names, describe only the action, punchy.\n"
        "Output one label per line under the header CHAPTERS:\n\n"
        f"{clips_block}\n\n"

        "## TASK 2 — SHORTS DESCRIPTIONS\n"
        "Write a punchy YouTube Shorts description for each clip below.\n"
        "Rules: 2-3 lines, energetic tone, end with 5-8 hashtags including #Shorts, no player names.\n"
        "Output each description under its own header SHORT_1:, SHORT_2:, etc.\n\n"
        f"{shorts_block}"
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()

    # --- Parse CHAPTERS ---
    chapters_str = ""
    if "CHAPTERS:" in text:
        raw = text.split("CHAPTERS:")[1]
        raw = raw.split("SHORT_1:")[0].strip()
        labels = [l.strip() for l in raw.splitlines() if l.strip()]
        lines = ["00:00 Intro"]
        t = 0.0
        for clip, label in zip(clips, labels):
            t_int = int(t)
            lines.append(f"{t_int // 60:02d}:{t_int % 60:02d} {label}")
            t += clip.get("duration", 30)
        chapters_str = "\n".join(lines)

    # --- Parse SHORTS ---
    short_descs = []
    for i in range(len(short_clips)):
        marker = f"SHORT_{i+1}:"
        next_marker = f"SHORT_{i+2}:"
        if marker in text:
            chunk = text.split(marker)[1]
            if next_marker in chunk:
                chunk = chunk.split(next_marker)[0]
            short_descs.append(chunk.strip())
        else:
            short_descs.append("")

    return chapters_str, short_descs


