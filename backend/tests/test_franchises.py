"""GET /pipeline/franchises — Plex collection children + TMDB enrichment + cache."""

import json
import unittest.mock as mock

import pytest
from conftest import movie, show


# ── helpers ────────────────────────────────────────────────────────────────────

def _plex_sections_response(sections):
    return {"MediaContainer": {"Directory": sections}}


def _plex_collections_response(collections):
    return {"MediaContainer": {"Metadata": collections}}


def _plex_children_response(children):
    return {"MediaContainer": {"Metadata": children}}


# ── Plex-source tests ──────────────────────────────────────────────────────────

def test_plex_franchise_members_filtered_to_library(pr, seed, monkeypatch):
    """Only members whose titles are present in plex_library.csv survive."""
    seed([
        movie("The Matrix", year=1999),
        movie("The Matrix Reloaded", year=2003),
        # "The Matrix Revolutions" NOT in library
    ])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"plex_url": "http://plex", "plex_token": "tok"}),
        encoding="utf-8",
    )

    def fake_plex_get(base_url, token, path, timeout=30):
        if path == "/library/sections":
            return _plex_sections_response([{"key": "1", "title": "Movies"}])
        if "/collections" in path:
            return _plex_collections_response([
                {"ratingKey": "99", "title": "The Matrix Collection", "childCount": "3"},
            ])
        if "/metadata/99/children" in path:
            return _plex_children_response([
                {"title": "The Matrix", "year": "1999"},
                {"title": "The Matrix Reloaded", "year": "2003"},
                {"title": "The Matrix Revolutions", "year": "2003"},
            ])
        return {}

    monkeypatch.setattr(pr, "_plex_get", fake_plex_get)
    result = pr.get_franchises()
    assert len(result) == 1
    names = [m["title"] for m in result[0]["members"]]
    assert "The Matrix" in names
    assert "The Matrix Reloaded" in names
    assert "The Matrix Revolutions" not in names


def test_plex_source_works_without_tmdb_key(pr, seed, monkeypatch):
    """No tmdb_api_key in config → Plex-only franchises returned, no error."""
    seed([movie("Batman", year=1989), movie("Batman Returns", year=1992)])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"plex_url": "http://plex", "plex_token": "tok"}),
        encoding="utf-8",
    )

    def fake_plex_get(base_url, token, path, timeout=30):
        if path == "/library/sections":
            return _plex_sections_response([{"key": "1", "title": "Movies"}])
        if "/collections" in path:
            return _plex_collections_response([
                {"ratingKey": "10", "title": "Batman Collection"},
            ])
        if "/metadata/10/children" in path:
            return _plex_children_response([
                {"title": "Batman", "year": "1989"},
                {"title": "Batman Returns", "year": "1992"},
            ])
        return {}

    monkeypatch.setattr(pr, "_plex_get", fake_plex_get)
    result = pr.get_franchises()
    assert len(result) == 1
    assert result[0]["source"] == "plex"
    assert result[0]["name"] == "Batman Collection"


def test_plex_franchise_members_sorted_by_year(pr, seed, monkeypatch):
    """Plex franchise members are sorted by year ascending."""
    seed([
        movie("Episode III", year=2005),
        movie("Episode I", year=1999),
        movie("Episode II", year=2002),
    ])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"plex_url": "http://plex", "plex_token": "tok"}),
        encoding="utf-8",
    )

    def fake_plex_get(base_url, token, path, timeout=30):
        if path == "/library/sections":
            return _plex_sections_response([{"key": "1", "title": "Movies"}])
        if "/collections" in path:
            return _plex_collections_response([
                {"ratingKey": "20", "title": "Prequel Trilogy"},
            ])
        if "/metadata/20/children" in path:
            return _plex_children_response([
                {"title": "Episode III", "year": "2005"},
                {"title": "Episode I", "year": "1999"},
                {"title": "Episode II", "year": "2002"},
            ])
        return {}

    monkeypatch.setattr(pr, "_plex_get", fake_plex_get)
    result = pr.get_franchises()
    assert len(result) == 1
    years = [m["year"] for m in result[0]["members"]]
    assert years == sorted(years)


