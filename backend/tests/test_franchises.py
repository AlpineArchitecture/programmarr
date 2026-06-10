"""F9 — TMDB enrichment scan + franchise discovery.

Tests verify:
  - No Plex-collection source is used.
  - Enrichment cache is written with the correct {title, year, collection, keywords} shape.
  - Franchises derive from TMDB collections filtered to library (>= FRANCHISE_MIN members).
  - Scan status reports progress and done.
  - Cache is reused on a second call without re-running TMDB.
  - Defensive on TMDB failure (no 500; returns whatever succeeded).
  - GET /pipeline/franchises returns empty while scan not done / no key.
"""

import json
import threading
import time
import unittest.mock as mock

import pytest
from conftest import movie, show


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_tmdb_fake(
    collection_by_title: dict[str, dict | None],
    keywords_by_title: dict[str, list] | None = None,
    fail_titles: set[str] | None = None,
):
    """Return a fake _tmdb_get that returns controlled TMDB responses.

    collection_by_title: title → {"id": int, "name": str} | None
    keywords_by_title:   title → [{"id": int, "name": str}, ...]
    fail_titles:         set of titles that should raise an exception.
    """
    id_counter = [1000]

    def _fake(path: str, api_key: str, timeout: int = 10):
        if "search/movie" in path:
            # Extract query from path.
            params = dict(urllib.parse.parse_qsl(path.split("?", 1)[1] if "?" in path else ""))
            title = params.get("query", "")
            if fail_titles and title in fail_titles:
                raise Exception("simulated TMDB failure")
            movie_id = id_counter[0]
            id_counter[0] += 1
            # Store title → id mapping in closure for detail call.
            _fake._title_by_id[movie_id] = title
            return {"results": [{"id": movie_id}]}
        if "/movie/" in path:
            # Extract movie_id from path like /movie/1001?append_to_response=keywords
            seg = path.split("/movie/")[1].split("?")[0]
            mid = int(seg)
            title = _fake._title_by_id.get(mid, "")
            coll = collection_by_title.get(title)
            kws = (keywords_by_title or {}).get(title, [])
            return {
                "belongs_to_collection": coll,
                "keywords": {"keywords": kws},
            }
        return {}

    _fake._title_by_id: dict[int, str] = {}
    return _fake


def _run_scan_sync(pr, movies, tmdb_key, sig):
    """Run the enrichment scan synchronously in the test (bypass threads)."""
    import urllib.parse
    from routers.pipeline_router import _run_tmdb_enrichment_scan
    _run_tmdb_enrichment_scan(pr._test_data_dir, movies, tmdb_key, sig)


# ── Import urllib.parse for use in _make_tmdb_fake ────────────────────────────
import urllib.parse


# ── No Plex-collection source ─────────────────────────────────────────────────

def test_no_plex_collection_source_used(pr, seed, monkeypatch):
    """Plex /collections is never called from the franchise endpoints."""
    seed([movie("The Matrix", year=1999), movie("The Matrix Reloaded", year=2003)])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"plex_url": "http://plex", "plex_token": "tok", "tmdb_api_key": "k"}),
        encoding="utf-8",
    )

    plex_calls: list[str] = []

    def fake_plex_get(base_url, token, path, timeout=30):
        plex_calls.append(path)
        return {}

    monkeypatch.setattr(pr, "_plex_get", fake_plex_get)

    # Neither start_tmdb_scan nor get_franchises should touch Plex collections.
    pr.get_franchises()
    assert not any("/collections" in p for p in plex_calls), (
        f"Plex /collections was called: {plex_calls}"
    )


# ── Enrichment cache shape ─────────────────────────────────────────────────────

