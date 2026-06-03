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
        velocity = round(c.get("_velocity", 0), 1)
        lines.append(
            f"{i}: title=\"{c['title']}\" | broadcaster={c['broadcaster_name']} "
            f"| {int(c['duration'])}s | velocity={velocity} views/day"
        )
    candidate_block = "\n".join(lines)

    prompt = f"""You are a strict quality filter for a TikTok-style gaming clip website. Your job is to REJECT bad clips, not to find good ones.

Game: {game_slug} — {game_context}

For each clip, ask yourself: "Is there ANY reason to reject this?" If yes — reject it. Only keep a clip if you find NO reason to reject it AND its title clearly implies genuine in-game action.

REJECT immediately if the title:
- Is gibberish, symbols/emojis only, random letters, or keyboard smash
- Suggests a tutorial, guide, settings, warmup, or aim training
- Describes real-world/IRL content: people talking, facecam, physical reactions, rank-up screen
- Is a rank milestone with no gameplay ("new rank", "hit diamond", "peak unlocked")
- Is a joke, meme, or humorous comment in a non-English language
- Involves streamer drama, arguments, callouts, shoutouts, or social reactions
- Is a filler reaction with no game-specific content ("lol", "omg", "nice", "wow")
- Is vague with no implied action: bare number + noun, player name only, generic exclamation
- Is a biographical or trivia question about a person ("Is [Name]'s real name X?", "Who is [Name]?")
- Analyzes or explains rather than describes action ("Why X is broken", "How X works", "The truth about X")
- Uses underscores as word separators ("Who_s_your_friend", "best_play_ever")
- Is ambiguous — if you cannot tell from the title alone whether it's gameplay, REJECT it

Only KEEP a clip whose title unambiguously describes:
- A gameplay highlight: kills, clutches, outplays, insane shots, combos, impressive feats
- A funny/unexpected IN-GAME moment in English
- A remarkable in-game achievement: record, comeback, last-second action

Return exactly {n} clips if that many qualify. Return fewer if not enough pass. Never lower your bar to hit the target count.

Candidates:
{candidate_block}

Respond with ONLY a JSON array of accepted indices, e.g. [0, 3, 7]. No explanation."""

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