def test_plex_franchise_spans_tv_and_movies(pr, seed, monkeypatch):
    """A Plex collection can mix movies and TV; both are returned when in library."""
    seed([
        movie("Firefly: Serenity", year=2005),
        show("Firefly", episodes=14),
    ])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"plex_url": "http://plex", "plex_token": "tok"}),
        encoding="utf-8",
    )

    def fake_plex_get(base_url, token, path, timeout=30):
        if path == "/library/sections":
            return _plex_sections_response([{"key": "1", "title": "Mixed"}])
        if "/collections" in path:
            return _plex_collections_response([
                {"ratingKey": "30", "title": "Firefly Franchise"},
            ])
        if "/metadata/30/children" in path:
            return _plex_children_response([
                {"title": "Firefly", "year": "2002"},
                {"title": "Firefly: Serenity", "year": "2005"},
            ])
        return {}

    monkeypatch.setattr(pr, "_plex_get", fake_plex_get)
    result = pr.get_franchises()
    assert len(result) == 1
    member_titles = {m["title"] for m in result[0]["members"]}
    assert "Firefly: Serenity" in member_titles
    assert "Firefly" in member_titles


def test_no_plex_configured_returns_empty(pr, seed):
    """No plex_url/token → empty list, no error."""
    seed([movie("Foo", year=2000)])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({}), encoding="utf-8"
    )
    result = pr.get_franchises()
    assert result == []


def test_plex_failure_returns_empty_list(pr, seed, monkeypatch):
    """Plex network failure → returns empty list rather than 500."""
    import urllib.error

    seed([movie("Foo", year=2000)])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"plex_url": "http://plex", "plex_token": "tok"}),
        encoding="utf-8",
    )

    def fail_plex_get(base_url, token, path, timeout=30):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(pr, "_plex_get", fail_plex_get)
    result = pr.get_franchises()
    assert result == []


# ── TMDB de-dupe tests ─────────────────────────────────────────────────────────

def test_tmdb_dedupes_against_plex_names(pr, seed, monkeypatch):
    """TMDB collection already covered by a Plex collection by same name is dropped."""
    seed([
        movie("The Matrix", year=1999),
        movie("The Matrix Reloaded", year=2003),
    ])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({
            "plex_url": "http://plex", "plex_token": "tok",
            "tmdb_api_key": "tmdb123",
        }),
        encoding="utf-8",
    )

    def fake_plex_get(base_url, token, path, timeout=30):
        if path == "/library/sections":
            return _plex_sections_response([{"key": "1", "title": "Movies"}])
        if "/collections" in path:
            return _plex_collections_response([
                {"ratingKey": "99", "title": "The Matrix Collection"},
            ])
        if "/metadata/99/children" in path:
            return _plex_children_response([
                {"title": "The Matrix", "year": "1999"},
                {"title": "The Matrix Reloaded", "year": "2003"},
            ])
        return {}

    monkeypatch.setattr(pr, "_plex_get", fake_plex_get)

    # TMDB also finds "The Matrix Collection" — should be de-duped.
    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "search/movie" in url:
            body = json.dumps({"results": [{"id": 1001}]}).encode()
        elif "/movie/1001" in url:
            body = json.dumps({"belongs_to_collection": {"id": 500, "name": "The Matrix Collection"}}).encode()
        else:
            body = b"{}"

        cm = mock.MagicMock()
        cm.__enter__ = lambda s: s
        cm.__exit__ = mock.MagicMock(return_value=False)
        cm.read = lambda: body
        return cm

    monkeypatch.setattr(pr.urllib.request, "urlopen", fake_urlopen)

    result = pr.get_franchises()
    # Only the Plex franchise; TMDB duplicate dropped.
    matrix_entries = [f for f in result if "matrix" in f["name"].lower()]
    assert len(matrix_entries) == 1
    assert matrix_entries[0]["source"] == "plex"


