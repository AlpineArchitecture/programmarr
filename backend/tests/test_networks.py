"""F10 — TVmaze network scan + networks facet.

Tests verify:
  - Networks facet derives from TVmaze cache (NOT the Studio column).
  - Facet returns [] when the cache is absent (scan not done yet).
  - Background scan writes tvmaze_cache.json with the correct shape.
  - Scan status reports progress and done.
  - Cache is reused on a second call without re-running TVmaze.
  - Defensive on TVmaze failure (no crash; failed shows get null, scan continues).
  - compose kind=network resolves TV shows by TVmaze network (not Studio).
  - compose kind=network falls back to Studio column when cache is absent.
"""

import json
import threading
import time
import unittest.mock as mock

import pytest
from conftest import movie, show


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_tvmaze_fake(
    network_by_title: dict[str, str | None],
    fail_titles: set[str] | None = None,
):
    """Return a fake _tvmaze_get that returns controlled TVmaze responses.

    network_by_title: show title → network name string (or None for "no network").
    fail_titles: set of titles whose lookup should raise an exception.
    """
    def _fake(path: str, timeout: int = 8):
        # Decode the title from the singlesearch path.
        import urllib.parse
        if "singlesearch" in path:
            qs = path.split("?", 1)[1] if "?" in path else ""
            params = dict(urllib.parse.parse_qsl(qs))
            title = params.get("q", "")
            if fail_titles and title in fail_titles:
                raise Exception("simulated TVmaze failure")
            net_name = network_by_title.get(title)
            if net_name is None:
                # Title not found in map → simulate "no network"
                return {"network": None, "webChannel": None}
            return {"network": {"name": net_name}, "webChannel": None}
        return {}

    return _fake


def _run_scan_sync(pr, shows, sig, monkeypatch, fake_get):
    """Run the TVmaze scan synchronously in the test (bypass threads)."""
    from routers.pipeline_router import _run_tvmaze_scan
    monkeypatch.setattr("routers.pipeline_router._tvmaze_get", fake_get)
    _run_tvmaze_scan(pr._test_data_dir, shows, sig)


def _compose(pr, specs, start=1):
    req = pr.ComposeRequest(specs=[pr.CandidateSpec(**s) for s in specs], start=start)
    return pr.compose_channels(req)


# ── Networks facet from TVmaze cache ──────────────────────────────────────────

def test_networks_facet_empty_when_no_cache(pr, seed):
    """If the TVmaze cache is absent, networks facet returns [] (scan not done)."""
    seed([
        show("The Sopranos", studio="HBO"),
        show("The Wire", studio="HBO"),
        show("The Wire 2", studio="HBO"),
    ])
    f = pr.library_facets()
    # No tvmaze_cache.json → networks should be empty even though shows exist.
    assert f["networks"] == []


def test_networks_facet_uses_tvmaze_cache(pr, seed, monkeypatch):
    """Networks facet counts are derived from the TVmaze cache, not the Studio column."""
    seed([
        show("Show A", studio="WrongStudio"),
        show("Show B", studio="WrongStudio"),
        show("Show C", studio="WrongStudio"),
        show("Show D", studio="SomeOtherStudio"),
        show("Show E", studio="SomeOtherStudio"),
        show("Show F", studio="SomeOtherStudio"),
        # Tiny should be filtered out (below NETWORK_MIN=3)
        show("Show G", studio="Tiny"),
    ])
    sig = pr._library_signature()
    # Write a TVmaze cache directly — A/B/C → HBO, D/E/F → Netflix, G → Tiny
    cache = {
        "sig": sig,
        "networks": {
            "Show A": "HBO",
            "Show B": "HBO",
            "Show C": "HBO",
            "Show D": "Netflix",
            "Show E": "Netflix",
            "Show F": "Netflix",
            "Show G": "Tiny",
        },
    }
    (pr._test_data_dir / "tvmaze_cache.json").write_text(
        json.dumps(cache), encoding="utf-8"
    )
    f = pr.library_facets()
    by_value = {n["value"]: n["count"] for n in f["networks"]}
    assert by_value.get("HBO") == 3
    assert by_value.get("Netflix") == 3
    # Tiny has only 1 show — below NETWORK_MIN (3), must be absent.
    assert "Tiny" not in by_value
    # Studio column values (WrongStudio, SomeOtherStudio) must NOT appear.
    assert "WrongStudio" not in by_value
    assert "SomeOtherStudio" not in by_value


def test_networks_facet_stale_cache_returns_empty(pr, seed):
    """If the cache signature doesn't match the current library, treat as absent → []."""
    seed([show("Show A", studio="HBO"), show("Show B", studio="HBO"), show("Show C", studio="HBO")])
    # Write a cache with a stale signature.
    cache = {"sig": "0000000-0", "networks": {"Show A": "HBO", "Show B": "HBO", "Show C": "HBO"}}
    (pr._test_data_dir / "tvmaze_cache.json").write_text(
        json.dumps(cache), encoding="utf-8"
    )
    f = pr.library_facets()
    assert f["networks"] == []


