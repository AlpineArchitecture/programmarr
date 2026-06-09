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


# ── tv_movie_mix ───────────────────────────────────────────────────────────────

def test_tv_movie_mix_contains_both_show_and_movie_titles(pr, seed):
    """A tv_movie_mix channel's content includes titles from both movie and TV sides."""
    seed([
        movie("Comedy Film A", genres="Comedy"),
        movie("Comedy Film B", genres="Comedy"),
        show("Comedy Show A", genres="Comedy", episodes=50),
        show("Comedy Show B", genres="Comedy", episodes=30),
    ])
    out = _compose(pr, [{"kind": "tv_movie_mix", "genre": "Comedy", "name": "Comedy"}])
    assert out["count"] == 1
    ch = out["channels"][0]
    assert ch["items"] == 4  # 2 movies + 2 shows


def test_tv_movie_mix_content_in_draft(pr, seed):
    """Draft file written by compose contains both a show title and a movie title."""
    import json as _json
    seed([
        movie("Action Film", genres="Action"),
        show("Action Show", genres="Action", episodes=80),
    ])
    _compose(pr, [{"kind": "tv_movie_mix", "genre": "Action", "name": "Action"}])
    draft = _json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    content = draft["channels"][0]["content"]
    assert "Action Film" in content
    assert "Action Show" in content


def test_tv_movie_mix_auto_name(pr, seed):
    """_auto_name for tv_movie_mix returns the bare genre name."""
    seed([
        movie("Horror Film 1", genres="Horror"),
        movie("Horror Film 2", genres="Horror"),
        show("Horror Show 1", genres="Horror", episodes=30),
    ])
    out = _compose(pr, [{"kind": "tv_movie_mix", "genre": "Horror"}])
    assert out["channels"][0]["name"] == "Horror"


def test_tv_movie_mix_genre_case_insensitive(pr, seed):
    """Genre matching in tv_movie_mix is case-insensitive."""
    seed([
        movie("Drama Film", genres="Drama"),
        show("drama show", genres="drama", episodes=20),  # lowercase genre tag
    ])
    out = _compose(pr, [{"kind": "tv_movie_mix", "genre": "Drama"}])
    assert out["count"] == 1
    assert out["channels"][0]["items"] == 2


def test_tv_movie_mix_no_match_is_skipped(pr, seed):
    """A tv_movie_mix spec with no matching titles is skipped with a reason."""
    seed([movie("Comedy Film", genres="Comedy")])
    out = _compose(pr, [{"kind": "tv_movie_mix", "genre": "Western"}])
    assert out["count"] == 0
    assert out["skipped"][0]["reason"] == "no matching titles"


# ── network ────────────────────────────────────────────────────────────────────

def test_network_resolves_tv_shows_by_studio(pr, seed):
    """kind=network resolves TV show titles whose Studio matches value (case-insensitive)."""
    seed([
        show("The Sopranos", studio="HBO"),
        show("The Wire", studio="HBO"),
        show("Breaking Bad", studio="AMC"),
        movie("HBO Film", studio="HBO"),  # movie rows must NOT appear in network channel
    ])
    out = _compose(pr, [{"kind": "network", "value": "HBO"}])
    assert out["count"] == 1
    # Must contain exactly the 2 HBO shows, not the movie.
    draft = json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    content = set(draft["channels"][0]["content"])
    assert content == {"The Sopranos", "The Wire"}


def test_network_case_insensitive(pr, seed):
    """Network value matching is case-insensitive."""
    seed([
        show("Show A", studio="hbo"),
        show("Show B", studio="HBO"),
        show("Show C", studio="Hbo"),
    ])
    out = _compose(pr, [{"kind": "network", "value": "HBO"}])
    assert out["count"] == 1
    assert out["channels"][0]["items"] == 3


def test_network_auto_name(pr, seed):
    """_auto_name for network returns the network value."""
    seed([
        show("Show X", studio="Netflix"),
        show("Show Y", studio="Netflix"),
        show("Show Z", studio="Netflix"),
    ])
    out = _compose(pr, [{"kind": "network", "value": "Netflix"}])
    assert out["channels"][0]["name"] == "Netflix"


