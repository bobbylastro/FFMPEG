"""
Génère 3 scripts depuis les posts Reddit GTA 6 :
  - long_en  : vidéo YouTube longue (~400-500 mots, ~3 min)
  - short_en : YouTube Short (~130-150 mots, ~55 sec)
  - tiktok_fr: TikTok en français (~130-150 mots, ~55 sec)
"""
import json
import logging
import re

import anthropic

from config.settings import ANTHROPIC_API_KEY

log = logging.getLogger(__name__)
MODEL = "claude-haiku-4-5-20251001"


def _build_context(posts: list[dict]) -> str:
    parts = []
    for p in posts[:8]:
        flair = f"[{p['flair']}] " if p["flair"] else ""
        body  = p["body"].strip()
        parts.append(f"{flair}{p['title']}\n{body}" if body else f"{flair}{p['title']}")
    return "\n\n---\n\n".join(parts)


def generate_scripts(posts: list[dict], topic: str = "") -> dict:
    """
    Retourne {"long_en": str, "short_en": str, "tiktok_fr": str}.
    topic optionnel pour orienter le script sur un angle spécifique.
    """
    context = _build_context(posts)
    topic_hint = f"\nFocus specifically on this angle: {topic}\n" if topic else ""

    prompt = f"""You are a YouTube content creator specializing in GTA 6 hype content.
GTA 6 is NOT yet released (launch date: November 19, 2026).
Based on the Reddit posts below, write engaging scripts about GTA 6 theories, leaks, and news.
{topic_hint}
Reddit content:
{context}

Write THREE scripts. Pure spoken text only — no stage directions, no emojis, no hashtags, no [Music] tags.

LONG_EN (~420 words, ~3 minutes spoken at 140 wpm):
- Hook: start with a bold statement or question that grabs attention immediately
- Cover 2-3 theories or news items from the posts
- Conversational YouTube tone, enthusiastic
- End with "Subscribe for more GTA 6 coverage" and a question for comments

SHORT_EN (~140 words, ~55 seconds spoken):
- Hook in the very first sentence
- Focus on ONE interesting theory or piece of news
- End with a short punchy call to action

TIKTOK_FR (~140 words, ~55 seconds spoken):
- Same topic as SHORT_EN but in natural, casual French
- Hook in the first sentence in French
- Modern French internet slang is welcome
- End with a question to engage viewers

Return ONLY this JSON (no other text):
{{
  "long_en": "...",
  "short_en": "...",
  "tiktok_fr": "..."
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = resp.content[0].text.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON in response: {raw[:300]!r}")

    scripts = json.loads(match.group())
    for key in ("long_en", "short_en", "tiktok_fr"):
        if key not in scripts:
            raise ValueError(f"Missing key '{key}' in AI response")

    log.info(
        f"Scripts générés — long: {len(scripts['long_en'])} chars, "
        f"short: {len(scripts['short_en'])} chars, "
        f"tiktok: {len(scripts['tiktok_fr'])} chars"
    )
    return scripts