def test_networks_facet_sorted_by_count_desc(pr, seed, monkeypatch):
    """Networks returned sorted by count descending."""
    seed(
        [show(f"HBO{i}", studio="HBO") for i in range(5)] +
        [show(f"Net{i}", studio="Netflix") for i in range(3)]
    )
    sig = pr._library_signature()
    networks_map = {f"HBO{i}": "HBO" for i in range(5)}
    networks_map.update({f"Net{i}": "Netflix" for i in range(3)})
    cache = {"sig": sig, "networks": networks_map}
    (pr._test_data_dir / "tvmaze_cache.json").write_text(
        json.dumps(cache), encoding="utf-8"
    )
    f = pr.library_facets()
    values = [n["value"] for n in f["networks"]]
    assert values.index("HBO") < values.index("Netflix")


def test_networks_facet_movie_rows_excluded(pr, seed, monkeypatch):
    """Movie rows do NOT contribute to the networks facet, even if the cache has them."""
    seed([
        movie("Film 1", studio="A24"),
        movie("Film 2", studio="A24"),
        movie("Film 3", studio="A24"),
        show("Show 1", studio="HBO"),
        show("Show 2", studio="HBO"),
        show("Show 3", studio="HBO"),
    ])
    sig = pr._library_signature()
    # Cache only has TV shows — movies are irrelevant.
    cache = {
        "sig": sig,
        "networks": {
            "Show 1": "HBO",
            "Show 2": "HBO",
            "Show 3": "HBO",
        },
    }
    (pr._test_data_dir / "tvmaze_cache.json").write_text(
        json.dumps(cache), encoding="utf-8"
    )
    f = pr.library_facets()
    by_value = {n["value"]: n["count"] for n in f["networks"]}
    assert "A24" not in by_value
    assert by_value.get("HBO") == 3


# ── TVmaze scan background runner ─────────────────────────────────────────────

def test_tvmaze_scan_writes_cache(pr, seed, monkeypatch):
    """_run_tvmaze_scan writes tvmaze_cache.json with correct shape."""
    seed([
        show("Breaking Bad"),
        show("Better Call Saul"),
    ])
    fake_get = _make_tvmaze_fake({
        "Breaking Bad": "AMC",
        "Better Call Saul": "AMC",
    })
    shows = [{"Title": "Breaking Bad", "Type": "TV"}, {"Title": "Better Call Saul", "Type": "TV"}]
    sig = pr._library_signature()
    _run_scan_sync(pr, shows, sig, monkeypatch, fake_get)

    cache_path = pr._test_data_dir / "tvmaze_cache.json"
    assert cache_path.exists()
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert data["sig"] == sig
    assert data["networks"]["Breaking Bad"] == "AMC"
    assert data["networks"]["Better Call Saul"] == "AMC"


def test_tvmaze_scan_defensive_on_failure(pr, seed, monkeypatch):
    """Scan continues and writes cache even when some lookups fail; failed shows get null."""
    seed([show("Good Show"), show("Bad Show"), show("Another Good Show")])
    fake_get = _make_tvmaze_fake(
        {"Good Show": "HBO", "Another Good Show": "HBO"},
        fail_titles={"Bad Show"},
    )
    shows = [
        {"Title": "Good Show", "Type": "TV"},
        {"Title": "Bad Show", "Type": "TV"},
        {"Title": "Another Good Show", "Type": "TV"},
    ]
    sig = pr._library_signature()
    _run_scan_sync(pr, shows, sig, monkeypatch, fake_get)

    cache_path = pr._test_data_dir / "tvmaze_cache.json"
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert data["networks"].get("Good Show") == "HBO"
    assert data["networks"].get("Another Good Show") == "HBO"
    # Bad Show failed — should be None (not crash the scan).
    assert data["networks"].get("Bad Show") is None


def test_tvmaze_scan_state_updates(pr, seed, monkeypatch):
    """Scan state reports running=True during scan and done=True after."""
    import routers.pipeline_router as module

    seed([show("Show A"), show("Show B")])
    fake_get = _make_tvmaze_fake({"Show A": "HBO", "Show B": "NBC"})
    shows = [{"Title": "Show A", "Type": "TV"}, {"Title": "Show B", "Type": "TV"}]
    sig = pr._library_signature()

    # Reset state.
    with module._tvmaze_scan_lock:
        module._tvmaze_scan_state.update(
            {"running": False, "scanned": 0, "total": 0, "done": False, "sig": None}
        )

    _run_scan_sync(pr, shows, sig, monkeypatch, fake_get)

    with module._tvmaze_scan_lock:
        state = dict(module._tvmaze_scan_state)

    assert state["done"] is True
    assert state["running"] is False
    assert state["scanned"] == 2


