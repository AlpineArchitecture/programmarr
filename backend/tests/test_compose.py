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
# NOTE: compose kind=network now resolves shows from the TVmaze cache when present,
# falling back to the Studio column when the cache is absent.  Comprehensive tests
# covering TVmaze-source behavior live in test_networks.py.

def _write_tvmaze_cache(pr, networks_map: dict):
    """Write a valid tvmaze_cache.json for the current library signature."""
    sig = pr._library_signature()
    cache = {"sig": sig, "networks": networks_map}
    (pr._test_data_dir / "tvmaze_cache.json").write_text(
        json.dumps(cache), encoding="utf-8"
    )


def test_network_resolves_tv_shows_via_tvmaze_cache(pr, seed):
    """kind=network resolves TV show titles via TVmaze cache (case-insensitive value)."""
    seed([
        show("The Sopranos", studio="Irrelevant"),
        show("The Wire", studio="Irrelevant"),
        show("Breaking Bad", studio="Irrelevant"),
        movie("HBO Film", studio="HBO"),  # movie rows must NOT appear in network channel
    ])
    _write_tvmaze_cache(pr, {
        "The Sopranos": "HBO",
        "The Wire": "HBO",
        "Breaking Bad": "AMC",
    })
    out = _compose(pr, [{"kind": "network", "value": "HBO"}])
    assert out["count"] == 1
    # Must contain exactly the 2 HBO shows, not the AMC show or the movie.
    draft = json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    content = set(draft["channels"][0]["content"])
    assert content == {"The Sopranos", "The Wire"}


def test_network_case_insensitive(pr, seed):
    """Network value matching is case-insensitive (TVmaze cache path)."""
    seed([
        show("Show A"),
        show("Show B"),
        show("Show C"),
    ])
    _write_tvmaze_cache(pr, {"Show A": "hbo", "Show B": "HBO", "Show C": "Hbo"})
    out = _compose(pr, [{"kind": "network", "value": "HBO"}])
    assert out["count"] == 1
    assert out["channels"][0]["items"] == 3


def test_network_auto_name(pr, seed):
    """_auto_name for network returns the network value."""
    seed([
        show("Show X"),
        show("Show Y"),
        show("Show Z"),
    ])
    _write_tvmaze_cache(pr, {"Show X": "Netflix", "Show Y": "Netflix", "Show Z": "Netflix"})
    out = _compose(pr, [{"kind": "network", "value": "Netflix"}])
    assert out["channels"][0]["name"] == "Netflix"


def test_network_no_match_skipped(pr, seed):
    """A network spec with no matching TV shows is skipped (TVmaze cache has different network)."""
    seed([show("Some Show")])
    _write_tvmaze_cache(pr, {"Some Show": "HBO"})
    out = _compose(pr, [{"kind": "network", "value": "Netflix"}])
    assert out["count"] == 0
    assert out["skipped"][0]["reason"] == "no matching titles"


def test_network_shuffle_default(pr, seed):
    """network kind uses 'shuffle' as its default shuffle mode."""
    seed([show("A"), show("B"), show("C")])
    _write_tvmaze_cache(pr, {"A": "HBO", "B": "HBO", "C": "HBO"})
    _compose(pr, [{"kind": "network", "value": "HBO"}])
    draft = json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    assert draft["channels"][0]["shuffle"] == "shuffle"


def test_network_fallback_to_studio_when_no_cache(pr, seed):
    """Without TVmaze cache, network kind falls back to the Studio column."""
    seed([
        show("Show A", studio="HBO"),
        show("Show B", studio="HBO"),
        show("Show C", studio="HBO"),
    ])
    # No cache written — Studio fallback must find the HBO shows.
    out = _compose(pr, [{"kind": "network", "value": "HBO"}])
    assert out["count"] == 1
    assert out["channels"][0]["items"] == 3


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


# ── franchise ──────────────────────────────────────────────────────────────────

def test_franchise_resolves_checked_titles(pr, seed):
    """kind=franchise resolves spec.titles against the library (movies + shows)."""
    seed([
        movie("The Matrix", year=1999),
        movie("The Matrix Reloaded", year=2003),
        movie("The Matrix Revolutions", year=2003),
    ])
    out = _compose(pr, [{
        "kind": "franchise",
        "name": "The Matrix Collection",
        "titles": ["The Matrix", "The Matrix Reloaded"],  # Revolutions unchecked
    }])
    assert out["count"] == 1
    draft = json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    content = draft["channels"][0]["content"]
    assert "The Matrix" in content
    assert "The Matrix Reloaded" in content
    assert "The Matrix Revolutions" not in content


