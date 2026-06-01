import json
import logging
import re
import time

import anthropic

from config.settings import ANTHROPIC_API_KEY

log = logging.getLogger(__name__)

class NoClipsSelectedError(Exception):
    """L'IA n'a retenu aucun clip parmi les candidats."""

MODEL = "claude-haiku-4-5-20251001"

_GAME_CONTEXT = {
    "valorant":      "Tactical 5v5 FPS with agents that have unique abilities. Teams attack/defend a bomb site. Round-based, one life per round.",
    "marvel-rivals": "6v6 hero shooter with Marvel characters. Two teams fight to capture/push objectives. Heroes have powerful ultimates and combos.",
    "the-finals":    "3-team FPS with massive environmental destruction. Teams compete to steal and hold a cashout briefcase. Gadgets and building destruction are core mechanics.",
    "apex-legends":  "Battle royale FPS with squads of 3. Last squad standing wins. Characters have unique abilities. High movement, fast TTK.",
    "rocket-league": "Soccer with rocket-powered cars. Players fly, boost, and spin to hit a giant ball into a goal. Aerial mechanics are the highlight.",
    "r6-siege":      "Tactical 5v5 FPS with operator gadgets. Attackers breach a building, defenders fortify it. One life per round, heavy destruction mechanics.",
}

_GAME_PLAYS = {
    "valorant":      "ace, 4k, 3k, clutch, 1v2, 1v3, 1v4, 1v5, knife kill, operator flick, Sheriff ace, spike defuse clutch, retake, ability kill, util kill",
    "marvel-rivals": "team wipe, ultimate, clutch, 1v5, 1v6, multi-kill, POTG, MVP, combo, flank, hero outplay, ability combo, ult wipe",
    "the-finals":    "squad wipe, cashout steal, multi-kill, clutch, 1v2, 1v3, insane shot, environmental kill, gadget play, building destruction, comeback, cashout defend",
    "apex-legends":  "squad wipe, 20-kill game, 3k damage, 4k damage, 1v3 clutch, final circle win, champion squad, revive clutch, 1v2, 1v3, no-scope, wingman shot",
    "rocket-league": "aerial goal, ceiling shot, musty flick, flip reset, double tap, overtime winner, insane save, 360 shot, air dribble, redirect",
    "r6-siege":      "ace, 4k, 3k, clutch, 1v2, 1v3, 1v4, 1v5, drone play, wallbang, operator ability play, defuse clutch, retake, through wall kill",
}


def select_clips_ai(candidates: list[dict], n: int, game_name: str = "gaming", game_slug: str = "") -> list[dict]:
    n = min(n, len(candidates))  # ne pas demander plus que disponible
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

    priority_plays = _GAME_PLAYS.get(game_slug, "ace, clutch, outplay, insane play, highlight")
    game_context   = _GAME_CONTEXT.get(game_slug, "")

    prompt = f"""You are selecting clips for a {game_name} YouTube highlights channel. Your ONLY job is to find EXPLICIT IN-GAME PLAYS.

Game context: {game_context}

TARGET plays for {game_name} (pick these first):
{priority_plays}

A clip PASSES ONLY if its title unambiguously names a specific in-game action:
- Kill count: ace, 4k, 3k, 2k, 1v2, 1v3, 1v4, 1v5, clutch, collateral, triple kill, quad kill, penta, squad wipe
- Mechanics: flick, spray, wallbang, no-scope, headshot, aerial, ceiling shot, defuse, retake, outplay, comeback, prefire
- {game_name} specifics: {priority_plays}
- Qualifiers are OK: "almost ace", "worst 4k ever", "insane clutch", "how did I hit that"

A clip FAILS — REJECT immediately — if ANY of these apply:
- Vague or emotional: "bang bang", "oh my god", "sorry mate", "he's alive", "not like this", "insane", "crazy" ALONE with no play described
- Sound/onomatopoeia with no action: "boom", "bang", "woah", "ahhh"
- Object/item with no action: "une grenade", "the tea bag", "this gun", "my knife"
- No play described: song names, lore words, player emotions, life updates, reactions
- Training/tutorial: "aim training", "how to", "guide", "settings", "warmup"
- Equipment/tech: "mouse problem", "lag", "fps drop", "my setup"
- Rank ceremony: "rank up", "promotion game", "rank reveal"
- Edit/montage: "edit", "montage", "amv", "#edit"
- Name alone: character name, operator name, streamer name with no action

RULE: return FEWER than {n} if not enough clips qualify. NEVER pick a FAIL clip to fill the count. An empty result [] is better than bad clips.

Candidates:
{candidate_block}

Respond with ONLY a JSON array of indices (integers), e.g. [0, 3, 7].
Return [] if truly none qualify. No explanation."""

    retries = [30, 60, 120]
    last_error = None
    for attempt in range(len(retries) + 1):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            log.debug(f"AI response: {raw}")
            match = re.search(r"\[.*?\]", raw, re.DOTALL)
            if not match:
                raise ValueError(f"No JSON array found in response: {raw[:100]!r}")
            indices = json.loads(match.group())
            if not isinstance(indices, list):
                raise ValueError("not a list")
            indices = [int(x) for x in indices if 0 <= int(x) < len(candidates)]
            selected = [candidates[i] for i in indices[:n]]
            log.info(f"AI selected {len(selected)}/{len(candidates)} clips")
            if not selected:
                log.error(f"AI returned 0 clips. Raw response: {raw[:300]!r}")
                log.error(f"Candidates titles: {[c['title'] for c in candidates]}")
                raise NoClipsSelectedError(f"AI selected 0 clips out of {len(candidates)} candidates")
            return selected
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < len(retries):
                wait = retries[attempt]
                log.warning(f"API overloaded (529), retry dans {wait}s... (tentative {attempt + 1}/{len(retries)})")
                time.sleep(wait)
                last_error = e
            else:
                last_error = e
                break
        except Exception as e:
            last_error = e
            break

    log.warning(f"AI selection failed ({last_error}), falling back to top-{n} by velocity")
    return candidates[:n]
