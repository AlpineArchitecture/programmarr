"""badge_renderer tests — real Pillow rendering against committed badge_assets/."""

import io

from PIL import Image

import badge_renderer


def _open(png_bytes):
    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")


def test_render_returns_512_png():
    img = _open(badge_renderer.render_badge("Horror", kind="genre", genre="horror"))
    assert img.size == (512, 512)


def test_genre_sets_background_color():
    img = _open(badge_renderer.render_badge("Horror", kind="genre", genre="horror"))
    # (256, 40): top-center, inside the rounded rect fill, above the glyph.
    assert img.getpixel((256, 40)) == (139, 0, 0, 255)  # horror = #8b0000


def test_different_genres_render_differently():
    horror = badge_renderer.render_badge("Late Night", kind="genre", genre="horror")
    comedy = badge_renderer.render_badge("Late Night", kind="genre", genre="comedy")
    assert horror != comedy


def test_kind_color_when_no_genre():
    img = _open(badge_renderer.render_badge("HBO", kind="network"))
    assert img.getpixel((256, 40)) == (40, 53, 147, 255)  # network = #283593


def test_unknown_everything_uses_default():
    img = _open(badge_renderer.render_badge("Mystery Box"))
    assert img.getpixel((256, 40)) == (55, 71, 79, 255)  # default = #37474f


def test_long_names_do_not_crash():
    png = badge_renderer.render_badge(
        "The Totally Excellent Late Night Creature Feature Double Bill Marathon",
        kind="theme")
    assert _open(png).size == (512, 512)


def test_name_text_changes_output():
    a = badge_renderer.render_badge("Horror", genre="horror")
    b = badge_renderer.render_badge("80s Horror", genre="horror")
    assert a != b