def test_franchise_titles_sorted_by_year(pr, seed):
    """franchise content is sorted by year ascending for release-order playback."""
    seed([
        movie("Episode III", year=2005),
        movie("Episode I", year=1999),
        movie("Episode II", year=2002),
    ])
    out = _compose(pr, [{
        "kind": "franchise",
        "name": "Prequel Trilogy",
        "titles": ["Episode III", "Episode I", "Episode II"],
    }])
    assert out["count"] == 1
    draft = json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    content = draft["channels"][0]["content"]
    assert content == ["Episode I", "Episode II", "Episode III"]


def test_franchise_spans_tv_and_movies(pr, seed):
    """franchise resolves members from both movies and TV shows."""
    seed([
        movie("Firefly: Serenity", year=2005),
        show("Firefly", episodes=14),
    ])
    out = _compose(pr, [{
        "kind": "franchise",
        "name": "Firefly Franchise",
        "titles": ["Firefly", "Firefly: Serenity"],
    }])
    assert out["count"] == 1
    draft = json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    content = set(draft["channels"][0]["content"])
    assert "Firefly: Serenity" in content
    assert "Firefly" in content


def test_franchise_title_intersection_case_insensitive(pr, seed):
    """franchise title matching against library is case-insensitive."""
    seed([movie("batman begins", year=2005), movie("The Dark Knight", year=2008)])
    out = _compose(pr, [{
        "kind": "franchise",
        "name": "Dark Knight Trilogy",
        "titles": ["Batman Begins", "The Dark Knight"],
    }])
    assert out["count"] == 1
    assert out["channels"][0]["items"] == 2


def test_franchise_not_in_library_skipped(pr, seed):
    """franchise spec with no library matches is skipped."""
    seed([movie("Unrelated Film", year=2000)])
    out = _compose(pr, [{
        "kind": "franchise",
        "name": "MCU",
        "titles": ["Iron Man", "Thor"],
    }])
    assert out["count"] == 0
    assert out["skipped"][0]["reason"] == "no matching titles"


def test_franchise_auto_name(pr, seed):
    """_auto_name for franchise returns spec.name."""
    seed([movie("Iron Man", year=2008), movie("Iron Man 2", year=2010)])
    out = _compose(pr, [{
        "kind": "franchise",
        "name": "Iron Man Series",
        "titles": ["Iron Man", "Iron Man 2"],
    }])
    assert out["channels"][0]["name"] == "Iron Man Series"


def test_franchise_shuffle_default(pr, seed):
    """franchise kind uses 'ordered' as its default shuffle mode."""
    seed([movie("Movie A", year=2000), movie("Movie B", year=2002)])
    _compose(pr, [{
        "kind": "franchise",
        "name": "Test Franchise",
        "titles": ["Movie A", "Movie B"],
    }])
    draft = json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    assert draft["channels"][0]["shuffle"] == "ordered"


def test_franchise_no_titles_skipped(pr, seed):
    """franchise spec with empty titles list is skipped."""
    seed([movie("Foo", year=2000)])
    out = _compose(pr, [{"kind": "franchise", "name": "Empty", "titles": []}])
    assert out["count"] == 0
    assert out["skipped"][0]["reason"] == "no matching titles"


# ── live franchise refs ────────────────────────────────────────────────────────

def _write_tmdb_enrichment(pr, collection_id, collection_name, titles):
    """Write a minimal tmdb_enrichment.json with the given collection members."""
    enrichment = {
        t: {"title": t, "year": 1990 + i, "collection": {"id": collection_id, "name": collection_name}, "keywords": []}
        for i, t in enumerate(titles)
    }
    cache = {"sig": "x", "enrichment": enrichment}
    (pr._test_data_dir / "tmdb_enrichment.json").write_text(
        json.dumps(cache), encoding="utf-8"
    )


