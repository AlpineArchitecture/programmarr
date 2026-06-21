"""test_resolve_title_collision.py — a movie and a series with the same exact title.

Real bug: the library held both the 2017 "Baywatch" film and the 242-episode 1989
series. resolve_title checked movie_map first and returned unconditionally, so the
"Baywatch Marathon" channel looped the lone movie instead of the series. The fix
prefers whichever copy has more PLAYABLE programs.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import channel_engine


def _movie(title, state="ok"):
    return {"program": {"title": title, "state": state}}


def _show(title, n_eps, state="ok"):
    return {
        "title": title,
        "showId": f"uuid-{title}",
        "programs": [{"program": {"title": f"{title} S1E{i}", "state": state}} for i in range(n_eps)],
    }


def test_series_beats_same_named_movie():
    movie_map = {"baywatch": _movie("Baywatch")}
    show_map = {"baywatch": _show("Baywatch", 242)}
    item = channel_engine.resolve_title("Baywatch", movie_map, show_map)
    assert item["type"] == "TV"
    assert len(item["programs"]) == 242


def test_movie_kept_when_series_is_all_missing():
    movie_map = {"baywatch": _movie("Baywatch")}
    show_map = {"baywatch": _show("Baywatch", 5, state="missing")}  # dead series, 0 playable
    item = channel_engine.resolve_title("Baywatch", movie_map, show_map)
    assert item["type"] == "Movie"


def test_no_collision_unchanged():
    movie_map = {"big movie": _movie("Big Movie")}
    show_map = {"cheers": _show("Cheers", 10)}
    assert channel_engine.resolve_title("Big Movie", movie_map, show_map)["type"] == "Movie"
    assert channel_engine.resolve_title("Cheers", movie_map, show_map)["type"] == "TV"
    assert channel_engine.resolve_title("Nope", movie_map, show_map) is None
