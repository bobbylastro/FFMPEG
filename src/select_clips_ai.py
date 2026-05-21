import json
import logging
import re

import anthropic

from config.settings import ANTHROPIC_API_KEY

log = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"

_GAME_PLAYS = {
    "valorant":          "ace, 4k, 3k, clutch, 1v2-5, knife kill, operator flick, Sheriff ace, spike defuse clutch, retake",
    "counter-strike-2":  "ace, 4k, 3k, clutch, 1v2-5, AWP no-scope, deagle headshot, wallbang, collateral, knife kill",
    "league-of-legends": "pentakill, quadrakill, baron steal, dragon steal, outplay, 1v9 carry, insane comeback, nexus destroy",
    "apex-legends":      "squad wipe, 20-kill game, 3k damage, 1v3 clutch, final circle win, champion squad, revive clutch",
    "rocket-league":     "aerial goal, ceiling shot, musty flick, flip reset, double tap, overtime winner, insane save",
    "r6-siege":          "ace, 4k, 3k, clutch, 1v2-5, drone play, wallbang, operator ability play, defuse clutch, retake",
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

    prompt = f"""You are curating a {game_name} highlights compilation for YouTube. Pick the best {n} clips a general audience will enjoy.

PRIORITY — strongly prefer clips whose title mentions these {game_name}-specific plays:
{priority_plays}

A clip PASSES only if its title contains an explicit in-game ACTION or PLAY — not just a game reference:
- Kill count or clutch word: ace, 4k, 3k, 2k, 1v2, 1v3, 1v4, 1v5, clutch, collateral, triple, quad, penta, kill, frag, DBNO, down
- Mechanic or action: flick, spray, peek, flank, snipe, wallbang, jumpshot, headshot, breach, rush, rotate, anchor, drone, defuse, plant
- Outcome: retake, outplay, comeback, overtime, win, 1vX, carried, saved
- Champion/agent/hero + action (e.g. "Yasuo pentakill", "Jett ace", "Wraith 1v3") — the character name alone is NOT enough
- Any pro player name known in the {game_name} competitive scene + an action term
- Qualifier + gaming term still PASSES: "almost ace", "worst 4k ever", "nearly clutched", "how lucky was that"

A clip FAILS if ANY of the following is true:
- Title is a song, artist, or lyric: "heavenly", "Heart Attack", "lil yachty", "Billie Jean", "bye bye", "worry"
- Title is a lore location, region, or world name with no action: "Shurima", "The Void", "Demacia", "Noxus", "Runeterra", "Piltover"
- Title sounds like a cinematic edit or music video: atmospheric, poetic, or lore-flavored language without a play description
- Explicit edit/montage label: "edit", "montage", "edit.mp4", "my edit", "first 2026 edit", "#edit", "amv"
- Completely vague with no game context: "long time no see guys", "yall im so back", "We r who we r"
- Just a champion/agent/hero name with no action (e.g. "Yasuo", "Jinx", "Ahri" alone)
- Training, practice or aim routine: "tutorial", "aim training", "practice", "how to", "guide", "settings", "sensitivity", "crosshair", "warmup", "routine", "tips", "tricks"
- Technical/equipment complaint or real-life issue with no play: "mouse problem", "lag", "fps drop", "my setup", "pc issue", "stuttering", "input delay", "my hands", "my keyboard"
- Rank promotion/reveal with no action: "rank promotion", "rank up", "new rank", "ranked up", "promotion game", "rank reveal", "hitting plat", "hitting diamond", "hitting gold"
- Random/empty/filename: "t", "g", "clip.mp4"

IMPORTANT: return FEWER than {n} clips rather than lowering the bar. Quality over quantity — never pick a FAIL clip just to fill the count.

Candidates:
{candidate_block}

Respond with ONLY a JSON array of indices (integers), e.g. [0, 3, 7].
Return [] if truly none qualify. No explanation."""

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        log.debug(f"AI response: {raw}")
        # Extraire le tableau JSON même si le modèle ajoute du texte autour
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON array found in response: {raw[:100]!r}")
        indices = json.loads(match.group())
        if not isinstance(indices, list):
            raise ValueError("not a list")
        indices = [int(x) for x in indices if 0 <= int(x) < len(candidates)]
        selected = [candidates[i] for i in indices[:n]]
        log.info(f"AI selected {len(selected)}/{len(candidates)} clips")
        return selected
    except Exception as e:
        log.warning(f"AI selection failed ({e}), falling back to top-{n} by velocity")
        return candidates[:n]