def test_compose_live_franchise_emits_franchise_ref(pr, seed):
    """A franchise spec with live=True and a matching cache entry produces a live channel
    whose content is a single franchise identity ref; unchecked members become the exclude list."""
    seed([
        movie("Die Hard", year=1988),
        movie("Die Hard 2", year=1990),
        movie("Die Hard 3", year=1995),
    ])
    # Cache has three members; spec only checks the first two.
    _write_tmdb_enrichment(pr, 1570, "Die Hard Collection",
                           ["Die Hard", "Die Hard 2", "Die Hard 3"])

    out = _compose(pr, [{
        "kind": "franchise",
        "name": "Die Hard Collection",
        "titles": ["Die Hard", "Die Hard 2"],
        "live": True,
    }])
    assert out["count"] == 1

    draft = json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    ch = draft["channels"][0]

    assert ch.get("live") is True
    assert ch["shuffle"] == "ordered"
    assert len(ch["content"]) == 1
    ref = ch["content"][0]
    assert ref["match"] == "franchise"
    assert ref["name"] == "Die Hard Collection"
    assert ref["order"] == "release_date"
    # exclude = members NOT checked, in index order
    assert ref["exclude"] == ["Die Hard 3"]


def test_compose_live_franchise_without_cache_falls_back_static(pr, seed):
    """A live=True franchise spec with no cache files falls back to a static channel
    (plain title list, no live flag)."""
    seed([
        movie("Die Hard", year=1988),
        movie("Die Hard 2", year=1990),
        movie("Die Hard 3", year=1995),
    ])
    # No tmdb_enrichment.json or wikidata_cache.json written.

    out = _compose(pr, [{
        "kind": "franchise",
        "name": "Die Hard Collection",
        "titles": ["Die Hard", "Die Hard 2"],
        "live": True,
    }])
    assert out["count"] == 1

    draft = json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    ch = draft["channels"][0]

    # Static fallback: plain titles, not live.
    assert not ch.get("live")
    assert all(isinstance(item, str) for item in ch["content"])
    assert "Die Hard" in ch["content"]
    assert "Die Hard 2" in ch["content"]


def test_compose_non_live_franchise_unchanged(pr, seed):
    """A franchise spec without live (or live=False) composes exactly as before:
    static title list sorted by year, no live flag, even when a cache exists."""
    seed([
        movie("Die Hard", year=1988),
        movie("Die Hard 2", year=1990),
    ])
    _write_tmdb_enrichment(pr, 1570, "Die Hard Collection",
                           ["Die Hard", "Die Hard 2", "Die Hard 3"])

    out = _compose(pr, [{
        "kind": "franchise",
        "name": "Die Hard Collection",
        "titles": ["Die Hard", "Die Hard 2"],
        # live omitted — defaults to False
    }])
    assert out["count"] == 1

    draft = json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    ch = draft["channels"][0]

    assert not ch.get("live")
    assert ch["content"] == ["Die Hard", "Die Hard 2"]
    assert all(isinstance(item, str) for item in ch["content"])


# ── F12: country / mood / style compose kinds ──────────────────────────────────

def test_country_spec_resolves_titles(pr, seed):
    """kind=country resolves movies whose Country column contains the value (case-insensitive)."""
    seed([
        movie("French Film A", country="France"),
        movie("French Film B", country="france"),   # case-insensitive
        movie("German Film", country="Germany"),
    ])
    out = _compose(pr, [{"kind": "country", "value": "France"}])
    assert out["count"] == 1
    assert out["channels"][0]["items"] == 2


def test_country_multi_value_row(pr, seed):
    """A co-production row with two country values is matched by either country."""
    seed([
        movie("Co-prod 1", country="France|Italy"),
        movie("Co-prod 2", country="France|Italy"),
        movie("Co-prod 3", country="France|Italy"),
    ])
    out = _compose(pr, [{"kind": "country", "value": "Italy"}])
    assert out["count"] == 1
    assert out["channels"][0]["items"] == 3


def test_country_auto_name(pr, seed):
    """_auto_name for country returns '<value> Cinema'."""
    seed([movie(f"F{i}", country="Japan") for i in range(3)])
    out = _compose(pr, [{"kind": "country", "value": "Japan"}])
    assert out["channels"][0]["name"] == "Japan Cinema"