def test_tvmaze_scan_cache_reuse(pr, seed, monkeypatch):
    """_start_tvmaze_scan_impl returns cached=True and does NOT re-run if cache is valid."""
    import routers.pipeline_router as module

    seed([show("The Wire"), show("The Sopranos"), show("The Wire 2")])
    sig = pr._library_signature()
    # Pre-write a valid cache.
    cache = {"sig": sig, "networks": {"The Wire": "HBO", "The Sopranos": "HBO", "The Wire 2": "HBO"}}
    (pr._test_data_dir / "tvmaze_cache.json").write_text(
        json.dumps(cache), encoding="utf-8"
    )

    call_count = {"n": 0}
    original_get = module._tvmaze_get
    def fake_get(*args, **kwargs):
        call_count["n"] += 1
        return original_get(*args, **kwargs)

    monkeypatch.setattr(module, "_tvmaze_get", fake_get)
    result = module._start_tvmaze_scan_impl(refresh=False)

    assert result["cached"] is True
    assert result["running"] is False
    assert call_count["n"] == 0  # No HTTP calls — cache was reused.


def test_tvmaze_scan_status_endpoint(pr, seed, monkeypatch):
    """tvmaze_scan_status returns the correct shape."""
    import routers.pipeline_router as module

    with module._tvmaze_scan_lock:
        module._tvmaze_scan_state.update(
            {"running": True, "scanned": 5, "total": 20, "done": False, "sig": "test"}
        )

    status = module.tvmaze_scan_status()
    assert status["running"] is True
    assert status["scanned"] == 5
    assert status["total"] == 20
    assert status["done"] is False

    # Reset.
    with module._tvmaze_scan_lock:
        module._tvmaze_scan_state.update(
            {"running": False, "scanned": 0, "total": 0, "done": False, "sig": None}
        )


def test_tvmaze_scan_no_csv_returns_early(pr, monkeypatch):
    """_start_tvmaze_scan_impl returns no_csv reason if plex_library.csv is absent."""
    import routers.pipeline_router as module
    result = module._start_tvmaze_scan_impl()
    assert result["running"] is False
    assert result["cached"] is False
    assert result.get("reason") == "no_csv"


# ── compose network kind uses TVmaze cache ─────────────────────────────────────

def test_compose_network_uses_tvmaze_cache(pr, seed, monkeypatch):
    """compose kind=network resolves shows by TVmaze network when cache is present."""
    seed([
        show("The Sopranos", studio="WrongStudio"),
        show("The Wire", studio="WrongStudio"),
        show("Breaking Bad", studio="SomeOther"),
        movie("HBO Film", studio="HBO"),  # movie rows must never appear
    ])
    sig = pr._library_signature()
    cache = {
        "sig": sig,
        "networks": {
            "The Sopranos": "HBO",
            "The Wire": "HBO",
            "Breaking Bad": "AMC",
        },
    }
    (pr._test_data_dir / "tvmaze_cache.json").write_text(
        json.dumps(cache), encoding="utf-8"
    )
    out = _compose(pr, [{"kind": "network", "value": "HBO"}])
    assert out["count"] == 1
    draft = json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    content = set(draft["channels"][0]["content"])
    assert content == {"The Sopranos", "The Wire"}
    # AMC show and movie must not appear.
    assert "Breaking Bad" not in content
    assert "HBO Film" not in content


def test_compose_network_case_insensitive_with_cache(pr, seed, monkeypatch):
    """Network value matching is case-insensitive when using the TVmaze cache."""
    seed([
        show("Show A"),
        show("Show B"),
        show("Show C"),
    ])
    sig = pr._library_signature()
    cache = {"sig": sig, "networks": {"Show A": "hbo", "Show B": "HBO", "Show C": "Hbo"}}
    (pr._test_data_dir / "tvmaze_cache.json").write_text(
        json.dumps(cache), encoding="utf-8"
    )
    out = _compose(pr, [{"kind": "network", "value": "HBO"}])
    assert out["count"] == 1
    assert out["channels"][0]["items"] == 3


def test_compose_network_fallback_to_studio_when_no_cache(pr, seed):
    """compose kind=network falls back to Studio column when TVmaze cache is absent."""
    seed([
        show("Show A", studio="HBO"),
        show("Show B", studio="HBO"),
        show("Show C", studio="HBO"),
        show("Show D", studio="AMC"),
    ])
    # No cache file — must fall back to Studio.
    out = _compose(pr, [{"kind": "network", "value": "HBO"}])
    assert out["count"] == 1
    draft = json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    content = set(draft["channels"][0]["content"])
    assert content == {"Show A", "Show B", "Show C"}


def test_compose_network_no_match_skipped_with_cache(pr, seed, monkeypatch):
    """compose kind=network with cache: skips if no TVmaze network matches."""
    seed([show("Orphan Show", studio="HBO")])
    sig = pr._library_signature()
    cache = {"sig": sig, "networks": {"Orphan Show": "AMC"}}
    (pr._test_data_dir / "tvmaze_cache.json").write_text(
        json.dumps(cache), encoding="utf-8"
    )
    out = _compose(pr, [{"kind": "network", "value": "HBO"}])
    assert out["count"] == 0
    assert out["skipped"][0]["reason"] == "no matching titles"
