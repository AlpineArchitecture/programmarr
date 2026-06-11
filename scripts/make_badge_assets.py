#!/usr/bin/env python3
"""scripts/make_badge_assets.py — (re)generate the committed badge_assets/ dir.

Downloads Tabler icon SVGs (MIT) at a pinned tag, renders each to a white
256x256 PNG, and downloads the Anton font (OFL) + both licenses. The outputs
are COMMITTED — end users never run this; the runtime needs only Pillow.

Dev-only deps:  pip install cairosvg pillow
Usage:          python scripts/make_badge_assets.py
"""

import io
import os
import sys
import urllib.request

try:
    import cairosvg
except ImportError:
    sys.exit("cairosvg required (dev-only): pip install cairosvg")
from PIL import Image

TABLER_TAG = "v3.31.0"
TABLER_SVG = "https://raw.githubusercontent.com/tabler/tabler-icons/{tag}/icons/outline/{name}.svg"
TABLER_LICENSE = "https://raw.githubusercontent.com/tabler/tabler-icons/{tag}/LICENSE"
ANTON_TTF = "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf"
ANTON_OFL = "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/OFL.txt"

# Single source of truth for which glyphs exist. badge_renderer.py's
# GENRE_GLYPHS / KIND_GLYPHS values must be a subset of this list.
GLYPHS = sorted({
    "antenna", "ball-football", "bomb", "broadcast", "brush", "building",
    "cactus", "calendar", "camera", "color-swatch", "compass", "device-tv",
    "device-tv-old", "eye", "fingerprint", "heart", "hourglass",
    "layout-grid", "masks-theater", "mood-smile", "moon", "movie", "music",
    "palette", "question-mark", "rocket", "skull", "sparkles", "stack-2",
    "star", "swords", "users-group", "wand", "world",
})

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "badge_assets")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Programmarr-dev"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def main():
    glyph_dir = os.path.join(OUT, "glyphs")
    font_dir = os.path.join(OUT, "font")
    os.makedirs(glyph_dir, exist_ok=True)
    os.makedirs(font_dir, exist_ok=True)

    missing = []
    for name in GLYPHS:
        url = TABLER_SVG.format(tag=TABLER_TAG, name=name)
        try:
            svg = fetch(url)
        except Exception as e:
            missing.append(name)
            print(f"  ! {name}: {e}")
            continue
        png = cairosvg.svg2png(bytestring=svg, output_width=256, output_height=256)
        rendered = Image.open(io.BytesIO(png)).convert("RGBA")
        # Tabler outline icons render as black strokes; recolor to white by
        # painting a solid white tile through the rendered alpha channel.
        white = Image.new("RGBA", rendered.size, (255, 255, 255, 255))
        white.putalpha(rendered.getchannel("A"))
        white.save(os.path.join(glyph_dir, f"{name}.png"))
        print(f"  ok {name}")

    with open(os.path.join(OUT, "LICENSE-tabler-icons.txt"), "wb") as f:
        f.write(fetch(TABLER_LICENSE.format(tag=TABLER_TAG)))
    with open(os.path.join(font_dir, "Anton-Regular.ttf"), "wb") as f:
        f.write(fetch(ANTON_TTF))
    with open(os.path.join(font_dir, "OFL-Anton.txt"), "wb") as f:
        f.write(fetch(ANTON_OFL))

    if missing:
        sys.exit(
            f"\n{len(missing)} glyph(s) failed: {', '.join(missing)}.\n"
            "Substitute a similar icon name that exists at "
            f"https://tabler.io/icons (tag {TABLER_TAG}), update GLYPHS here "
            "AND the matching entry in badge_renderer.py, then re-run."
        )
    print(f"\nDone -> {OUT}")


if __name__ == "__main__":
    main()
