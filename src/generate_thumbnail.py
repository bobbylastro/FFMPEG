import json
import logging
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont, ImageStat

log = logging.getLogger(__name__)

_ASSETS    = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")
FONT_TITLE = os.path.abspath(os.path.join(_ASSETS, "RussoOne-Regular.ttf"))
FONT_GAME  = os.path.abspath(os.path.join(_ASSETS, "Montserrat-ExtraBold.ttf"))

COUNTER_DIR  = "data/episode_counter"
OUTPUT_DIR   = "output/thumbnails"
THUMB_W, THUMB_H = 1280, 720

# Phrases d'accroche universelles — vraies pour toute compilation
HEADLINES = [
    "BEST MOMENTS",
    "INSANE PLAYS",
    "HIGHLIGHT REEL",
    "TOP PLAYS",
    "CRACKED PLAYS",
    "MUST WATCH",
    "UNREAL MOMENTS",
    "WEEKLY HIGHLIGHTS",
]

GAME_THEMES = {
    "valorant": {
        "primary":   (255, 70,  85),
        "secondary": (255, 248, 240),
        "overlay":   (10,  15,  25,  130),
    },
    "counter-strike-2": {
        "primary":   (240, 165,  0),
        "secondary": (255, 255, 255),
        "overlay":   (10,  10,  10,  140),
    },
    "league-of-legends": {
        "primary":   (200, 155,  60),
        "secondary": (255, 248, 220),
        "overlay":   (5,   5,   30,  140),
    },
    "apex-legends": {
        "primary":   (252,  68,  34),
        "secondary": (255, 255, 255),
        "overlay":   (10,   5,   5,  130),
    },
    "rocket-league": {
        "primary":   (59,  173, 248),
        "secondary": (255, 255, 255),
        "overlay":   (5,   10,  30,  130),
    },
    "rainbow-six-siege": {
        "primary":   (255, 106,   0),
        "secondary": (255, 255, 255),
        "overlay":   (5,   10,  20,  140),
    },
}
_FALLBACK_THEME = {
    "primary":   (255, 200,  50),
    "secondary": (255, 255, 255),
    "overlay":   (10,  10,  10,  130),
}


def _get_theme(game: str) -> dict:
    slug = game.lower().replace(" ", "-").replace(":", "").replace(".", "")
    return GAME_THEMES.get(slug, _FALLBACK_THEME)


def _get_headline(episode: int) -> str:
    return HEADLINES[(episode - 1) % len(HEADLINES)]


def bump_episode(game: str) -> int:
    return _get_and_bump_episode(game)


def _get_and_bump_episode(game: str) -> int:
    os.makedirs(COUNTER_DIR, exist_ok=True)
    slug = game.lower().replace(" ", "-").replace(":", "").replace(".", "")
    path = os.path.join(COUNTER_DIR, f"{slug}.json")
    n = 0
    if os.path.exists(path):
        with open(path) as f:
            n = json.load(f).get("episode", 0)
    n += 1
    with open(path, "w") as f:
        json.dump({"episode": n}, f)
    return n


def _get_duration(video_path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path],
        capture_output=True,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def _frame_sharpness(img: Image.Image) -> float:
    """Stddev des pixels — frames d'action ont plus de contraste/détail."""
    return sum(ImageStat.Stat(img).stddev)


def _best_frame(video_path: str, n_samples: int = 6) -> Image.Image:
    """Extrait n_samples frames, retourne la plus nette (= moment le plus fort)."""
    duration = _get_duration(video_path)
    # Samplent dans les 75% premiers — la fin d'un clip est souvent vide/kill-cam
    timestamps = [duration * i / (n_samples + 1) * 0.75 for i in range(1, n_samples + 1)]

    best_img, best_score = None, -1.0
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(timestamps):
            out = os.path.join(tmp, f"frame_{i}.png")
            subprocess.run([
                "ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", video_path,
                "-frames:v", "1", "-q:v", "2", out,
            ], capture_output=True)
            if not os.path.exists(out):
                continue
            img   = Image.open(out).convert("RGB")
            score = _frame_sharpness(img)
            if score > best_score:
                best_score, best_img = score, img.copy()

    if best_img is None:
        raise RuntimeError(f"Could not extract any frame from {video_path}")
    return best_img


def _draw_shadowed(draw: ImageDraw, x: int, y: int, text: str, font: ImageFont,
                   fill, shadow_offset: int = 3, shadow_alpha: int = 200) -> None:
    """Texte avec shadow directionnel subtil — plus élégant qu'un outline épais."""
    shadow = (0, 0, 0, shadow_alpha)
    draw.text((x + shadow_offset, y + shadow_offset), text, font=font,
              fill=(*shadow[:3], shadow[3]))
    draw.text((x, y), text, font=font, fill=fill)


