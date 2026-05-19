import json
import logging

import anthropic

from config.settings import ANTHROPIC_API_KEY

log = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"


def select_clips_ai(candidates: list[dict], n: int, game_name: str = "gaming") -> list[dict]:
    """Ask Claude to pick the best n clips from candidates based on title/metadata."""
    if not candidates:
        return []

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    lines = []
    for i, c in enumerate(candidates):
        lines.append(
            f"{i}: title=\"{c['title']}\" | broadcaster={c['broadcaster_name']} "
            f"| {int(c['duration'])}s | {c['view_count']} views"
        )
    candidate_block = "\n".join(lines)

    prompt = f"""You are curating a {game_name} highlights compilation for YouTube. Pick the best {n} clips a general audience will enjoy.

A clip PASSES if its title contains at least one explicit gaming term relevant to {game_name}:
- Kill count or clutch word: ace, 4k, 3k, 2k, 1v2, 1v3, 1v4, 1v5, clutch, collateral, triple, quad, penta, kill, frag, DBNO, down
- Mechanic or action: flick, spray, peek, flank, snipe, wallbang, jumpshot, headshot, breach, rush, rotate, anchor, drone, defuse, plant
- Outcome: retake, outplay, comeback, overtime, ranked up, win, 1vX, carried, saved, comeback
- Any character, operator, agent, hero, or weapon name from {game_name} (e.g. an operator name in R6, agent in Valorant, legend in Apex, champion in LoL)
- Any pro player name known in the {game_name} competitive scene
- Qualifier + gaming term still PASSES: "almost ace", "worst 4k ever", "nearly clutched", "how lucky was that"

A clip FAILS only if its title contains NO gaming term at all:
- Pure song or artist name used as title: "heavenly", "Heart Attack", "lil yachty", "Billie Jean", "bye bye", "worry"
- Completely vague with no game context: "long time no see guys", "yall im so back", "We r who we r"
- Explicit edit/montage label: "first 2026 edit", "edit.mp4", "new edit", "my montage"
- Random/empty/filename: "t", "g", "clip.mp4"

Return exactly {n} clips if possible. When two clips are equal quality, prefer higher view count.

Candidates:
{candidate_block}

Respond with ONLY a JSON array of indices (integers), e.g. [0, 3, 7].
Return [] if truly none qualify. No explanation."""

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=64,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        log.debug(f"AI response: {raw}")
        indices = json.loads(raw)
        if not isinstance(indices, list):
            raise ValueError("not a list")
        indices = [int(x) for x in indices if 0 <= int(x) < len(candidates)]
        selected = [candidates[i] for i in indices[:n]]
        log.info(f"AI selected {len(selected)}/{len(candidates)} clips")
        return selected
    except Exception as e:
        log.warning(f"AI selection failed ({e}), falling back to top-{n} by velocity")
        return candidates[:n]