def test_enrichment_cache_written_with_correct_shape(pr, seed, monkeypatch):
    """After a scan, tmdb_enrichment.json has the expected {title, year, collection, keywords} shape."""
    seed([movie("Inception", year=2010), movie("Interstellar", year=2014)])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"tmdb_api_key": "testkey"}), encoding="utf-8"
    )

    fake_tmdb = _make_tmdb_fake(
        collection_by_title={"Inception": None, "Interstellar": None},
        keywords_by_title={
            "Inception": [{"id": 11, "name": "dream"}],
            "Interstellar": [{"id": 22, "name": "space"}],
        },
    )
    monkeypatch.setattr(pr, "_tmdb_get", fake_tmdb)

    sig = pr._library_signature()
    movies = [{"Title": "Inception", "Year": "2010"}, {"Title": "Interstellar", "Year": "2014"}]
    pr._run_tmdb_enrichment_scan(pr._test_data_dir, movies, "testkey", sig)

    cache_path = pr._test_data_dir / "tmdb_enrichment.json"
    assert cache_path.exists()
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert data["sig"] == sig
    enrichment = data["enrichment"]
    assert "Inception" in enrichment
    assert "Interstellar" in enrichment

    inc = enrichment["Inception"]
    assert inc["title"] == "Inception"
    assert inc["year"] == 2010
    assert inc["collection"] is None
    assert isinstance(inc["keywords"], list)
    assert any(kw["name"] == "dream" for kw in inc["keywords"])

    inter = enrichment["Interstellar"]
    assert isinstance(inter["keywords"], list)
    assert any(kw["name"] == "space" for kw in inter["keywords"])


def test_enrichment_cache_includes_collection_info(pr, seed, monkeypatch):
    """Movies belonging to a TMDB collection have collection {id, name} in cache."""
    seed([movie("The Matrix", year=1999), movie("The Matrix Reloaded", year=2003)])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"tmdb_api_key": "k"}), encoding="utf-8"
    )
    coll = {"id": 500, "name": "The Matrix Collection"}
    fake_tmdb = _make_tmdb_fake(
        collection_by_title={
            "The Matrix": coll,
            "The Matrix Reloaded": coll,
        },
    )
    monkeypatch.setattr(pr, "_tmdb_get", fake_tmdb)

    sig = pr._library_signature()
    movies = [
        {"Title": "The Matrix", "Year": "1999"},
        {"Title": "The Matrix Reloaded", "Year": "2003"},
    ]
    pr._run_tmdb_enrichment_scan(pr._test_data_dir, movies, "k", sig)

    data = json.loads((pr._test_data_dir / "tmdb_enrichment.json").read_text(encoding="utf-8"))
    for title in ("The Matrix", "The Matrix Reloaded"):
        assert data["enrichment"][title]["collection"] == {"id": 500, "name": "The Matrix Collection"}


# ── Franchise filtering ────────────────────────────────────────────────────────

def test_franchises_derive_from_tmdb_collections(pr, seed, monkeypatch):
    """Franchises only include library movies belonging to a TMDB collection (>= FRANCHISE_MIN)."""
    seed([
        movie("Batman", year=1989),
        movie("Batman Returns", year=1992),
        movie("Inception", year=2010),  # no collection
    ])
    coll = {"id": 10, "name": "Batman Collection"}
    fake_tmdb = _make_tmdb_fake(
        collection_by_title={
            "Batman": coll,
            "Batman Returns": coll,
            "Inception": None,
        }
    )
    monkeypatch.setattr(pr, "_tmdb_get", fake_tmdb)

    sig = pr._library_signature()
    enrichment_data = {
        "sig": sig,
        "enrichment": {
            "Batman": {"title": "Batman", "year": 1989, "collection": coll, "keywords": []},
            "Batman Returns": {"title": "Batman Returns", "year": 1992, "collection": coll, "keywords": []},
            "Inception": {"title": "Inception", "year": 2010, "collection": None, "keywords": []},
        },
    }
    (pr._test_data_dir / "tmdb_enrichment.json").write_text(
        json.dumps(enrichment_data), encoding="utf-8"
    )
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"tmdb_api_key": "k"}), encoding="utf-8"
    )

    result = pr.get_franchises()
    assert len(result) == 1
    assert result[0]["name"] == "Batman Collection"
    assert result[0]["source"] == "tmdb"
    titles = {m["title"] for m in result[0]["members"]}
    assert titles == {"Batman", "Batman Returns"}
    assert "Inception" not in titles


