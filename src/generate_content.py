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


def generate_chapters(clips: list[dict]) -> str:
    """Génère un bloc chapitres YouTube (timestamps + label action) pour la description."""
    if not clips:
        return ""

    titles_input = "\n".join(f"{i+1}. {c['title']}" for i, c in enumerate(clips))
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": (
                "Convert these gaming clip titles into very short action labels (3-5 words max).\n"
                "Rules: no player names, describe only what happens, keep it punchy.\n"
                "Output exactly one label per line, same order, no numbering, no extra text.\n\n"
                f"{titles_input}"
            ),
        }],
    )

    labels = [l.strip() for l in msg.content[0].text.strip().splitlines() if l.strip()]

    lines = ["00:00 Intro"]
    t = 0.0
    for clip, label in zip(clips, labels):
        t_int = int(t)
        lines.append(f"{t_int // 60:02d}:{t_int % 60:02d} {label}")
        t += clip.get("duration", 30)

    return "\n".join(lines)


def get_shorts_description(clip: dict) -> str:
    """Génère une description Shorts optimisée via Claude Haiku pour ce clip."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    title = clip.get("title", "")
    broadcaster = clip.get("broadcaster_name", "")
    game = clip.get("_game", "Valorant")

    prompt = (
        f"Write a short, punchy YouTube Shorts description for a {game} gaming clip.\n"
        f"Clip title: \"{title}\"\n"
        f"Player: {broadcaster}\n\n"
        "Requirements:\n"
        "- 2-3 lines max, energetic tone\n"
        "- End with 5-8 relevant hashtags on the last line\n"
        "- Include #Shorts\n"
        "- No emojis in hashtags, emojis allowed elsewhere\n"
        "- Output only the description text, nothing else"
    )

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