def test_network_no_match_skipped(pr, seed):
    """A network spec with no matching TV shows is skipped."""
    seed([show("Some Show", studio="HBO")])
    out = _compose(pr, [{"kind": "network", "value": "Netflix"}])
    assert out["count"] == 0
    assert out["skipped"][0]["reason"] == "no matching titles"


def test_network_shuffle_default(pr, seed):
    """network kind uses 'shuffle' as its default shuffle mode."""
    seed([
        show("A", studio="HBO"),
        show("B", studio="HBO"),
        show("C", studio="HBO"),
    ])
    _compose(pr, [{"kind": "network", "value": "HBO"}])
    draft = json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    assert draft["channels"][0]["shuffle"] == "shuffle"


# ── programming_block ──────────────────────────────────────────────────────────

def test_programming_block_resolves_member_titles(pr, seed):
    """kind=programming_block resolves the spec's titles list against library TV shows."""
    seed([
        show("Full House", episodes=192),
        show("Family Matters", episodes=215),
        show("Step by Step", episodes=160),
        # "Boy Meets World" not in library
    ])
    out = _compose(pr, [{
        "kind": "programming_block",
        "name": "TGIF",
        "titles": ["Full House", "Family Matters", "Step by Step", "Boy Meets World"],
    }])
    assert out["count"] == 1
    draft = json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    content = set(draft["channels"][0]["content"])
    # Only the 3 titles present in the library; Boy Meets World is absent.
    assert content == {"Full House", "Family Matters", "Step by Step"}
    assert "Boy Meets World" not in content


def test_programming_block_case_insensitive_intersection(pr, seed):
    """programming_block title matching against library is case-insensitive."""
    seed([
        show("full house", episodes=192),       # different case in library
        show("Family Matters", episodes=215),
        show("Step by Step", episodes=160),
    ])
    out = _compose(pr, [{
        "kind": "programming_block",
        "name": "TGIF",
        "titles": ["Full House", "Family Matters", "Step by Step"],
    }])
    assert out["count"] == 1
    assert out["channels"][0]["items"] == 3


def test_programming_block_auto_name(pr, seed):
    """_auto_name for programming_block returns the spec's name."""
    seed([
        show("Seinfeld", episodes=180),
        show("Friends", episodes=236),
        show("Frasier", episodes=264),
    ])
    out = _compose(pr, [{
        "kind": "programming_block",
        "name": "Must See TV",
        "titles": ["Seinfeld", "Friends", "Frasier"],
    }])
    assert out["channels"][0]["name"] == "Must See TV"


def test_programming_block_shuffle_default(pr, seed):
    """programming_block kind uses 'ordered' as its default shuffle mode."""
    seed([
        show("Show A", episodes=50),
        show("Show B", episodes=50),
        show("Show C", episodes=50),
    ])
    _compose(pr, [{
        "kind": "programming_block",
        "name": "Test Block",
        "titles": ["Show A", "Show B", "Show C"],
    }])
    draft = json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    assert draft["channels"][0]["shuffle"] == "ordered"


def test_programming_block_no_titles_skipped(pr, seed):
    """A programming_block spec with no titles field (or empty list) is skipped."""
    seed([show("Some Show", episodes=50)])
    out = _compose(pr, [{"kind": "programming_block", "name": "Empty Block", "titles": []}])
    assert out["count"] == 0
    assert out["skipped"][0]["reason"] == "no matching titles"


def test_programming_block_no_library_match_skipped(pr, seed):
    """A programming_block whose titles don't match any library show is skipped."""
    seed([show("Other Show", episodes=50)])
    out = _compose(pr, [{
        "kind": "programming_block",
        "name": "TGIF",
        "titles": ["Full House", "Family Matters"],
    }])
    assert out["count"] == 0
    assert out["skipped"][0]["reason"] == "no matching titles"
