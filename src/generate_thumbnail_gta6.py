"""
Génère une miniature YouTube pour les vidéos GTA 6 pre-launch.
  - Background : frame cinématique extraite du trailer
  - Titre      : accroche courte générée par l'IA (5-7 mots max)
  - Style      : Vice City — néon rose/teal sur fond sombre
"""
import logging
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont, ImageStat

log = logging.getLogger(__name__)

_ASSETS    = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")
FONT_TITLE = os.path.abspath(os.path.join(_ASSETS, "RussoOne-Regular.ttf"))
FONT_SUB   = os.path.abspath(os.path.join(_ASSETS, "Montserrat-ExtraBold.ttf"))

TRAILERS_DIR = os.path.abspath("assets/gta6_trailers")
OUTPUT_DIR   = "output/gta6"
THUMB_W, THUMB_H = 1280, 720

# Palette Vice City / GTA VI
NEON_PINK  = (255,  60, 120)
NEON_TEAL  = (  0, 210, 210)
DARK_BG    = ( 10,   5,  20, 145)   # overlay sombre violacé
WHITE      = (255, 255, 255)


def _get_duration(path: str) -> float:
    import json
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def _frame_sharpness(img: Image.Image) -> float:
    return sum(ImageStat.Stat(img).stddev)


def _best_trailer_frame(trailer_path: str, n: int = 10) -> Image.Image:
    """Extrait la frame la plus nette/contrastée du trailer."""
    duration = _get_duration(trailer_path)
    # Échantillons entre 10% et 85% du trailer (évite intro et générique fin)
    timestamps = [duration * (0.10 + 0.75 * i / (n - 1)) for i in range(n)]

    best_img, best_score = None, -1.0
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(timestamps):
            out = os.path.join(tmp, f"f{i}.png")
            subprocess.run([
                "ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", trailer_path,
                "-frames:v", "1", "-q:v", "2", out,
            ], capture_output=True)
            if not os.path.exists(out):
                continue
            img   = Image.open(out).convert("RGB")
            score = _frame_sharpness(img)
            if score > best_score:
                best_score, best_img = score, img.copy()

    if best_img is None:
        raise RuntimeError(f"Impossible d'extraire une frame de {trailer_path}")
    return best_img


def _auto_font(draw: ImageDraw, text: str, font_path: str,
               start_size: int, max_width: int) -> ImageFont.FreeTypeFont:
    size = start_size
    while size > 32:
        font = ImageFont.truetype(font_path, size)
        bb = draw.textbbox((0, 0), text, font=font)
        if (bb[2] - bb[0]) <= max_width:
            return font
        size -= 6
    return ImageFont.truetype(font_path, size)


def _draw_text_with_outline(draw: ImageDraw, x: int, y: int, text: str,
                             font: ImageFont.FreeTypeFont, fill, outline,
                             outline_w: int = 4) -> None:
    for dx in range(-outline_w, outline_w + 1):
        for dy in range(-outline_w, outline_w + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline)
    draw.text((x, y), text, font=font, fill=fill)


def generate_thumbnail_gta6(title_line: str, date_str: str,
                             trailer_index: int = 0) -> str:
    """
    Génère une miniature 1280×720 pour une vidéo GTA 6.

    title_line : accroche courte (≤ 7 mots), ex. "GTA 6 MAP IS 3X BIGGER?"
    """
    import glob
    trailers = sorted(
        glob.glob(os.path.join(TRAILERS_DIR, "*.mp4"))
        + glob.glob(os.path.join(TRAILERS_DIR, "*.mov"))
    )
    if not trailers:
        raise FileNotFoundError(f"Aucun trailer dans {TRAILERS_DIR}")
    trailer = trailers[trailer_index % len(trailers)]

    # 1. Frame cinématique du trailer
    bg = _best_trailer_frame(trailer)
    bg = bg.resize((THUMB_W, THUMB_H), Image.LANCZOS)

    # 2. Overlay sombre
    overlay = Image.new("RGBA", (THUMB_W, THUMB_H), DARK_BG)
    img = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    MAX_W = THUMB_W - 80

    # 3. "GTA VI" en petit en haut
    sub_text = "GTA VI"
    font_sub = _auto_font(draw, sub_text, FONT_SUB, 60, MAX_W)
    sub_bb   = draw.textbbox((0, 0), sub_text, font=font_sub)
    sub_w    = sub_bb[2] - sub_bb[0]
    sub_x    = (THUMB_W - sub_w) // 2
    sub_y    = 55
    _draw_text_with_outline(draw, sub_x, sub_y, sub_text, font_sub,
                            fill=NEON_TEAL, outline=(0, 0, 0), outline_w=3)

    # Trait sous "GTA VI"
    line_y = sub_y + (sub_bb[3] - sub_bb[1]) + 10
    bar_w  = min(sub_w + 40, 300)
    draw.rectangle(
        [((THUMB_W - bar_w) // 2, line_y), ((THUMB_W + bar_w) // 2, line_y + 5)],
        fill=NEON_PINK,
    )

    # 4. Titre principal (grand, centré, 2 lignes si besoin)
    title_up = title_line.upper()
    font_hl  = _auto_font(draw, title_up, FONT_TITLE, 130, MAX_W)
    hl_bb    = draw.textbbox((0, 0), title_up, font=font_hl)
    hl_w     = hl_bb[2] - hl_bb[0]
    hl_h     = hl_bb[3] - hl_bb[1]
    hl_x     = (THUMB_W - hl_w) // 2
    hl_y     = line_y + 20
    _draw_text_with_outline(draw, hl_x, hl_y, title_up, font_hl,
                            fill=WHITE, outline=(0, 0, 0), outline_w=5)

    # 5. Bandeau "THEORY" ou "NEWS" en bas
    tag_text = "THEORY"
    font_tag = ImageFont.truetype(FONT_SUB, 38)
    tag_bb   = draw.textbbox((0, 0), tag_text, font=font_tag)
    tag_w    = tag_bb[2] - tag_bb[0]
    tag_h    = tag_bb[3] - tag_bb[1]
    pad_x, pad_y = 18, 8
    rect_x = (THUMB_W - tag_w - 2 * pad_x) // 2
    rect_y = THUMB_H - tag_h - 2 * pad_y - 40
    draw.rectangle(
        [(rect_x, rect_y), (rect_x + tag_w + 2 * pad_x, rect_y + tag_h + 2 * pad_y)],
        fill=NEON_PINK,
    )
    draw.text((rect_x + pad_x, rect_y + pad_y), tag_text, font=font_tag, fill=WHITE)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"{date_str}_thumbnail.jpg")
    img.save(out_path, "JPEG", quality=95)
    log.info(f"Miniature GTA 6 → {out_path}")
    return out_path
