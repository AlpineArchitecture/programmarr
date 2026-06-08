"""compose_channels — each CandidateSpec kind resolves; soft-block numbering + spill."""

import json

import pytest
from conftest import movie, show


def _compose(pr, specs, start=1):
    req = pr.ComposeRequest(specs=[pr.CandidateSpec(**s) for s in specs], start=start)
    return pr.compose_channels(req)


def test_genre_spec_resolves_titles(pr, seed):
    seed([movie("Funny One", genres="Comedy"),
          movie("Funny Two", genres="comedy"),   # case-insensitive genre match
          movie("Scary", genres="Horror")])
    out = _compose(pr, [{"kind": "genre", "genre": "Comedy"}])
    assert out["count"] == 1
    ch = out["channels"][0]
    assert ch["items"] == 2  # both comedies, not the horror


def test_each_kind_resolves(pr, seed):
    seed([
        movie("Dir Film", director="Greta Gerwig"),
        movie("Studio Film", studio="A24"),
        movie("Star Film", actors="Tom Hanks"),
        movie("Nineties Com", year=1995, genres="Comedy"),
        movie("Blend Film", genres="Comedy|Drama"),
        show("Big Show", genres="Comedy", episodes=200),
    ])
    out = _compose(pr, [
        {"kind": "director", "value": "Greta Gerwig"},
        {"kind": "studio", "value": "A24"},
        {"kind": "actor", "value": "Tom Hanks"},
        {"kind": "genre_decade", "genre": "Comedy", "decade_start": 1990},
        {"kind": "blend", "genres": ["Comedy", "Drama"]},
        {"kind": "tv_genre", "genre": "Comedy"},
        {"kind": "marathon", "value": "Big Show"},
    ])
    assert out["count"] == 7
    assert out["skipped"] == []


def test_empty_spec_skipped_and_reported(pr, seed):
    seed([movie("Funny", genres="Comedy")])
    out = _compose(pr, [
        {"kind": "genre", "genre": "Comedy"},
        {"kind": "genre", "genre": "Western"},   # no titles -> skipped
    ])
    assert out["count"] == 1
    assert len(out["skipped"]) == 1
    assert out["skipped"][0]["reason"] == "no matching titles"


def test_unknown_kind_reported(pr, seed):
    seed([movie("Funny", genres="Comedy")])
    out = _compose(pr, [{"kind": "bogus", "name": "Weird"}])
    assert out["count"] == 0
    assert "unknown kind" in out["skipped"][0]["reason"]


def test_fresh_deploy_starts_at_one(pr, seed):
    # start=1 (a fresh deploy with nothing kept) truly begins at channel 1 — no 10 floor.
    seed([show("Loop Show", episodes=300), movie("Funny", genres="Comedy")])
    out = _compose(pr, [
        {"kind": "genre", "genre": "Comedy"},
        {"kind": "marathon", "value": "Loop Show"},
    ])
    by_name = {c["name"]: c["number"] for c in out["channels"]}
    # Default sizes 10/10/20: marathon block 1–10, movie block 21–40.
    assert by_name["Loop Show 24/7"] == 1
    assert by_name["Comedy Movies"] == 21


def test_classic_layout_when_starting_at_ten(pr, seed):
    # Keeping existing channels rounds the start up (e.g. to 10) → the historical layout.
    seed([show("Loop Show", episodes=300), movie("Funny", genres="Comedy")])
    out = _compose(pr, [
        {"kind": "genre", "genre": "Comedy"},
        {"kind": "marathon", "value": "Loop Show"},
    ], start=10)
    by_name = {c["name"]: c["number"] for c in out["channels"]}
    assert by_name["Loop Show 24/7"] == 10
    assert by_name["Comedy Movies"] == 30


def test_custom_block_sizes_from_config(pr, seed):
    # A config-set block size scales a category; later blocks shift to accommodate it.
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"channel_blocks": {"marathon": 100}}), encoding="utf-8")
    seed([show("Loop Show", episodes=300), movie("Funny", genres="Comedy")])
    out = _compose(pr, [
        {"kind": "genre", "genre": "Comedy"},
        {"kind": "marathon", "value": "Loop Show"},
    ])
    by_name = {c["name"]: c["number"] for c in out["channels"]}
    # marathon 1–100, then default tv_block 101–110, so the movie block starts at 111.
    assert by_name["Loop Show 24/7"] == 1
    assert by_name["Comedy Movies"] == 111


def test_marathon_overflow_spills_sequentially(pr, seed):
    shows = [show(f"Show {i}", episodes=100 + i) for i in range(12)]
    seed(shows)
    specs = [{"kind": "marathon", "value": f"Show {i}"} for i in range(12)]
    out = _compose(pr, specs)
    numbers = sorted(c["number"] for c in out["channels"])
    # Default marathon block is 1–10; 12 marathons spill past into 11, 12 — contiguous.
    assert numbers == list(range(1, 13))


def test_writes_channels_json(pr, seed):
    seed([movie("Funny", genres="Comedy")])
    _compose(pr, [{"kind": "genre", "genre": "Comedy"}])
    written = json.loads((pr._test_data_dir / "channels.json").read_text(encoding="utf-8"))
    assert written["channels"][0]["name"] == "Comedy Movies"
    assert written["channels"][0]["content"] == ["Funny"]


def test_compose_without_export_raises(pr):
    with pytest.raises(Exception):
        _compose(pr, [{"kind": "genre", "genre": "Comedy"}])
