"""
Génère une miniature YouTube pour les vidéos GTA 6 pre-launch.
  - Background : frame cinématique extraite du trailer
  - Logo       : assets/Grand_Theft_Auto_VI_logo.svg (WebP RGBA)
  - Titre      : accroche courte générée par l'IA (5-7 mots max)
  - Style      : Vice City — néon rose/teal, gradient sombre en bas
"""
import logging
import os
import subprocess
import tempfile
import textwrap

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

log = logging.getLogger(__name__)

_ASSETS    = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")
FONT_TITLE = os.path.abspath(os.path.join(_ASSETS, "RussoOne-Regular.ttf"))
FONT_SUB   = os.path.abspath(os.path.join(_ASSETS, "Montserrat-ExtraBold.ttf"))
LOGO_PATH  = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "Grand_Theft_Auto_VI_logo.svg"))

TRAILERS_DIR = os.path.abspath("assets/gta6_trailers")
OUTPUT_DIR   = "output/gta6"
THUMB_W, THUMB_H = 1280, 720

NEON_PINK  = (255,  60, 120)
NEON_TEAL  = (  0, 210, 210)
WHITE      = (255, 255, 255)
BLACK      = (  0,   0,   0)


def _get_duration(path: str) -> float:
    import json
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def _frame_sharpness(img: Image.Image) -> float:
    return sum(ImageStat.Stat(img).stddev)


def _best_trailer_frame(trailer_path: str, n: int = 12) -> Image.Image:
    duration = _get_duration(trailer_path)
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


def _auto_font(draw: ImageDraw.Draw, text: str, font_path: str,
               start_size: int, max_width: int) -> ImageFont.FreeTypeFont:
    size = start_size
    while size > 28:
        font = ImageFont.truetype(font_path, size)
        bb = draw.textbbox((0, 0), text, font=font)
        if (bb[2] - bb[0]) <= max_width:
            return font
        size -= 4
    return ImageFont.truetype(font_path, size)


def _draw_outlined(draw: ImageDraw.Draw, x: int, y: int, text: str,
                   font: ImageFont.FreeTypeFont, fill, outline, outline_w: int = 5) -> None:
    for dx in range(-outline_w, outline_w + 1):
        for dy in range(-outline_w, outline_w + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline)
    draw.text((x, y), text, font=font, fill=fill)