def test_tmdb_failure_returns_plex_results(pr, seed, monkeypatch):
    """TMDB HTTP failure → Plex-only franchises returned, no 500."""
    seed([movie("Batman", year=1989), movie("Batman Returns", year=1992)])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({
            "plex_url": "http://plex", "plex_token": "tok",
            "tmdb_api_key": "tmdb123",
        }),
        encoding="utf-8",
    )

    def fake_plex_get(base_url, token, path, timeout=30):
        if path == "/library/sections":
            return _plex_sections_response([{"key": "1", "title": "Movies"}])
        if "/collections" in path:
            return _plex_collections_response([
                {"ratingKey": "10", "title": "Batman Collection"},
            ])
        if "/metadata/10/children" in path:
            return _plex_children_response([
                {"title": "Batman", "year": "1989"},
                {"title": "Batman Returns", "year": "1992"},
            ])
        return {}

    monkeypatch.setattr(pr, "_plex_get", fake_plex_get)

    # TMDB fails for every request.
    import urllib.error as _ue

    def fail_urlopen(req, timeout=None):
        raise _ue.URLError("tmdb down")

    monkeypatch.setattr(pr.urllib.request, "urlopen", fail_urlopen)

    result = pr.get_franchises()
    # Should get Plex results back.
    assert len(result) == 1
    assert result[0]["source"] == "plex"


# ── Cache tests ────────────────────────────────────────────────────────────────

def test_cache_written_and_reused(pr, seed, monkeypatch):
    """After first call, cache file is written and a second call reuses it (no Plex call)."""
    seed([movie("Foo", year=2000), movie("Bar", year=2001)])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"plex_url": "http://plex", "plex_token": "tok"}),
        encoding="utf-8",
    )

    plex_call_count = {"n": 0}

    def counting_plex_get(base_url, token, path, timeout=30):
        plex_call_count["n"] += 1
        if path == "/library/sections":
            return _plex_sections_response([{"key": "1", "title": "Movies"}])
        if "/collections" in path:
            return _plex_collections_response([
                {"ratingKey": "55", "title": "Foo Collection"},
            ])
        if "/metadata/55/children" in path:
            return _plex_children_response([
                {"title": "Foo", "year": "2000"},
                {"title": "Bar", "year": "2001"},
            ])
        return {}

    monkeypatch.setattr(pr, "_plex_get", counting_plex_get)

    # First call — should hit Plex and write cache.
    result1 = pr.get_franchises()
    assert len(result1) == 1
    cache_path = pr._test_data_dir / "franchise_cache.json"
    assert cache_path.exists()
    calls_after_first = plex_call_count["n"]
    assert calls_after_first > 0

    # Second call — should read cache, no new Plex calls.
    result2 = pr.get_franchises()
    assert result2 == result1
    assert plex_call_count["n"] == calls_after_first  # no additional calls


def test_refresh_bypasses_cache(pr, seed, monkeypatch):
    """?refresh=1 forces a re-scan even when cache is valid."""
    seed([movie("Foo", year=2000), movie("Bar", year=2001)])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"plex_url": "http://plex", "plex_token": "tok"}),
        encoding="utf-8",
    )

    plex_call_count = {"n": 0}

    def counting_plex_get(base_url, token, path, timeout=30):
        plex_call_count["n"] += 1
        if path == "/library/sections":
            return _plex_sections_response([{"key": "1", "title": "Movies"}])
        if "/collections" in path:
            return _plex_collections_response([])
        return {}

    monkeypatch.setattr(pr, "_plex_get", counting_plex_get)

    pr.get_franchises()
    calls_after_first = plex_call_count["n"]

    # Call again with refresh=True.
    pr.get_franchises(refresh=True)
    assert plex_call_count["n"] > calls_after_first


def test_stale_cache_invalidated_on_library_change(pr, seed, monkeypatch):
    """Cache with a different library signature triggers a full re-scan."""
    seed([movie("Foo", year=2000)])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"plex_url": "http://plex", "plex_token": "tok"}),
        encoding="utf-8",
    )

    # Pre-seed a cache with an old signature.
    (pr._test_data_dir / "franchise_cache.json").write_text(
        json.dumps({"sig": "old-sig-0", "franchises": [{"name": "Stale Franchise", "source": "plex", "members": []}]}),
        encoding="utf-8",
    )

    plex_calls = {"n": 0}

    def counting_plex_get(base_url, token, path, timeout=30):
        plex_calls["n"] += 1
        if path == "/library/sections":
            return _plex_sections_response([{"key": "1", "title": "Movies"}])
        if "/collections" in path:
            return _plex_collections_response([])
        return {}

    monkeypatch.setattr(pr, "_plex_get", counting_plex_get)

    result = pr.get_franchises()
    # Stale cache discarded; Plex was called again.
    assert plex_calls["n"] > 0
    # "Stale Franchise" should not appear (it wasn't in the fresh Plex response).
    assert not any(f["name"] == "Stale Franchise" for f in result)
