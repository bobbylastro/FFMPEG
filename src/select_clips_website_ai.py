"""
Sélection IA des clips pour le site web (style TikTok).
Critères larges : pas uniquement des plays, mais tout contenu engageant.
"""
import json
import logging
import re
import time

import anthropic

from config.settings import ANTHROPIC_API_KEY

log = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"

_GAME_CONTEXT = {
    "valorant":          "Tactical 5v5 FPS with agents and abilities. Teams attack/defend a bomb site.",
    "apex-legends":      "Battle royale FPS with squads of 3. High movement, unique character abilities.",
    "marvel-rivals":     "6v6 hero shooter with Marvel characters. Powerful ultimates and team combos.",
    "the-finals":        "3-team FPS with massive building destruction. Cashout-based objective.",
    "rocket-league":     "Soccer with rocket-powered flying cars. Aerial mechanics are the highlight.",
    "rainbow-six-siege": "Tactical 5v5 FPS with operator gadgets and building destruction.",
    "league-of-legends": "5v5 MOBA with champions and abilities. Strategic team fights and objectives.",
    "cs2":               "Tactical 5v5 FPS (Counter-Strike 2). Bomb plant/defuse, precise gunplay.",
    "rust":              "Open-world survival game. PvP raids, base building, resource gathering.",
    "gta-v":             "Open-world crime game. Freemode PvP, heists, stunts, chaos. GTA RP (roleplay servers) counts as gameplay — funny RP moments, unusual challenges, chaotic interactions are all valid.",
    "minecraft":         "Sandbox survival/creative game. Builds, redstone, PvP, speedruns.",
    "overwatch":         "6v6 hero shooter with diverse characters and team-based objectives.",
    "arc-raiders":       "Co-op extraction shooter. Teams fight AI and other players for loot.",
    "tft":               "Auto-battler strategy game (Teamfight Tactics). Unit placement and synergies.",
}


def select_website_clips(candidates: list[dict], n: int, game_slug: str = "") -> list[dict]:
    """Demande à Claude de sélectionner n clips engageants pour un site style TikTok."""
    if not candidates:
        return []

    n = min(n, len(candidates))
    game_context = _GAME_CONTEXT.get(game_slug, "")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    lines = []
    for i, c in enumerate(candidates):
        lines.append(
            f"{i}: title=\"{c['title']}\" | broadcaster={c['broadcaster_name']} "
            f"| {int(c['duration'])}s | {c['view_count']} views"
        )
    candidate_block = "\n".join(lines)

    prompt = f"""You are curating clips for a TikTok-style gaming website. Select the most engaging clips a viewer would want to watch.

Game: {game_slug} — {game_context}

ACCEPT a clip if its title suggests ANY of these:
- Impressive plays: kills, clutches, outplays, insane shots, combos, big moments
- Funny/unexpected: fails, trolling, unexpected outcomes, wild situations, unusual challenges
- Remarkable feats: records, unusual achievements, creative plays, anything chaotic or memorable
- Engaging moments: comeback, revenge, last-second action, underdog situation
- Any title that mentions a champion/character/weapon/ability alongside a hint of action

REJECT a clip ONLY if it clearly fits one of these:
- Gibberish: only symbols/emojis, random letters, keyboard smash (e.g. "xdddddd", "yeps", "enty", "jj")
- Purely technical/educational: settings guide, tutorial, warmup, aim training
- Non-gameplay real-world content: setup tour, hardware review, IRL-only situation
- Bare number + noun with no implied action (e.g. "113 knife", "4k", "round 5") — a clear achievement like "1v5 ace" is fine
- Player/streamer names + social verb only, no gameplay action described (e.g. "X goes off on Y", "X vs Y", "argument between X and Y") — social drama without gameplay
- Pure filler reaction alone: "lol", "omg", "nice", "good vibes", "wow", "yep" with no game reference

When in doubt and any game action or game-specific content is implied: ACCEPT.
Aim to return exactly {n} clips. Return fewer only if genuinely fewer than {n} qualify.

Candidates:
{candidate_block}

Respond with ONLY a JSON array of indices, e.g. [0, 3, 7]. No explanation."""

    retries = [30, 60]
    for attempt in range(len(retries) + 1):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            match = re.search(r"\[.*?\]", raw, re.DOTALL)
            if not match:
                raise ValueError(f"No JSON array in response: {raw[:100]!r}")
            indices = json.loads(match.group())
            indices = [int(x) for x in indices if 0 <= int(x) < len(candidates)]
            selected = [candidates[i] for i in indices[:n]]
            log.info(f"  [{game_slug}] IA sélectionne {len(selected)}/{len(candidates)} clips")
            return selected
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < len(retries):
                time.sleep(retries[attempt])
            else:
                break
        except Exception as e:
            log.warning(f"  [{game_slug}] AI selection error: {e}")
            break

    # Fallback : top-n par vélocité
    log.warning(f"  [{game_slug}] Fallback top-{n} par vélocité")
    return candidates[:n]