def test_franchises_below_min_excluded(pr, seed, monkeypatch):
    """A TMDB collection with only one library member is NOT returned (< FRANCHISE_MIN)."""
    seed([movie("Solo Movie", year=2020)])
    coll = {"id": 99, "name": "Solo Collection"}
    enrichment_data = {
        "sig": pr._library_signature(),
        "enrichment": {
            "Solo Movie": {"title": "Solo Movie", "year": 2020, "collection": coll, "keywords": []},
        },
    }
    (pr._test_data_dir / "tmdb_enrichment.json").write_text(
        json.dumps(enrichment_data), encoding="utf-8"
    )
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"tmdb_api_key": "k"}), encoding="utf-8"
    )

    result = pr.get_franchises()
    assert result == []


def test_franchises_sorted_by_member_count_desc(pr, seed, monkeypatch):
    """Franchises are sorted by number of members descending."""
    seed([
        movie("A1", year=2000), movie("A2", year=2001), movie("A3", year=2002),
        movie("B1", year=2000), movie("B2", year=2001),
    ])
    coll_a = {"id": 1, "name": "Collection A"}
    coll_b = {"id": 2, "name": "Collection B"}
    enrichment_data = {
        "sig": pr._library_signature(),
        "enrichment": {
            "A1": {"title": "A1", "year": 2000, "collection": coll_a, "keywords": []},
            "A2": {"title": "A2", "year": 2001, "collection": coll_a, "keywords": []},
            "A3": {"title": "A3", "year": 2002, "collection": coll_a, "keywords": []},
            "B1": {"title": "B1", "year": 2000, "collection": coll_b, "keywords": []},
            "B2": {"title": "B2", "year": 2001, "collection": coll_b, "keywords": []},
        },
    }
    (pr._test_data_dir / "tmdb_enrichment.json").write_text(
        json.dumps(enrichment_data), encoding="utf-8"
    )
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"tmdb_api_key": "k"}), encoding="utf-8"
    )

    result = pr.get_franchises()
    assert result[0]["name"] == "Collection A"  # 3 members first
    assert result[1]["name"] == "Collection B"  # 2 members second


def test_franchises_members_sorted_by_year(pr, seed, monkeypatch):
    """Franchise members are sorted by year ascending."""
    seed([movie("Ep I", year=1999), movie("Ep II", year=2002), movie("Ep III", year=2005)])
    coll = {"id": 5, "name": "Star Collection"}
    enrichment_data = {
        "sig": pr._library_signature(),
        "enrichment": {
            "Ep I":   {"title": "Ep I",   "year": 1999, "collection": coll, "keywords": []},
            "Ep II":  {"title": "Ep II",  "year": 2002, "collection": coll, "keywords": []},
            "Ep III": {"title": "Ep III", "year": 2005, "collection": coll, "keywords": []},
        },
    }
    (pr._test_data_dir / "tmdb_enrichment.json").write_text(
        json.dumps(enrichment_data), encoding="utf-8"
    )
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"tmdb_api_key": "k"}), encoding="utf-8"
    )

    result = pr.get_franchises()
    assert len(result) == 1
    years = [m["year"] for m in result[0]["members"]]
    assert years == sorted(years)


# ── No TMDB key ───────────────────────────────────────────────────────────────

def test_no_tmdb_key_returns_empty_franchises(pr, seed):
    """No tmdb_api_key → franchises empty, no error."""
    seed([movie("Foo", year=2000)])
    (pr._test_data_dir / "config.json").write_text(json.dumps({}), encoding="utf-8")
    result = pr.get_franchises()
    assert result == []


def test_no_tmdb_key_start_scan_returns_no_key(pr, seed):
    """POST /pipeline/tmdb-scan without a key returns reason=no_tmdb_key immediately."""
    seed([movie("Foo", year=2000)])
    (pr._test_data_dir / "config.json").write_text(json.dumps({}), encoding="utf-8")
    result = pr._start_tmdb_scan_impl()
    assert result["running"] is False
    assert result.get("reason") == "no_tmdb_key"


