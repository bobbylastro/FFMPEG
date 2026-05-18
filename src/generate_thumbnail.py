import json
import logging
import os
import subprocess

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

FONT_BOLD = "/usr/share/fonts/opentype/bebas-neue/BebasNeue-Bold.otf"
FONT_REG  = "/usr/share/fonts/opentype/bebas-neue/BebasNeue-Regular.otf"

COUNTER_PATH = "data/episode_counter.json"
OUTPUT_DIR   = "output/thumbnails"
THUMB_W, THUMB_H = 1280, 720

# ---------------------------------------------------------------------------
# Thèmes par jeu : primary (couleur principale), secondary (texte principal),
# overlay (fond sombre RGBA), label (texte sous primary)
# ---------------------------------------------------------------------------
GAME_THEMES = {
    "valorant": {
        "primary":   (255, 70,  85),        # #FF4655 — rouge Valorant
        "secondary": (255, 248, 240),        # blanc chaud
        "overlay":   (10,  15,  25,  100),
    },
    "counter-strike-2": {
        "primary":   (240, 165,  0),         # #F0A500 — or CS2
        "secondary": (255, 255, 255),
        "overlay":   (10,  10,  10,  110),
    },
    "league-of-legends": {
        "primary":   (200, 155,  60),        # #C89B3C — or LoL
        "secondary": (255, 248, 220),        # crème
        "overlay":   (5,   5,   30,  115),   # bleu nuit
    },
    "apex-legends": {
        "primary":   (252,  68,  34),        # #FC4422 — rouge-orange Apex
        "secondary": (255, 255, 255),
        "overlay":   (10,   5,   5,  110),
    },
    "rocket-league": {
        "primary":   (59,  173, 248),        # #3BADF8 — bleu Rocket League
        "secondary": (255, 255, 255),
        "overlay":   (5,   10,  30,  105),
    },
}

_FALLBACK_THEME = {
    "primary":   (255, 200,  50),
    "secondary": (255, 255, 255),
    "overlay":   (10,  10,  10,  110),
}


def _get_theme(game: str) -> dict:
    slug = game.lower().replace(" ", "-").replace(":", "").replace(".", "")
    return GAME_THEMES.get(slug, _FALLBACK_THEME)


def bump_episode(game: str) -> int:
    """Incrémente et retourne le numéro d'épisode. À appeler une seule fois par run."""
    return _get_and_bump_episode(game)


def _get_and_bump_episode(game: str) -> int:
    data = {}
    if os.path.exists(COUNTER_PATH):
        with open(COUNTER_PATH) as f:
            data = json.load(f)
    n = data.get(game, 0) + 1
    data[game] = n
    with open(COUNTER_PATH, "w") as f:
        json.dump(data, f, indent=2)
    return n


def _extract_frame(video_path: str, output_png: str) -> None:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path],
        capture_output=True,
    )
    duration = float(json.loads(r.stdout)["format"]["duration"])
    t = duration * 0.5
    subprocess.run([
        "ffmpeg", "-y", "-ss", str(t), "-i", video_path,
        "-frames:v", "1", "-q:v", "2", output_png,
    ], capture_output=True, check=True)


def _draw_centered(draw: ImageDraw, y: int, text: str, font: ImageFont,
                   fill, shadow_offset: int = 4) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (THUMB_W - w) // 2
    shadow = (0, 0, 0, 180)
    draw.text((x + shadow_offset, y + shadow_offset), text, font=font,
              fill=(*shadow[:3], shadow[3]))
    draw.text((x, y), text, font=font, fill=fill)
    return h


def generate_thumbnail(clips: list[dict], game: str, episode: int = None) -> str:
    """
    clips   : liste des clips téléchargés (local_path + view_count).
    episode : numéro pré-calculé (évite un double bump si déjà incrémenté).
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    theme   = _get_theme(game)
    episode = episode if episode is not None else _get_and_bump_episode(game)

    best      = max(clips, key=lambda c: c.get("view_count", 0))
    frame_png = f"/tmp/thumb_frame_{episode}.png"
    _extract_frame(best["local_path"], frame_png)

    img = Image.open(frame_png).convert("RGB")
    img = img.resize((THUMB_W, THUMB_H), Image.LANCZOS)

    overlay = Image.new("RGBA", (THUMB_W, THUMB_H), theme["overlay"])
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(img)

    font_game  = ImageFont.truetype(FONT_REG,  72)
    font_title = ImageFont.truetype(FONT_BOLD, 200)
    font_ep    = ImageFont.truetype(FONT_BOLD, 130)

    game_upper = game.upper()
    ep_text    = f"#{episode}"

    g_bbox  = draw.textbbox((0, 0), game_upper, font=font_game)
    g_w     = g_bbox[2] - g_bbox[0]
    g_h     = g_bbox[3] - g_bbox[1]
    t_bbox  = draw.textbbox((0, 0), "MOMENTS", font=font_title)
    t_h     = t_bbox[3] - t_bbox[1]
    ep_bbox = draw.textbbox((0, 0), ep_text, font=font_ep)
    ep_h    = ep_bbox[3] - ep_bbox[1]

    LINE_H   = 5
    GAP_LINE = 12
    GAP_1    = 18
    GAP_2    = 10

    total_h = g_h + GAP_LINE + LINE_H + GAP_1 + t_h + GAP_2 + ep_h
    start_y = (THUMB_H - total_h) // 2

    # Nom du jeu
    g_y = start_y
    _draw_centered(draw, g_y, game_upper, font_game, theme["primary"], shadow_offset=3)

    # Trait couleur primaire
    line_y = g_y + g_h + GAP_LINE
    line_w = min(g_w, 240)
    draw.rectangle(
        [((THUMB_W - line_w) // 2, line_y), ((THUMB_W + line_w) // 2, line_y + LINE_H)],
        fill=theme["primary"],
    )

    # MOMENTS
    t_y = line_y + LINE_H + GAP_1
    _draw_centered(draw, t_y, "MOMENTS", font_title, theme["secondary"])

    # #XX
    ep_y = t_y + t_h + GAP_2
    _draw_centered(draw, ep_y, ep_text, font_ep, theme["primary"])

    slug     = game.lower().replace(" ", "_").replace(":", "").replace(".", "")
    out_path = os.path.join(OUTPUT_DIR, f"{slug}_ep{episode:03d}.jpg")
    img.save(out_path, "JPEG", quality=95)
    os.remove(frame_png)

    log.info(f"Thumbnail → {out_path}  (clip: {best.get('title', '')[:40]})")
    return out_path