def _text_width(draw: ImageDraw, text: str, font: ImageFont) -> int:
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0]


def _auto_font(draw: ImageDraw, text: str, font_path: str,
               start_size: int, max_width: int) -> ImageFont:
    """Réduit la taille jusqu'à ce que le texte tienne dans max_width."""
    size = start_size
    while size > 40:
        font = ImageFont.truetype(font_path, size)
        if _text_width(draw, text, font) <= max_width:
            return font
        size -= 8
    return ImageFont.truetype(font_path, size)


def _draw_centered_shadowed(draw: ImageDraw, y: int, text: str, font: ImageFont,
                             fill, shadow_offset: int = 3, shadow_alpha: int = 200) -> tuple:
    """Retourne (x, rendered_bottom) pour positionner les éléments suivants."""
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    x = (THUMB_W - w) // 2
    _draw_shadowed(draw, x, y, text, font, fill, shadow_offset, shadow_alpha)
    return x, y + bbox[3]   # bottom = y + bbox[3] (tient compte de l'ascender)


def generate_thumbnail(clips: list[dict], game: str, episode: int = None) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    theme   = _get_theme(game)
    episode = episode if episode is not None else _get_and_bump_episode(game)

    # Clip avec le plus de vues → meilleure chance d'avoir un beau visuel
    best = max(clips, key=lambda c: c.get("view_count", 0))
    img  = _best_frame(best["local_path"])
    img  = img.resize((THUMB_W, THUMB_H), Image.LANCZOS)

    # Overlay global pour assombrir légèrement le fond
    overlay = Image.new("RGBA", (THUMB_W, THUMB_H), theme["overlay"])
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(img)

    headline = _get_headline(episode)
    ep_text  = f"#{episode}"

    # Polices — headline auto-sized pour ne jamais dépasser la largeur
    MAX_W     = THUMB_W - 100
    font_game = _auto_font(draw, game.upper(), FONT_TITLE, 100, MAX_W)
    font_hl   = _auto_font(draw, headline,     FONT_TITLE, 150, MAX_W)
    font_ep   = _auto_font(draw, ep_text,      FONT_TITLE, 110, MAX_W)

    LINE_H   = 6
    GAP_LINE = 10
    GAP_1    = 14
    GAP_2    = 8

    # Calcul des hauteurs réelles (bbox[3] inclut l'ascender)
    g_bb  = draw.textbbox((0, 0), game.upper(), font=font_game)
    hl_bb = draw.textbbox((0, 0), headline,     font=font_hl)
    ep_bb = draw.textbbox((0, 0), ep_text,       font=font_ep)
    g_bottom  = g_bb[3]
    hl_bottom = hl_bb[3]
    ep_bottom = ep_bb[3]

    total_h = g_bottom + GAP_LINE + LINE_H + GAP_1 + hl_bottom + GAP_2 + ep_bottom
    start_y = (THUMB_H - total_h) // 2

    # Nom du jeu
    _, g_px_bottom = _draw_centered_shadowed(
        draw, start_y, game.upper(), font_game,
        fill=theme["primary"], shadow_offset=4, shadow_alpha=200,
    )

    # Trait sous le nom du jeu (positionné après les pixels réels)
    line_y = g_px_bottom + GAP_LINE
    line_w = min(g_bb[2] - g_bb[0], 260)
    draw.rectangle(
        [((THUMB_W - line_w) // 2, line_y), ((THUMB_W + line_w) // 2, line_y + LINE_H)],
        fill=theme["primary"],
    )

    # Headline dynamique
    t_y = line_y + LINE_H + GAP_1
    _, hl_px_bottom = _draw_centered_shadowed(
        draw, t_y, headline, font_hl,
        fill=theme["secondary"], shadow_offset=5, shadow_alpha=210,
    )

    # Numéro d'épisode
    ep_y = hl_px_bottom + GAP_2
    _draw_centered_shadowed(
        draw, ep_y, ep_text, font_ep,
        fill=theme["primary"], shadow_offset=4, shadow_alpha=200,
    )

    slug     = game.lower().replace(" ", "_").replace(":", "").replace(".", "")
    out_path = os.path.join(OUTPUT_DIR, f"{slug}_ep{episode:03d}.jpg")
    img.save(out_path, "JPEG", quality=95)

    log.info(f"Thumbnail → {out_path}  [{headline}]  (clip: {best.get('title', '')[:40]})")
    return out_path