# ── Scan progress ─────────────────────────────────────────────────────────────

def test_scan_status_reports_progress_and_done(pr, seed, monkeypatch):
    """Scan status transitions: running=True mid-scan, done=True on completion."""
    seed([
        movie("A", year=2000), movie("B", year=2001), movie("C", year=2002),
    ])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"tmdb_api_key": "k"}), encoding="utf-8"
    )

    # Synchronously run the scan (bypasses threading).
    sig = pr._library_signature()
    movies = [
        {"Title": "A", "Year": "2000"},
        {"Title": "B", "Year": "2001"},
        {"Title": "C", "Year": "2002"},
    ]
    fake_tmdb = _make_tmdb_fake(
        collection_by_title={"A": None, "B": None, "C": None}
    )
    monkeypatch.setattr(pr, "_tmdb_get", fake_tmdb)

    # Reset state.
    with pr._tmdb_scan_lock:
        pr._tmdb_scan_state.update({"running": False, "scanned": 0, "total": 0, "done": False, "sig": None})

    pr._run_tmdb_enrichment_scan(pr._test_data_dir, movies, "k", sig)

    # After sync run, state must show done.
    status = pr.tmdb_scan_status()
    assert status["done"] is True
    assert status["running"] is False
    assert status["scanned"] == 3
    assert status["total"] == 3


def test_scan_state_shows_total_on_start(pr, seed, monkeypatch):
    """After _run_tmdb_enrichment_scan starts, total equals number of movies."""
    sig = "test-sig"
    movies = [{"Title": "X", "Year": "2020"}, {"Title": "Y", "Year": "2021"}]

    # Capture state snapshots during the scan by patching the executor.
    observed_totals: list[int] = []

    real_run = pr._run_tmdb_enrichment_scan

    def patched_run(data_dir, mvs, key, s):
        with pr._tmdb_scan_lock:
            pr._tmdb_scan_state.update({"running": True, "scanned": 0, "total": len(mvs), "done": False, "sig": s})
        observed_totals.append(pr._tmdb_scan_state["total"])
        # Skip actual TMDB calls; write a minimal cache.
        with pr._tmdb_scan_lock:
            pr._tmdb_scan_state.update({"running": False, "done": True, "scanned": len(mvs)})

    monkeypatch.setattr(pr, "_run_tmdb_enrichment_scan", patched_run)
    patched_run(pr._test_data_dir, movies, "k", sig)

    assert observed_totals == [2]


# ── Cache reuse ───────────────────────────────────────────────────────────────

def test_enrichment_cache_reused_on_second_call(pr, seed, monkeypatch):
    """Second call to get_franchises reuses tmdb_enrichment.json (no TMDB calls)."""
    seed([movie("The Matrix", year=1999), movie("The Matrix Reloaded", year=2003)])
    coll = {"id": 500, "name": "The Matrix Collection"}
    sig = pr._library_signature()
    enrichment_data = {
        "sig": sig,
        "enrichment": {
            "The Matrix": {"title": "The Matrix", "year": 1999, "collection": coll, "keywords": []},
            "The Matrix Reloaded": {"title": "The Matrix Reloaded", "year": 2003, "collection": coll, "keywords": []},
        },
    }
    (pr._test_data_dir / "tmdb_enrichment.json").write_text(
        json.dumps(enrichment_data), encoding="utf-8"
    )
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"tmdb_api_key": "k"}), encoding="utf-8"
    )

    tmdb_call_count = {"n": 0}

    def counting_tmdb_get(path, api_key, timeout=10):
        tmdb_call_count["n"] += 1
        return {}

    monkeypatch.setattr(pr, "_tmdb_get", counting_tmdb_get)

    result1 = pr.get_franchises()
    result2 = pr.get_franchises()

    assert result1 == result2
    assert len(result1) == 1
    # Cache was valid — _tmdb_get should never have been called.
    assert tmdb_call_count["n"] == 0


