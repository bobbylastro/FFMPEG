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

INCLUDE clips whose title suggests:
- A spectacular or skillful play (mechanical outplay, clutch moment, rare achievement)
- An exciting or unexpected outcome
- Hype adjectives paired with clear gameplay context: insane/crazy/sick/impossible/unreal + action

EXCLUDE clips whose title clearly signals no gameplay value:
- Pure lobby, menu, or loading screen content
- Streamer reaction with no play described
- Tournament pre-show, interview, or announcement
- Completely generic with zero context ("clip", "wow", "lol", standalone "wtf")

When ambiguous, INCLUDE — viewers will judge.
Try to return exactly {n} clips. If the pool has fewer, return as many as possible.

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
