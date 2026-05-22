import json
import logging
import os
import time

import anthropic

from config.settings import ANTHROPIC_API_KEY

log = logging.getLogger(__name__)

CONTENT_DIR = "data/content"


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


def generate_ai_content(clips: list[dict], short_clips: list[dict]) -> tuple[str, list[str], list[str]]:
    """Un seul appel Haiku pour générer les chapitres YouTube, les descriptions et titres Shorts.

    Retourne (chapters_block, [desc_short_1, ...], [title_short_1, ...]).
    """
    if not clips:
        return "", [], []

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

        "## TASK 2 — SHORTS TITLES\n"
        f"Write a punchy, SEO-optimized YouTube Shorts title for each clip below.\n"
        f"Rules: 45-60 chars, start with the action (power words: Insane, Clutch, Crazy, Perfect, etc.), "
        f"include '{game}', no player names, no hashtags.\n"
        "Output each title under its own header STITLE_1:, STITLE_2:, etc.\n\n"
        f"{shorts_block}\n\n"

        "## TASK 3 — SHORTS DESCRIPTIONS\n"
        "Write a punchy YouTube Shorts description for each clip below.\n"
        "Rules: 2-3 lines, energetic tone, end with 5-8 hashtags including #Shorts, no player names.\n"
        "Output each description under its own header SDESC_1:, SDESC_2:, etc.\n\n"
        f"{shorts_block}"
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    retries = [30, 60, 120]
    text = None
    for attempt in range(len(retries) + 1):
        try:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = msg.content[0].text.strip()
            break
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < len(retries):
                wait = retries[attempt]
                log.warning(f"API overloaded (529), retry dans {wait}s... (tentative {attempt + 1}/{len(retries)})")
                time.sleep(wait)
            else:
                raise
    if text is None:
        raise RuntimeError("generate_ai_content: toutes les tentatives ont échoué")

    # --- Parse CHAPTERS ---
    chapters_str = ""
    if "CHAPTERS:" in text:
        raw = text.split("CHAPTERS:")[1]
        raw = raw.split("SHORT_TITLE_1:")[0].strip()
        labels = [l.strip() for l in raw.splitlines() if l.strip()]
        lines = []
        t = 0.0
        for clip, label in zip(clips, labels):
            t_int = int(t)
            lines.append(f"{t_int // 60:02d}:{t_int % 60:02d} {label}")
            t += clip.get("duration", 30)
        chapters_str = "\n".join(lines)

    # --- Parse SHORTS TITLES ---
    short_titles = []
    for i in range(len(short_clips)):
        marker      = f"STITLE_{i+1}:"
        next_marker = f"STITLE_{i+2}:"
        if marker in text:
            chunk = text.split(marker)[1]
            if next_marker in chunk:
                chunk = chunk.split(next_marker)[0]
            title = chunk.strip().splitlines()[0].strip().strip('"').strip("'").strip('*').strip()
            if title:
                short_titles.append(title[:97])
            else:
                log.warning(f"STITLE_{i+1} parsed empty — fallback to clip title")
                short_titles.append(short_clips[i].get("title", "")[:97])
        else:
            log.warning(f"STITLE_{i+1} marker not found in AI response — fallback to clip title")
            short_titles.append(short_clips[i].get("title", "")[:97])

    # --- Parse SHORTS DESCRIPTIONS ---
    short_descs = []
    for i in range(len(short_clips)):
        marker      = f"SDESC_{i+1}:"
        next_marker = f"SDESC_{i+2}:"
        if marker in text:
            chunk = text.split(marker)[1]
            if next_marker in chunk:
                chunk = chunk.split(next_marker)[0]
            short_descs.append(chunk.strip())
        else:
            log.warning(f"SDESC_{i+1} marker not found in AI response")
            short_descs.append("")

    return chapters_str, short_descs, short_titles


