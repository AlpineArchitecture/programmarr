"""compose_channels — each CandidateSpec kind resolves; sequential tight-packed numbering."""

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
    """start=1 (fresh deploy) → marathon gets 1, movie category follows immediately after."""
    seed([show("Loop Show", episodes=300), movie("Funny", genres="Comedy")])
    out = _compose(pr, [
        {"kind": "genre", "genre": "Comedy"},
        {"kind": "marathon", "value": "Loop Show"},
    ])
    by_name = {c["name"]: c["number"] for c in out["channels"]}
    # Sequential: marathon first (default order), movie second — no fixed gaps.
    assert by_name["Loop Show 24/7"] == 1
    assert by_name["Comedy Movies"] == 2


def test_multiple_in_same_category_numbered_contiguously(pr, seed):
    """Multiple channels in the same category get consecutive numbers."""
    seed([
        show("Show A", episodes=300),
        show("Show B", episodes=200),
        show("Show C", episodes=100),
    ])
    out = _compose(pr, [
        {"kind": "marathon", "value": "Show A"},
        {"kind": "marathon", "value": "Show B"},
        {"kind": "marathon", "value": "Show C"},
    ])
    numbers = sorted(c["number"] for c in out["channels"])
    assert numbers == [1, 2, 3]


def test_category_ordering_from_config(pr, seed):
    """Putting movie before marathon in channel_order makes movie channels get lower numbers."""
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"channel_order": ["movie", "marathon", "tv_block", "tv_movie_mix",
                                      "entity", "network", "programming_block",
                                      "franchise", "specialty"]}),
        encoding="utf-8")
    seed([show("Loop Show", episodes=300), movie("Funny", genres="Comedy")])
    out = _compose(pr, [
        {"kind": "genre", "genre": "Comedy"},
        {"kind": "marathon", "value": "Loop Show"},
    ])
    by_name = {c["name"]: c["number"] for c in out["channels"]}
    # movie category comes first in config → Comedy Movies gets 1, Loop Show 24/7 gets 2
    assert by_name["Comedy Movies"] == 1
    assert by_name["Loop Show 24/7"] == 2


def test_old_channel_blocks_config_does_not_crash(pr, seed):
    """Old configs with channel_blocks key (sizes) are silently ignored — no crash."""
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"channel_blocks": {"marathon": 10, "movie": 20}}), encoding="utf-8")
    seed([movie("Funny", genres="Comedy")])
    out = _compose(pr, [{"kind": "genre", "genre": "Comedy"}])
    assert out["count"] == 1
    assert out["channels"][0]["number"] == 1


def test_start_offset_respected(pr, seed):
    """start=10 shifts all numbers up from 10, not from 1."""
    seed([show("Loop Show", episodes=300), movie("Funny", genres="Comedy")])
    out = _compose(pr, [
        {"kind": "marathon", "value": "Loop Show"},
        {"kind": "genre", "genre": "Comedy"},
    ], start=10)
    by_name = {c["name"]: c["number"] for c in out["channels"]}
    assert by_name["Loop Show 24/7"] == 10
    assert by_name["Comedy Movies"] == 11


def test_writes_channels_draft(pr, seed):
    seed([movie("Funny", genres="Comedy")])
    _compose(pr, [{"kind": "genre", "genre": "Comedy"}])
    written = json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    assert written["channels"][0]["name"] == "Comedy Movies"
    assert written["channels"][0]["content"] == ["Funny"]


def test_compose_without_export_raises(pr):
    with pytest.raises(Exception):
        _compose(pr, [{"kind": "genre", "genre": "Comedy"}])