def _add_gradient_overlay(img: Image.Image) -> Image.Image:
    """Dégradé sombre en bas (pour la lisibilité du titre) et légère teinte en haut."""
    overlay = Image.new("RGBA", (THUMB_W, THUMB_H), (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    # Gradient bas : de transparent à noir opaque sur la moitié basse
    grad_start = THUMB_H // 2
    for y in range(grad_start, THUMB_H):
        alpha = int(200 * (y - grad_start) / (THUMB_H - grad_start))
        draw.line([(0, y), (THUMB_W, y)], fill=(0, 0, 0, alpha))

    # Légère teinte uniforme pour faire ressortir le logo
    draw.rectangle([(0, 0), (THUMB_W, THUMB_H)], fill=(0, 0, 0, 55))

    return Image.alpha_composite(img.convert("RGBA"), overlay)


def _wrap_title(title: str, draw: ImageDraw.Draw, font: ImageFont.FreeTypeFont,
                max_w: int) -> list[str]:
    """Découpe le titre en 1 ou 2 lignes selon la largeur dispo."""
    words = title.split()
    lines: list[str] = []
    current = ""
    for w in words:
        test = (current + " " + w).strip()
        bb = draw.textbbox((0, 0), test, font=font)
        if bb[2] - bb[0] > max_w and current:
            lines.append(current)
            current = w
        else:
            current = test
    if current:
        lines.append(current)
    return lines[:2]


def generate_thumbnail_gta6(title_line: str, date_str: str,
                             trailer_index: int = 0) -> str:
    import glob

    trailers = sorted(
        glob.glob(os.path.join(TRAILERS_DIR, "*.mp4"))
        + glob.glob(os.path.join(TRAILERS_DIR, "*.mov"))
    )
    if not trailers:
        raise FileNotFoundError(f"Aucun trailer dans {TRAILERS_DIR}")
    trailer = trailers[trailer_index % len(trailers)]

    # 1. Background cinématique
    bg = _best_trailer_frame(trailer)
    bg = bg.resize((THUMB_W, THUMB_H), Image.LANCZOS)

    # 2. Gradient overlay
    img = _add_gradient_overlay(bg).convert("RGB")

    # 3. Logo GTA VI (WebP RGBA)
    logo_img = Image.open(LOGO_PATH).convert("RGBA")
    logo_target_w = 520
    logo_ratio    = logo_target_w / logo_img.width
    logo_h        = int(logo_img.height * logo_ratio)
    logo_img      = logo_img.resize((logo_target_w, logo_h), Image.LANCZOS)

    # Centrer le logo — haut de l'image avec un peu d'espace
    logo_x = (THUMB_W - logo_target_w) // 2
    logo_y = 28
    img.paste(logo_img, (logo_x, logo_y), logo_img)

    # 4. Titre principal — Russo One, blanc éclatant avec halo orange
    draw     = ImageDraw.Draw(img)
    title_up = title_line.upper()
    MAX_W    = THUMB_W - 80

    font_hl = _auto_font(draw, title_up, FONT_TITLE, 148, MAX_W)
    lines   = _wrap_title(title_up, draw, font_hl, MAX_W)

    line_h         = int(font_hl.getbbox("A")[3] * 1.15) + 4
    total_h        = len(lines) * line_h
    title_zone_top = logo_y + logo_h + 20
    title_y_start  = title_zone_top + max(10, (THUMB_H - 60 - title_zone_top - total_h) // 2)

    for i, line in enumerate(lines):
        bb = draw.textbbox((0, 0), line, font=font_hl)
        lw = bb[2] - bb[0]
        lx = (THUMB_W - lw) // 2
        ly = title_y_start + i * line_h

        # Halo orange large (couche 1 — très diffus)
        for radius, color, alpha in [
            (28, (255, 100,  0), 120),
            (14, (255, 180, 30), 160),
            ( 6, (255, 220, 80), 200),
        ]:
            glow = Image.new("RGBA", (THUMB_W, THUMB_H), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow)
            gd.text((lx, ly), line, font=font_hl, fill=(*color, alpha))
            glow = glow.filter(ImageFilter.GaussianBlur(radius=radius))
            img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
            draw = ImageDraw.Draw(img)

        # Ombre portée (profondeur)
        _draw_outlined(draw, lx + 3, ly + 4, line, font_hl,
                       fill=(0, 0, 0, 0), outline=(0, 0, 0), outline_w=0)
        draw.text((lx + 3, ly + 4), line, font=font_hl, fill=(20, 10, 0))

        # Texte blanc pur (core)
        _draw_outlined(draw, lx, ly, line, font_hl,
                       fill=WHITE, outline=(255, 140, 0), outline_w=2)

    # 5. Badge en bas à gauche
    font_badge = ImageFont.truetype(FONT_SUB, 34)
    badge_text = "GTA VI THEORY"
    bb_b = draw.textbbox((0, 0), badge_text, font=font_badge)
    bw, bh = bb_b[2] - bb_b[0], bb_b[3] - bb_b[1]
    pad_x, pad_y = 20, 9
    bx = 44
    by = THUMB_H - bh - 2 * pad_y - 36
    draw.rounded_rectangle(
        [(bx, by), (bx + bw + 2 * pad_x, by + bh + 2 * pad_y)],
        radius=8, fill=NEON_PINK,
    )
    draw.text((bx + pad_x, by + pad_y), badge_text, font=font_badge, fill=WHITE)

    # 6. Trait néon teal sous le logo
    sep_y = logo_y + logo_h + 6
    draw.rectangle([(logo_x + 30, sep_y), (logo_x + logo_target_w - 30, sep_y + 3)],
                   fill=NEON_TEAL)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"{date_str}_thumbnail.jpg")
    img.save(out_path, "JPEG", quality=95)
    log.info(f"Miniature GTA 6 → {out_path}")
    return out_path
