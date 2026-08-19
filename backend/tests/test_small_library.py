"""test_small_library.py — libraries unlike the author's must still work.

Programmarr was built against one large, TV-heavy, mostly-modern library. Two
shapes that break that assumption:
  * a classic-film collection — every pre-1970 title used to fall out of the
    decade facet entirely, because the buckets started at 1970;
  * a movies-only library — the whole TV side of the Planner goes empty and the
    UI must explain why rather than render blank panes.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from conftest import movie, show  # noqa: E402


def labels(facets):
    return {d["label"] for d in facets["decades"]}


def test_pre_1970_films_get_decades(pr, seed):
    """A classic library contributed nothing to the decade facet before this."""
    seed([movie(f"Noir {i}", year=1947, genres="Crime") for i in range(8)] +
         [movie(f"Silent {i}", year=1925, genres="Drama") for i in range(6)])

    f = pr.library_facets()
    assert "1940s" in labels(f)
    assert "1920s" in labels(f)


def test_new_decade_labels_are_unambiguous(pr, seed):
    """'20s' next to '2020s' would be ambiguous in a channel name."""
    seed([movie(f"A{i}", year=1925) for i in range(6)] +
         [movie(f"B{i}", year=2021) for i in range(6)])

    ls = labels(pr.library_facets())
    assert "1920s" in ls and "2020s" in ls
    assert "20s" not in ls


def test_existing_decade_labels_unchanged(pr, seed):
    """70s/80s/90s must keep their labels — channel names and saved planner
    state already reference them."""
    seed([movie(f"A{i}", year=1975) for i in range(6)] +
         [movie(f"B{i}", year=1985) for i in range(6)] +
         [movie(f"C{i}", year=1995) for i in range(6)])

    ls = labels(pr.library_facets())
    assert {"70s", "80s", "90s"} <= ls


def test_empty_decades_are_not_offered(pr, seed):
    """The extra buckets must stay free — no empty decade channels."""
    seed([movie(f"A{i}", year=1995) for i in range(6)])

    assert labels(pr.library_facets()) == {"90s"}


def test_movies_only_library_reports_zero_tv(pr, seed):
    """The UI branches on tv_shows to explain an empty TV section."""
    seed([movie(f"A{i}", year=1995, genres="Action") for i in range(20)])

    f = pr.library_facets()
    assert f["tv_shows"] == 0
    assert f["marathons"] == [] and f["tv_genres"] == []
    assert f["networks"] == [] and f["tv_movie_genres"] == []
    assert f["movies"] == 20          # the movie side still works


def test_tv_present_but_below_thresholds_is_distinguishable(pr, seed):
    """'You have shows, none qualify' is a different message from 'you have no
    shows' — the count is what lets the UI tell them apart."""
    seed([show("Lonely Show", genres="Drama", episodes=8)])

    f = pr.library_facets()
    assert f["tv_shows"] == 1
    # A short run is still offerable as a channel (the listing gate is 2+ episodes);
    # only the 50-episode MARATHON count stays at zero.
    assert f["marathon_count"] == 0
    assert [m["title"] for m in f["marathons"]] == ["Lonely Show"]
    assert f["tv_genres"] == []       # 1 show < TV_GENRE_MIN


def test_single_episode_show_is_not_offered(pr, seed):
    """One-episode entries make no sense as a channel."""
    seed([show("Pilot Only", genres="Drama", episodes=1)])

    f = pr.library_facets()
    assert f["tv_shows"] == 1
    assert f["marathons"] == []


def test_tiny_library_does_not_crash(pr, seed):
    """A ~200-title library sits under most facet floors; that must be an empty
    facet, never an exception."""
    seed([movie(f"M{i}", year=2000 + (i % 20), genres="Drama") for i in range(20)])

    f = pr.library_facets()
    assert f["exists"] is True
    for key in ("studios", "directors", "actors", "blends", "genre_decade"):
        assert isinstance(f[key], list)
