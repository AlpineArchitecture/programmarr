"""test_library_index_multilib.py — index ALL movie/shows libraries, not just the first.

A Plex server can expose more than one movie or shows library (e.g. 'TV Shows' AND
'Cartoons'). build_library_index must aggregate every enabled library of each kind;
indexing only the first silently drops whole libraries, so any channel referencing a
show that lives in a secondary library resolves to empty.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import channel_engine


def _prog(title, show=None, state="ok"):
    p = {"title": title, "state": state}
    if show:
        p["show"] = {"uuid": f"uuid-{show}", "title": show}
    return {"type": "content", "id": f"id-{title}", "program": p}


@pytest.fixture
def two_shows_libs(monkeypatch):
    source = {"libraries": [
        {"id": "mv1", "mediaType": "movies", "enabled": True},
        {"id": "tv1", "mediaType": "shows", "enabled": True},   # TV Shows
        {"id": "tv2", "mediaType": "shows", "enabled": True},   # Cartoons
        {"id": "mv2", "mediaType": "movie", "enabled": True},   # a second movie lib
    ]}
    # Daria lives in BOTH tv1 and tv2 (a show duplicated across libraries) — must not
    # be double-counted, or resolve inflates past what Tunarr's show-slot enumerates
    # (permanent diff mismatch / scheduler churn).
    progs = {
        "mv1": [_prog("Big Movie")],
        "mv2": [_prog("Indie Film")],
        "tv1": [_prog("Cheers S1E1", show="Cheers"),
                _prog("Daria S1E1", show="Daria"), _prog("Daria S1E2", show="Daria"),
                # Phantom is a DEAD duplicate here (all files missing)...
                _prog("Phantom S1E1", show="Phantom", state="missing"),
                _prog("Phantom S1E2", show="Phantom", state="missing")],
        # ...but the real, playable Phantom lives in tv2.
        "tv2": [_prog("Daria S1E1 dup", show="Daria"), _prog("Daria S1E2 dup", show="Daria"),
                _prog("Phantom S1E1 real", show="Phantom"),
                _prog("Phantom S1E2 real", show="Phantom"),
                _prog("Phantom S1E3 real", show="Phantom")],
    }
    monkeypatch.setattr(channel_engine, "get_plex_source", lambda url: source)

    def fake_api(url, method, path, body=None, timeout=60):
        for lib_id, items in progs.items():
            if path.endswith(f"/{lib_id}/programs"):
                return items
        raise AssertionError(f"unexpected api call: {path}")

    monkeypatch.setattr(channel_engine, "api", fake_api)


def test_indexes_shows_from_all_shows_libraries(two_shows_libs):
    _, show_map = channel_engine.build_library_index("http://t")
    assert "cheers" in show_map     # from TV Shows
    assert "daria" in show_map      # from Cartoons (would be dropped by first-only)
    assert len(show_map["daria"]["programs"]) == 2


def test_indexes_movies_from_all_movie_libraries(two_shows_libs):
    movie_map, _ = channel_engine.build_library_index("http://t")
    assert "big movie" in movie_map
    assert "indie film" in movie_map  # from the second movie library


def test_show_in_multiple_libraries_is_not_doubled(two_shows_libs):
    """Daria is in both tv1 and tv2 — index it once (first library wins), not twice.

    Otherwise resolve() returns 2x the episodes while Tunarr's single show-slot
    enumerates 1x → the scheduler diff never converges and patches every cycle.
    """
    _, show_map = channel_engine.build_library_index("http://t")
    assert len(show_map["daria"]["programs"]) == 2  # one library's worth, not 4


def test_duplicate_show_prefers_the_playable_copy(two_shows_libs):
    """When a show is in two libraries, pick the copy with the most playable episodes.

    Mirrors the real bug: a dead 'Daria' (all files missing) in 'TV Shows' shadowing the
    real one in 'Cartoons'. Picking the dead copy gives a channel that plays nothing.
    """
    _, show_map = channel_engine.build_library_index("http://t")
    phantom = show_map["phantom"]["programs"]
    assert len(phantom) == 3                                   # the tv2 (real) copy
    assert all(p["program"]["state"] == "ok" for p in phantom)  # not the all-missing one
