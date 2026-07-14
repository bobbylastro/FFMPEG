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

TOPICS_FILE   = os.path.join(os.path.dirname(__file__), "..", "data", "gta6_topics.json")
CATALOG_FILE  = os.path.join(os.path.dirname(__file__), "..", "assets", "trailer_catalog.json")


def load_trailer_catalog() -> list[dict]:
    if not os.path.exists(CATALOG_FILE):
        return []
    with open(CATALOG_FILE, encoding="utf-8") as f:
        return json.load(f)


def _format_catalog(catalog: list[dict]) -> str:
    """Catalogue compact pour le prompt : [trailer · ts] description."""
    lines = []
    for e in catalog:
        trailer_short = "T1" if "Trailer 1" in e["trailer"] else "T2"
        lines.append(f"[{trailer_short} t={e['ts']:.0f}s] {e['description']}")
    return "\n".join(lines)


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


def generate_scripts(posts: list[dict], topic: str = "", history: list[dict] | None = None,
                     catalog: list[dict] | None = None) -> dict:
    """
    Retourne {"long_en": str, "short_en": str, "tiktok_fr": str}.
    topic optionnel pour orienter le script sur un angle spécifique.
    """
    context = _build_context(posts)
    topic_hint = f"\nFocus specifically on this angle: {topic}\n" if topic else ""

    catalog_block = ""
    if catalog:
        catalog_block = f"\nTRAILER VISUAL CATALOG — use these timestamps to assign visuals:\n{_format_catalog(catalog)}\n"

    history_block = ""
    if history:
        lines = "\n".join(
            f"- {h['date']}: {h['angle']} — {h['summary'][:80]}"
            for h in history[-20:]  # derniers 20 sujets
        )
        history_block = f"\nALREADY COVERED (do NOT repeat these angles):\n{lines}\n"

    prompt = f"""You are a viral TikTok/Shorts content creator for GTA 6 hype content.
GTA 6 launches November 19, 2026 — it is NOT yet released.
Based on the Reddit posts below, pick the angle with the HIGHEST TikTok virality potential — not just the most "interesting" one.
Don't just describe theories — make it feel like breaking news or an exclusive reveal.

IMPORTANT — Choose an angle that is TIKTOK-NATIVE, not a generic news recap:
- Optimize for the scroll-stop test: could this angle work as a 3-word on-screen hook that makes someone stop mid-scroll?
- Favor angles that trigger a reaction, not just information: disbelief ("wait, WHAT?"), FOMO, a hot take people will agree/disagree with in the comments, a "you didn't notice this but now you can't unsee it" reveal
- Prefer angles framed around the VIEWER directly ("this changes how YOU'LL play", "you're going to waste hours on this") over distant/neutral framing ("Rockstar has added a feature")
- Comparisons, countdowns, and "X vs Y" framing perform well — use them when the posts support it
- Avoid hyper-specific angles that hinge on a single precise trailer moment (e.g. "a 3-second POV driving shot reveals physics", "one frame shows X detail") — these are impossible to illustrate without that exact moment
- The best angles are ones where ANY scenic, action, or character shot from the trailer naturally fits the narration

Three GOOD angle categories — pick whichever the posts best support, don't default to one:
1. REVEAL/THEORY: a hidden trailer detail, leak, or fan theory presented as an exclusive discovery
2. DEBATE/CONTROVERSY: a real news item people are already arguing about (price, a Rockstar decision, a comparison to another game, fan backlash) — take a clear side or pose it as a question to bait comments. These work great even from "dry" news posts (e.g. a $80 price tag called "ridiculous") when framed as a hot take
3. HYPE/COMPARISON: scale, visual fidelity, or world detail that makes the game look insane compared to GTA 5 or other games
{topic_hint}{history_block}{catalog_block}
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
  "tiktok_caption": "...",
  "short_post_index": 0,
  "use_post_image": true,
  "shots": [
    {{"pct": 0,  "trailer": "T1", "ts": 14}},
    {{"pct": 20, "trailer": "T1", "ts": 35}},
    {{"pct": 50, "trailer": "T2", "ts": 45}},
    {{"pct": 75, "trailer": "T2", "ts": 120}}
  ]
}}

thumbnail_title: 5-7 words MAX, ALL CAPS, punchy clickbait for the YouTube thumbnail.
Examples: "GTA 6 MAP IS 3X BIGGER?", "LUCIA'S DARK SECRET REVEALED", "THE CRAZIEST GTA 6 THEORY"

tiktok_hook: 4-5 words MAX, ALL CAPS, French teaser shown at the top of the TikTok for 3 seconds.
It must stop the scroll instantly. Use urgency, surprise, or a provocative question.
Examples: "LA MAP GTA 6 DÉVOILÉE", "CE DÉTAIL VA TE CHOQUER", "ILS ONT TOUT CACHÉ ?"

tiktok_caption: the TikTok post caption in French, ready to copy-paste when publishing.
- 1-2 short punchy sentences (max ~150 chars) restating the hook/angle, plus a line of EXACTLY 3 relevant hashtags
- Always include #gta6, then 2 more hashtags specific to today's angle (e.g. #vicecity, #lucia, #rockstargames, #gtavi, #gaming)
- Example: "Rockstar a caché un truc énorme dans le trailer 👀\n#gta6 #vicecity #gaming"

short_post_index: integer — the index (0-7) of the [POST N] that SHORT_EN focuses on.
The post may have an image — use_post_image tells whether to show it.

use_post_image: boolean — true ONLY if the post's image would genuinely illustrate the narration
(e.g. a map screenshot when talking about map size, a screenshot of the game when describing gameplay).
Set to false for generic promotional images, article thumbnails, or images unrelated to the narration angle.
When false, the video goes straight to trailer footage from the first second.

shots: visual timeline for SHORT_EN and TIKTOK_FR (6-8 entries).
- pct: 0-100, percentage into the script where this visual starts
- trailer: "T1" or "T2"
- ts: timestamp in seconds from the TRAILER VISUAL CATALOG above
Rules:
- Choose visuals that MATCH what's being said at each moment — make it feel directed
- EVERY shot must use a DIFFERENT timestamp (minimum 10s gap between any two shots from the same trailer)
- Alternate between T1 and T2 as much as possible for visual variety
- Spread shots evenly across the full runtime — avoid clustering them together
- If use_post_image is true: first shot at pct=0, start trailer shots at pct ≈ 13% (≈10s in an 80s video)
- If use_post_image is false: first shot at pct=0 goes directly to trailer footage
"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = resp.content[0].text.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON in response: {raw[:300]!r}")

    scripts = json.loads(match.group())
    for key in ("long_en", "short_en", "tiktok_fr", "thumbnail_title", "tiktok_hook", "tiktok_caption", "short_post_index", "use_post_image", "shots"):
        if key not in scripts:
            raise ValueError(f"Missing key '{key}' in AI response")

    log.info(
        f"Scripts générés — long: {len(scripts['long_en'])} chars, "
        f"short: {len(scripts['short_en'])} chars, "
        f"tiktok: {len(scripts['tiktok_fr'])} chars"
    )
    return scripts
