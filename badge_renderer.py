"""badge_renderer.py — render channel badge PNGs. Pillow only, pure module.

Badges exist because (a) TMDB has no trustworthy logo for concept channels
(genre/decade/mood/theme/...), and (b) Plex hides a channel's text name once
any icon is set — so the badge must CARRY the name. Every badge: colored
rounded tile + white glyph + the channel name stamped in Anton caps.

Art inputs live in badge_assets/ (committed; regenerate via
scripts/make_badge_assets.py). Must stay in the Dockerfile COPY lines.
"""

import io
import os

from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "badge_assets")
FONT_PATH = os.path.join(ASSETS_DIR, "font", "Anton-Regular.ttf")

CANVAS = 512
GLYPH_SIZE = 176
TEXT_MAX_WIDTH = 440

GENRE_COLORS = {
    "action": "#c0392b", "adventure": "#ef6c00", "animation": "#00acc1",
    "comedy": "#f59f00", "crime": "#37474f", "documentary": "#00695c",
    "drama": "#34495e", "family": "#43a047", "fantasy": "#6a1b9a",
    "history": "#6d4c41", "horror": "#8b0000", "music": "#d81b60",
    "musical": "#d81b60", "mystery": "#4527a0", "romance": "#c2185b",
    "sci-fi": "#5e35b1", "science fiction": "#5e35b1", "sport": "#2e7d32",
    "thriller": "#455a64", "war": "#5d4037", "western": "#8d6e63",
    "film-noir": "#212121", "noir": "#212121",
}
KIND_COLORS = {
    "marathon": "#1565c0", "network": "#283593", "franchise": "#4e342e",
    "studio": "#006064", "director": "#424242", "actor": "#827717",
    "country": "#00838f", "mood": "#ad1457", "style": "#7b1fa2",
    "theme": "#00897b", "programming_block": "#3949ab",
}
DEFAULT_COLOR = "#37474f"

GENRE_GLYPHS = {
    "action": "bomb", "adventure": "compass", "animation": "palette",
    "comedy": "mood-smile", "crime": "fingerprint", "documentary": "camera",
    "drama": "masks-theater", "family": "users-group", "fantasy": "wand",
    "history": "hourglass", "horror": "skull", "music": "music",
    "musical": "music", "mystery": "question-mark", "romance": "heart",
    "sci-fi": "rocket", "science fiction": "rocket", "sport": "ball-football",
    "thriller": "eye", "war": "swords", "western": "cactus",
    "film-noir": "moon", "noir": "moon",
}
KIND_GLYPHS = {
    "marathon": "device-tv", "tv_genre": "device-tv",
    "tv_movie_mix": "device-tv-old", "network": "broadcast",
    "franchise": "stack-2", "studio": "building", "director": "movie",
    "actor": "star", "country": "world", "mood": "mood-smile",
    "style": "brush", "theme": "sparkles", "programming_block": "layout-grid",
    "genre": "movie", "genre_decade": "calendar", "blend": "color-swatch",
}
DEFAULT_GLYPH = "antenna"


def _norm(s):
    return (s or "").strip().lower()


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _darken(rgb, factor=0.65):
    return tuple(int(c * factor) for c in rgb)


def color_for(kind=None, genre=None):
    return (GENRE_COLORS.get(_norm(genre))
            or KIND_COLORS.get(_norm(kind))
            or DEFAULT_COLOR)


def glyph_path_for(kind=None, genre=None):
    name = (GENRE_GLYPHS.get(_norm(genre))
            or KIND_GLYPHS.get(_norm(kind))
            or DEFAULT_GLYPH)
    return os.path.join(ASSETS_DIR, "glyphs", f"{name}.png")


def _wrap(draw, text, font, max_width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if not cur or draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_badge(name, kind=None, genre=None):
    """Render a 512x512 badge PNG for a channel. Returns PNG bytes."""
    rgb = _hex_to_rgb(color_for(kind, genre))
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([8, 8, CANVAS - 8, CANVAS - 8], radius=48,
                           fill=rgb + (255,),
                           outline=_darken(rgb) + (255,), width=6)

    glyph_file = glyph_path_for(kind, genre)
    if os.path.exists(glyph_file):
        glyph = Image.open(glyph_file).convert("RGBA").resize(
            (GLYPH_SIZE, GLYPH_SIZE), Image.LANCZOS)
        img.alpha_composite(glyph, ((CANVAS - GLYPH_SIZE) // 2, 64))

    text = (name or "").upper()
    size = 60
    font = ImageFont.truetype(FONT_PATH, size)
    lines = _wrap(draw, text, font, TEXT_MAX_WIDTH)
    while size > 28 and (len(lines) > 3 or any(
            draw.textlength(l, font=font) > TEXT_MAX_WIDTH for l in lines)):
        size -= 4
        font = ImageFont.truetype(FONT_PATH, size)
        lines = _wrap(draw, text, font, TEXT_MAX_WIDTH)

    line_height = size + 10
    block_height = line_height * len(lines)
    y = 268 + max(0, (200 - block_height) // 2)
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((CANVAS - w) / 2, y), line, font=font,
                  fill=(255, 255, 255, 255))
        y += line_height

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
