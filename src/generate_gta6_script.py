"""
Génère 3 scripts depuis les posts Reddit GTA 6 :
  - long_en  : vidéo YouTube longue (~400-500 mots, ~3 min)
  - short_en : YouTube Short (~130-150 mots, ~55 sec)
  - tiktok_fr: TikTok en français (~130-150 mots, ~55 sec)
"""
import json
import logging
import os
import re

import anthropic

from config.settings import ANTHROPIC_API_KEY

log = logging.getLogger(__name__)
MODEL = "claude-haiku-4-5-20251001"

TOPICS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "gta6_topics.json")


def load_topic_history() -> list[dict]:
    """Charge l'historique des sujets GTA6 déjà traités."""
    if not os.path.exists(TOPICS_FILE):
        return []
    with open(TOPICS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_topic(scripts: dict, date_str: str) -> None:
    """Enregistre le sujet du jour dans l'historique."""
    os.makedirs(os.path.dirname(os.path.abspath(TOPICS_FILE)), exist_ok=True)
    history = load_topic_history()
    history.append({
        "date": date_str,
        "angle": scripts.get("thumbnail_title", ""),
        "hook": scripts.get("tiktok_hook", ""),
        "summary": scripts.get("short_en", "")[:120],
    })
    with open(TOPICS_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def _build_context(posts: list[dict]) -> str:
    parts = []
    for i, p in enumerate(posts[:8]):
        flair = f"[{p['flair']}] " if p["flair"] else ""
        body  = p["body"].strip()
        img   = f"\n[image disponible: {p['image_url']}]" if p.get("image_url") else ""
        text  = f"{flair}{p['title']}\n{body}" if body else f"{flair}{p['title']}"
        parts.append(f"[POST {i}]{img}\n{text}")
    return "\n\n---\n\n".join(parts)


def generate_scripts(posts: list[dict], topic: str = "", history: list[dict] | None = None) -> dict:
    """
    Retourne {"long_en": str, "short_en": str, "tiktok_fr": str}.
    topic optionnel pour orienter le script sur un angle spécifique.
    """
    context = _build_context(posts)
    topic_hint = f"\nFocus specifically on this angle: {topic}\n" if topic else ""

    history_block = ""
    if history:
        lines = "\n".join(
            f"- {h['date']}: {h['angle']} — {h['summary'][:80]}"
            for h in history[-20:]  # derniers 20 sujets
        )
        history_block = f"\nALREADY COVERED (do NOT repeat these angles):\n{lines}\n"

    prompt = f"""You are a viral YouTube/TikTok content creator for GTA 6 hype content.
GTA 6 launches November 19, 2026 — it is NOT yet released.
Based on the Reddit posts below, pick the MOST interesting, surprising, or insane angle.
Don't just describe theories — make it feel like breaking news or an exclusive reveal.
{topic_hint}{history_block}
Reddit content:
{context}

Write THREE scripts. Pure spoken text only — no stage directions, no emojis, no hashtags, no [Music] tags.

LONG_EN (~420 words, ~3 minutes):
- Hook: start with the most jaw-dropping fact/detail in the first sentence
- Cover 2-3 different angles (hidden trailer details, leaks, comparisons, wild implications)
- Use rhetorical questions, build suspense, reveal progressively
- Conversational but energetic YouTube tone
- End with a subscribe CTA and a provocative question

SHORT_EN (~240 words, ~75-85 seconds — DO NOT END BEFORE 75 SECONDS):
- Pick the ONE most viral-worthy angle from the posts (surprising stat, wild detail, shocking implication)
- Hook: first sentence must be a jaw-dropping statement or question people need to answer
- Go deep on ONE thing only — build it up, give context, add details that surprise
- End on a cliffhanger or shocking twist
- Tone: urgent, like you just discovered something crazy

TIKTOK_FR (~240 words, ~75-85 seconds — DO NOT END BEFORE 75 SECONDS):
- SAME angle as SHORT_EN, adapted for French TikTok audience
- Start with a hook that stops the scroll in French
- Casual but excited tone — like you're telling your friends something insane
- Do NOT translate literally — rephrase naturally in French internet speak
- End with a question to trigger comments

Return ONLY this JSON (no other text):
{{
  "long_en": "...",
  "short_en": "...",
  "tiktok_fr": "...",
  "thumbnail_title": "...",
  "tiktok_hook": "...",
  "short_post_index": 0
}}

thumbnail_title: 5-7 words MAX, ALL CAPS, punchy clickbait for the YouTube thumbnail.
Examples: "GTA 6 MAP IS 3X BIGGER?", "LUCIA'S DARK SECRET REVEALED", "THE CRAZIEST GTA 6 THEORY"

tiktok_hook: 4-5 words MAX, ALL CAPS, French teaser shown at the top of the TikTok for 3 seconds.
It must stop the scroll instantly. Use urgency, surprise, or a provocative question.
Examples: "LA MAP GTA 6 DÉVOILÉE", "CE DÉTAIL VA TE CHOQUER", "ILS ONT TOUT CACHÉ ?"

short_post_index: integer — the index (0-7) of the [POST N] that SHORT_EN focuses on.
Used to show the post's image as background video. Pick the post with the most visual/image potential.
"""

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
    for key in ("long_en", "short_en", "tiktok_fr", "thumbnail_title", "tiktok_hook", "short_post_index"):
        if key not in scripts:
            raise ValueError(f"Missing key '{key}' in AI response")

    log.info(
        f"Scripts générés — long: {len(scripts['long_en'])} chars, "
        f"short: {len(scripts['short_en'])} chars, "
        f"tiktok: {len(scripts['tiktok_fr'])} chars"
    )
    return scripts