def test_country_custom_name_overrides(pr, seed):
    """Providing a name in the spec overrides the auto-name."""
    seed([movie(f"F{i}", country="Japan") for i in range(3)])
    out = _compose(pr, [{"kind": "country", "value": "Japan", "name": "J-Cinema"}])
    assert out["channels"][0]["name"] == "J-Cinema"


def test_country_no_match_skipped(pr, seed):
    """A country spec with no matching movies is skipped."""
    seed([movie("Film", country="France")])
    out = _compose(pr, [{"kind": "country", "value": "Spain"}])
    assert out["count"] == 0
    assert out["skipped"][0]["reason"] == "no matching titles"


def test_mood_spec_resolves_titles(pr, seed):
    """kind=mood resolves movies whose Mood column contains the value (case-insensitive)."""
    seed([
        movie("Upbeat 1", mood="Feel-Good"),
        movie("Upbeat 2", mood="feel-good"),   # case-insensitive
        movie("Dark 1", mood="Dark"),
    ])
    out = _compose(pr, [{"kind": "mood", "value": "Feel-Good"}])
    assert out["count"] == 1
    assert out["channels"][0]["items"] == 2


def test_mood_auto_name(pr, seed):
    """_auto_name for mood returns the value directly."""
    seed([movie(f"F{i}", mood="Suspenseful") for i in range(3)])
    out = _compose(pr, [{"kind": "mood", "value": "Suspenseful"}])
    assert out["channels"][0]["name"] == "Suspenseful"


def test_mood_no_match_skipped(pr, seed):
    """A mood spec with no matching movies is skipped."""
    seed([movie("Film", mood="Feel-Good")])
    out = _compose(pr, [{"kind": "mood", "value": "Spooky"}])
    assert out["count"] == 0
    assert out["skipped"][0]["reason"] == "no matching titles"


def test_style_spec_resolves_titles(pr, seed):
    """kind=style resolves movies whose Style column contains the value (case-insensitive)."""
    seed([
        movie("Noir 1", style="Film Noir"),
        movie("Noir 2", style="film noir"),   # case-insensitive
        movie("Screwball", style="Screwball Comedy"),
    ])
    out = _compose(pr, [{"kind": "style", "value": "Film Noir"}])
    assert out["count"] == 1
    assert out["channels"][0]["items"] == 2


def test_style_auto_name(pr, seed):
    """_auto_name for style returns the value directly."""
    seed([movie(f"F{i}", style="Spaghetti Western") for i in range(3)])
    out = _compose(pr, [{"kind": "style", "value": "Spaghetti Western"}])
    assert out["channels"][0]["name"] == "Spaghetti Western"


def test_style_no_match_skipped(pr, seed):
    """A style spec with no matching movies is skipped."""
    seed([movie("Film", style="Film Noir")])
    out = _compose(pr, [{"kind": "style", "value": "Mockumentary"}])
    assert out["count"] == 0
    assert out["skipped"][0]["reason"] == "no matching titles"


def test_country_mood_style_map_to_movie_category(pr, seed):
    """country/mood/style kinds all land in the movie category (tight-packed with genre channels)."""
    seed([
        movie("French 1", country="France"),
        movie("French 2", country="France"),
        movie("French 3", country="France"),
        movie("Funny", genres="Comedy"),
    ])
    out = _compose(pr, [
        {"kind": "genre", "genre": "Comedy"},
        {"kind": "country", "value": "France"},
    ])
    assert out["count"] == 2
    numbers = sorted(c["number"] for c in out["channels"])
    # Both in movie category → consecutive numbers starting at 1.
    assert numbers == [1, 2]


def test_country_missing_column_returns_empty(pr, seed):
    """When the CSV has no Country column (old export), country spec finds nothing and is skipped."""
    import csv as _csv
    from conftest import CSV_FIELDS
    path = pr._test_data_dir / "plex_library.csv"
    old_fields = [f for f in CSV_FIELDS if f not in ("Country", "Mood", "Style")]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=old_fields)
        w.writeheader()
        w.writerow({"Title": "Old Film", "Year": "2000", "Type": "Movie", "Rating": "PG",
                    "Genres": "Drama", "Director": "", "Studio": "", "Actors": "",
                    "Seasons": "", "Episodes": ""})
    out = _compose(pr, [{"kind": "country", "value": "France"}])
    assert out["count"] == 0
    assert out["skipped"][0]["reason"] == "no matching titles"
