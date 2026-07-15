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


_CATALOG_BLACKLIST = ("title card", "rockstar games", "presents title", "presents logo")

def _format_catalog(catalog: list[dict]) -> str:
    """Catalogue compact pour le prompt : [trailer · ts] description."""
    lines = []
    for e in catalog:
        desc_low = e["description"].lower()
        if any(kw in desc_low for kw in _CATALOG_BLACKLIST):
            continue  # exclut les cartons titre "Rockstar Games presents"
        trailer_short = "T1" if "Trailer 1" in e["trailer"] else "T2"
        lines.append(f"[{trailer_short} t={e['ts']:.0f}s] {e['description']}")
    return "\n".join(lines)


def load_topic_history() -> list[dict]:
    """Charge l'historique des sujets GTA6 déjà traités."""
    if not os.path.exists(TOPICS_FILE):
        return []
    with open(TOPICS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_topic(scripts: dict, date_str: str, posts: list[dict] | None = None) -> None:
    """Enregistre le sujet du jour dans l'historique."""
    os.makedirs(os.path.dirname(os.path.abspath(TOPICS_FILE)), exist_ok=True)
    history = load_topic_history()
    source_titles = [p["title"][:80] for p in (posts or [])[:8]]
    history.append({
        "date":           date_str,
        "angle":          scripts.get("thumbnail_title", ""),
        "angle_category": scripts.get("angle_category", ""),
        "hook":           scripts.get("tiktok_hook", ""),
        "summary":        scripts.get("short_en", "")[:120],
        "source_titles":  source_titles,
    })
    with open(TOPICS_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


_DEBATE_CONSTRAINT_MSG = (
    "\n⚠️ CATEGORY CONSTRAINT: A recent run already covered a DEBATE/CONTROVERSY angle (price, analyst, crunch, backlash). "
    "You MUST pick a REVEAL or HYPE angle this time — completely ignore price/cost/analyst/crunch articles, "
    "find a different angle in the available posts.\n"
)


def _category_constraint(history: list[dict]) -> str:
    """Force la rotation REVEAL / DEBATE / HYPE.
    - Si DEBATE apparaît dans les 3 derniers runs catégorisés → force REVEAL ou HYPE
    - Si 2+ runs identiques (hors DEBATE) dans les 3 derniers → force rotation
    """
    recent = [h.get("angle_category", "") for h in history[-5:] if h.get("angle_category")]
    if not recent:
        return ""
    tail = recent[-3:]
    # DEBATE dans les 3 derniers → toujours bloquer (pas juste le run immédiat)
    if "DEBATE" in tail:
        return _DEBATE_CONSTRAINT_MSG
    # 2+ runs identiques → forcer rotation
    OTHERS = {"REVEAL": "HYPE or DEBATE", "HYPE": "REVEAL or DEBATE"}
    for cat, others in OTHERS.items():
        if tail.count(cat) >= 2:
            return (
                f"\n⚠️ CATEGORY CONSTRAINT: Recent runs were mostly {cat}. "
                f"You MUST pick a {others} angle this time.\n"
            )
    return ""


def _build_context(posts: list[dict]) -> str:
    parts = []
    for i, p in enumerate(posts[:8]):
        flair = f"[{p['flair']}] " if p["flair"] else ""
        body  = p["body"].strip()[:1800]
        img   = f"\n[image disponible: {p['image_url']}]" if p.get("image_url") else ""
        # Détecte si le body est essentiellement vide/inutilisable (juste le titre répété, ou <150 chars)
        body_is_thin = len(body) < 150 or body.lower().replace(" ", "").startswith(p["title"][:25].lower().replace(" ", ""))
        if body_is_thin:
            text = (f"{flair}{p['title']}\n"
                    "[⚠️ BODY UNAVAILABLE — only the title is accessible, no article text. "
                    "Do NOT pick this as your main angle; you cannot deliver specific details from it.]")
        else:
            text = f"{flair}{p['title']}\n{body}" if body else f"{flair}{p['title']}"
        parts.append(f"[POST {i}]{img}\n{text}")
    return "\n\n---\n\n".join(parts)


_DEBATE_TITLE_KW = [
    "$200", "$150", "$80", "$70", "price", "cost", "worth", "costs",
    "analyst", "crunch", "overtime", "layoff", "boycott", "backlash",
    "too expensive", "too cheap", "how much",
]

_TOPIC_STOP_WORDS = {
    "gta", "gta6", "the", "a", "an", "is", "was", "will", "be", "it", "its",
    "in", "on", "at", "to", "for", "of", "and", "or", "but", "this", "that",
    "with", "from", "has", "have", "had", "are", "were", "game", "games",
    "rockstar", "grand", "theft", "auto", "what", "your", "they", "their",
}


def _covered_keywords(history: list[dict], lookback: int = 6) -> set[str]:
    """Mots-clés significatifs extraits des angles et titres sources déjà couverts."""
    import re
    words: set[str] = set()
    for entry in history[-lookback:]:
        for w in re.findall(r"[a-z0-9]+", entry.get("angle", "").lower()):
            if len(w) >= 4 and w not in _TOPIC_STOP_WORDS:
                words.add(w)
        for title in entry.get("source_titles", [])[:3]:
            for w in re.findall(r"[a-z0-9]+", title.lower()):
                if len(w) >= 5 and w not in _TOPIC_STOP_WORDS:
                    words.add(w)
    return words


def _filter_repetitive_posts(posts: list[dict], history: list[dict],
                              active_debate_filter: bool = False) -> list[dict]:
    """Filtre en deux passes :
    1. Si active_debate_filter : retire articles DEBATE (prix/analyst/crunch) par mots-clés fixes
    2. Retire articles dont le titre chevauche ≥2 mots avec les angles déjà couverts
    """
    import re
    result = list(posts)

    # Passe 1 : mots-clés DEBATE fixes
    if active_debate_filter:
        no_debate = [
            p for p in result
            if not any(kw.lower() in p.get("title", "").lower() for kw in _DEBATE_TITLE_KW)
        ]
        if len(no_debate) >= 3:
            removed = len(result) - len(no_debate)
            log.info(f"  Filtre DEBATE : {removed} article(s) retirés")
            result = no_debate

    # Passe 2 : similarité avec angles déjà couverts
    if history:
        covered = _covered_keywords(history)
        no_overlap = []
        for p in result:
            title_words = set(re.findall(r"[a-z0-9]+", p.get("title", "").lower()))
            overlap = title_words & covered
            if len(overlap) >= 2:
                log.info(f"  Filtre overlap ({overlap}) : {p['title'][:60]}")
            else:
                no_overlap.append(p)
        if len(no_overlap) >= 3:
            result = no_overlap

    return result


def generate_scripts(posts: list[dict], topic: str = "", history: list[dict] | None = None,
                     catalog: list[dict] | None = None) -> dict:
    """
    Retourne {"long_en": str, "short_en": str, "tiktok_fr": str}.
    topic optionnel pour orienter le script sur un angle spécifique.
    """
    category_constraint = _category_constraint(history or [])

    # Filtrer les articles trop similaires à ce qui a déjà été couvert
    # (l'IA ne peut pas choisir ce qu'elle ne voit pas)
    active_debate_filter = "REVEAL or HYPE" in category_constraint
    effective_posts = _filter_repetitive_posts(posts, history or [], active_debate_filter)
    if len(effective_posts) < len(posts):
        log.info(f"  Articles filtrés : {len(effective_posts)}/{len(posts)} posts envoyés à l'IA")

    context = _build_context(effective_posts)
    topic_hint = f"\nFocus specifically on this angle: {topic}\n" if topic else ""

    catalog_block = ""
    if catalog:
        catalog_block = f"\nTRAILER VISUAL CATALOG — use these timestamps to assign visuals:\n{_format_catalog(catalog)}\n"

    history_block = ""
    if history:
        lines = []
        for h in history[-20:]:
            cat = h.get("angle_category", "")
            cat_tag = f"[{cat}] " if cat else ""
            line = f"- {h['date']}: {cat_tag}{h['angle']} — {h['summary'][:80]}"
            if h.get("source_titles"):
                line += f" [sources: {' | '.join(h['source_titles'][:3])}]"
            lines.append(line)
        history_block = "\nALREADY COVERED (do NOT repeat these angles or reuse these sources):\n" + "\n".join(lines) + "\n"

    prompt = f"""You are a viral TikTok/Shorts content creator for GTA 6 hype content.
GTA 6 launches November 19, 2026 — it is NOT yet released.
Based on the Reddit posts below, pick the angle with the HIGHEST TikTok virality potential — not just the most "interesting" one.
Don't just describe theories — make it feel like breaking news or an exclusive reveal.
{category_constraint}
IMPORTANT — Choose an angle that is TIKTOK-NATIVE, not a generic news recap:
- Optimize for the scroll-stop test: could this angle work as a 3-word on-screen hook that makes someone stop mid-scroll?
- Favor angles that trigger a reaction, not just information: disbelief ("wait, WHAT?"), FOMO, a hot take people will agree/disagree with in the comments, a "you didn't notice this but now you can't unsee it" reveal
- Prefer angles framed around the VIEWER directly ("this changes how YOU'LL play", "you're going to waste hours on this") over distant/neutral framing ("Rockstar has added a feature")
- Comparisons, countdowns, and "X vs Y" framing perform well — use them when the posts support it
- Avoid hyper-specific angles that hinge on a single precise trailer moment (e.g. "a 3-second POV driving shot reveals physics", "one frame shows X detail") — these are impossible to illustrate without that exact moment
- The best angles are ones where ANY scenic, action, or character shot from the trailer naturally fits the narration

Three GOOD angle categories — pick whichever the posts best support, don't default to one:
1. REVEAL/THEORY: a hidden trailer detail, leak, or fan theory presented as an exclusive discovery. Only pick this if the post actually contains a specific surprising detail — do NOT invent mechanics that aren't mentioned in the posts.
2. DEBATE/CONTROVERSY: a real news item people are already arguing about (price, a Rockstar decision, a comparison to another game, fan backlash) — take a clear side or pose it as a question to bait comments.
3. HYPE/COMPARISON: confirmed official features, scale, visual fidelity, or world detail that makes the game look insane compared to GTA 5 or other games.

IMPORTANT — prioritization rule: if any post lists confirmed/official GTA 6 features or gameplay mechanics, PREFER that over a speculative "hidden mechanic" theory. Confirmed content is more credible and drives more saves/shares than speculation.
{topic_hint}{history_block}{catalog_block}
Reddit content:
{context}

CRITICAL RULE — ONLY PROMISE WHAT THE POSTS ACTUALLY CONTAIN:
The posts below include the FULL article body text (not just RSS excerpts). Before picking an angle, verify that the specific details are actually present in the text:
- If you want to say "5 features", the 5 features must be NAMED and DESCRIBED in the posts. If they are listed, name them explicitly in your script.
- If you want to say "SECRET EXPOSED", the secret must be described in the posts. Don't invent mechanics that aren't mentioned.
- NEVER pick an angle that requires details you don't have. A script that vaguely alludes to "incredible features" without naming them is worthless and embarrassing.
Work only with what is actually written in the posts. If a post lists specific features/details/mechanics, USE THEM — name them one by one in your script. That's the whole point.

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
  "angle_category": "REVEAL",
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

angle_category: the category of this angle — exactly one of "REVEAL", "DEBATE", or "HYPE".
REVEAL = hidden detail, leak, fan theory, exclusive discovery.
DEBATE = controversy, price, crunch, backlash, hot take, comparison that divides people.
HYPE = scale, visual fidelity, world detail, insane comparison to other games.

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
- NEVER use title cards, logo screens, or "presents" text overlays — these show text-on-black behind subtitles and look terrible
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
    for key in ("long_en", "short_en", "tiktok_fr", "thumbnail_title", "tiktok_hook", "tiktok_caption", "short_post_index", "use_post_image", "angle_category", "shots"):
        if key not in scripts:
            raise ValueError(f"Missing key '{key}' in AI response")

    log.info(
        f"Scripts générés — long: {len(scripts['long_en'])} chars, "
        f"short: {len(scripts['short_en'])} chars, "
        f"tiktok: {len(scripts['tiktok_fr'])} chars"
    )
    return scripts