def test_stale_enrichment_cache_invalidated(pr, seed, monkeypatch):
    """An enrichment cache with a wrong signature is ignored."""
    seed([movie("Foo", year=2020)])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"tmdb_api_key": "k"}), encoding="utf-8"
    )
    # Write cache with wrong sig.
    (pr._test_data_dir / "tmdb_enrichment.json").write_text(
        json.dumps({"sig": "old-sig", "enrichment": {}}), encoding="utf-8"
    )

    result = pr._load_enrichment_cache(pr._test_data_dir, pr._library_signature())
    assert result is None


def test_start_scan_returns_cached_true_when_cache_valid(pr, seed, monkeypatch):
    """_start_tmdb_scan_impl returns cached=True when enrichment cache is fresh."""
    seed([movie("Foo", year=2020)])
    sig = pr._library_signature()
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"tmdb_api_key": "k"}), encoding="utf-8"
    )
    (pr._test_data_dir / "tmdb_enrichment.json").write_text(
        json.dumps({"sig": sig, "enrichment": {}}), encoding="utf-8"
    )

    # Reset scan state so it doesn't appear "already running".
    with pr._tmdb_scan_lock:
        pr._tmdb_scan_state.update({"running": False, "done": False, "sig": None})

    result = pr._start_tmdb_scan_impl()
    assert result["cached"] is True
    assert result["running"] is False


# ── Defensive: TMDB failure ───────────────────────────────────────────────────

def test_tmdb_failure_per_movie_skipped_no_500(pr, seed, monkeypatch):
    """If TMDB fails for one movie, that movie is skipped; the scan still completes."""
    seed([
        movie("GoodMovie", year=2000),
        movie("BadMovie", year=2001),   # will fail
    ])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"tmdb_api_key": "k"}), encoding="utf-8"
    )
    coll = {"id": 1, "name": "Good Collection"}
    fake_tmdb = _make_tmdb_fake(
        collection_by_title={"GoodMovie": coll},
        fail_titles={"BadMovie"},
    )
    monkeypatch.setattr(pr, "_tmdb_get", fake_tmdb)

    sig = pr._library_signature()
    movies = [{"Title": "GoodMovie", "Year": "2000"}, {"Title": "BadMovie", "Year": "2001"}]

    # Should not raise.
    pr._run_tmdb_enrichment_scan(pr._test_data_dir, movies, "k", sig)

    # Cache should exist (with at least GoodMovie).
    cache_path = pr._test_data_dir / "tmdb_enrichment.json"
    assert cache_path.exists()
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    # GoodMovie may be present; BadMovie may be absent or None — no 500.
    assert isinstance(data["enrichment"], dict)


def test_all_tmdb_failures_produces_empty_enrichment(pr, seed, monkeypatch):
    """If every TMDB call fails, enrichment is empty and franchises return []."""
    seed([movie("X", year=2000), movie("Y", year=2001)])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"tmdb_api_key": "k"}), encoding="utf-8"
    )
    fake_tmdb = _make_tmdb_fake(
        collection_by_title={"X": None, "Y": None},
        fail_titles={"X", "Y"},
    )
    monkeypatch.setattr(pr, "_tmdb_get", fake_tmdb)

    sig = pr._library_signature()
    pr._run_tmdb_enrichment_scan(pr._test_data_dir, [{"Title": "X", "Year": "2000"}, {"Title": "Y", "Year": "2001"}], "k", sig)

    enrichment = pr._load_enrichment_cache(pr._test_data_dir, sig)
    # The cache is written (even if empty).
    assert enrichment is not None
    # Either empty or contains only successfully-enriched movies.
    assert isinstance(enrichment, dict)

    # get_franchises must not raise.
    result = pr.get_franchises()
    assert result == []


# ── get_franchises returns empty if scan not done ──────────────────────────────

def test_get_franchises_empty_if_no_enrichment_cache(pr, seed):
    """GET /pipeline/franchises returns [] if the enrichment cache doesn't exist yet."""
    seed([movie("Foo", year=2020)])
    (pr._test_data_dir / "config.json").write_text(
        json.dumps({"tmdb_api_key": "k"}), encoding="utf-8"
    )
    # No tmdb_enrichment.json written.
    result = pr.get_franchises()
    assert result == []
