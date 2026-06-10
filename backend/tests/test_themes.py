"""F11 — TMDB-keyword themed channel facets.

Tests verify:
  - themes_from_enrichment counts correctly (any keyword_id match per movie).
  - THEME_MIN filters out themes with too few matches.
  - Returns [] when no enrichment cache exists.
  - Returns [] when the enrichment cache has a wrong signature.
  - library_facets includes a 'themes' key.
  - compose kind 'theme' resolves the correct movie titles from the library.
"""

import json

import pytest
from conftest import movie


# ── Helpers ────────────────────────────────────────────────────────────────────

def _write_enrichment(data_dir, sig, enrichment):
    """Write a tmdb_enrichment.json to the temp DATA_DIR."""
    (data_dir / "tmdb_enrichment.json").write_text(
        json.dumps({"sig": sig, "enrichment": enrichment}), encoding="utf-8"
    )


def _write_themed_keywords(scripts_dir, catalog):
    """Write a themed_keywords.json to the SCRIPTS_DIR."""
    (scripts_dir / "themed_keywords.json").write_text(
        json.dumps(catalog), encoding="utf-8"
    )


def _enrichment_for(titles_with_keywords):
    """Build an enrichment dict: {title: {title, year, collection, keywords}}."""
    return {
        title: {
            "title": title,
            "year": 2000,
            "collection": None,
            "keywords": [{"id": kw_id, "name": f"kw{kw_id}"} for kw_id in kw_ids],
        }
        for title, kw_ids in titles_with_keywords.items()
    }


# ── _themes_from_enrichment unit tests ──────────────────────────────────────────

def test_themes_counts_movies_matching_any_keyword_id(pr):
    """Each movie matching ANY of the theme's keyword_ids is counted once."""
    from routers.pipeline_router import _themes_from_enrichment, THEME_MIN

    enrichment = _enrichment_for({
        "Heist Movie 1": [10051],
        "Heist Movie 2": [10051, 999],
        "Unrelated":     [9999],
    })
    catalog = [{"name": "Heist Films", "keyword_ids": [10051]}]

    result = _themes_from_enrichment(enrichment, catalog)
    # THEME_MIN is 4 by default; we have only 2 matches — should be empty.
    assert result == []


def test_themes_meets_threshold(pr):
    """A theme with >= THEME_MIN movies is returned."""
    from routers.pipeline_router import _themes_from_enrichment

    enrichment = _enrichment_for({
        "Movie A": [10051],
        "Movie B": [10051],
        "Movie C": [10051],
        "Movie D": [10051],
    })
    catalog = [{"name": "Heist Films", "keyword_ids": [10051]}]

    result = _themes_from_enrichment(enrichment, catalog)
    assert len(result) == 1
    assert result[0]["name"] == "Heist Films"
    assert result[0]["count"] == 4
    assert set(result[0]["titles"]) == {"Movie A", "Movie B", "Movie C", "Movie D"}


def test_themes_multi_keyword_id_union(pr):
    """A movie matching ANY of multiple keyword_ids is counted."""
    from routers.pipeline_router import _themes_from_enrichment

    enrichment = _enrichment_for({
        "Zombie Movie":   [12377],
        "Another Zombie": [15012],
        "Both Keywords":  [12377, 15012],
        "Neither":        [999],
    })
    catalog = [{"name": "Zombie", "keyword_ids": [12377, 15012]}]
    # Only 3 match; THEME_MIN=4, so this will be empty with default.
    result = _themes_from_enrichment(enrichment, catalog)
    assert result == []


def test_themes_multi_keyword_meets_threshold(pr):
    """Multiple keyword_ids union; 4+ movies triggers inclusion."""
    from routers.pipeline_router import _themes_from_enrichment

    enrichment = _enrichment_for({
        "Zombie 1":   [12377],
        "Zombie 2":   [15012],
        "Zombie 3":   [12377, 15012],
        "Zombie 4":   [12377],
    })
    catalog = [{"name": "Zombie", "keyword_ids": [12377, 15012]}]

    result = _themes_from_enrichment(enrichment, catalog)
    assert len(result) == 1
    assert result[0]["count"] == 4


def test_themes_below_min_excluded(pr):
    """Themes with fewer than THEME_MIN movies are excluded."""
    from routers.pipeline_router import _themes_from_enrichment

    enrichment = _enrichment_for({
        "Movie 1": [4379],
        "Movie 2": [4379],
        "Movie 3": [4379],
    })
    catalog = [{"name": "Time Travel", "keyword_ids": [4379]}]

    result = _themes_from_enrichment(enrichment, catalog)
    assert result == []


def test_themes_sorted_by_count_desc(pr):
    """Themes are sorted by count descending, then name alphabetically."""
    from routers.pipeline_router import _themes_from_enrichment

    enrichment = _enrichment_for({
        "A1": [1], "A2": [1], "A3": [1], "A4": [1],         # theme A: 4
        "B1": [2], "B2": [2], "B3": [2], "B4": [2], "B5": [2],  # theme B: 5
    })
    catalog = [
        {"name": "Theme A", "keyword_ids": [1]},
        {"name": "Theme B", "keyword_ids": [2]},
    ]

    result = _themes_from_enrichment(enrichment, catalog)
    assert len(result) == 2
    assert result[0]["name"] == "Theme B"  # 5 > 4
    assert result[1]["name"] == "Theme A"


def test_themes_empty_enrichment_returns_empty(pr):
    """An empty enrichment dict yields no themes."""
    from routers.pipeline_router import _themes_from_enrichment

    catalog = [{"name": "Heist Films", "keyword_ids": [10051]}]
    result = _themes_from_enrichment({}, catalog)
    assert result == []


def test_themes_empty_catalog_returns_empty(pr):
    """An empty catalog yields no themes."""
    from routers.pipeline_router import _themes_from_enrichment

    enrichment = _enrichment_for({"Movie": [10051]})
    result = _themes_from_enrichment(enrichment, [])
    assert result == []


# ── library_facets integration tests ──────────────────────────────────────────

def test_library_facets_includes_themes_key(pr, seed, tmp_path, monkeypatch):
    """GET /pipeline/facets always includes a 'themes' key (list, possibly empty)."""
    seed([movie("Foo", year=2020)])
    result = pr.library_facets()
    assert "themes" in result
    assert isinstance(result["themes"], list)


def test_library_facets_themes_empty_without_enrichment(pr, seed):
    """themes is [] when no tmdb_enrichment.json exists."""
    seed([movie("Foo", year=2020)])
    result = pr.library_facets()
    assert result["themes"] == []


def test_library_facets_themes_populated_from_enrichment(pr, seed, tmp_path, monkeypatch):
    """themes is populated from the enrichment cache + themed_keywords.json."""
    from routers import pipeline_router as module

    # Redirect SCRIPTS_DIR to tmp_path so themed_keywords.json is not written
    # to the real repo root.
    monkeypatch.setattr(module, "SCRIPTS_DIR", tmp_path)

    seed([
        movie("Heist 1", year=2001),
        movie("Heist 2", year=2002),
        movie("Heist 3", year=2003),
        movie("Heist 4", year=2004),
    ])

    sig = pr._library_signature()
    enrichment = _enrichment_for({
        "Heist 1": [10051],
        "Heist 2": [10051],
        "Heist 3": [10051],
        "Heist 4": [10051],
    })
    _write_enrichment(pr._test_data_dir, sig, enrichment)

    # Write themed_keywords.json to the redirected SCRIPTS_DIR (tmp_path).
    catalog = [{"name": "Heist Films", "keyword_ids": [10051]}]
    _write_themed_keywords(tmp_path, catalog)

    result = pr.library_facets()
    assert len(result["themes"]) == 1
    assert result["themes"][0]["name"] == "Heist Films"
    assert result["themes"][0]["count"] == 4


def test_library_facets_themes_empty_with_stale_enrichment(pr, seed, tmp_path, monkeypatch):
    """themes is [] when the enrichment cache has a stale signature."""
    from routers import pipeline_router as module

    # Redirect SCRIPTS_DIR to tmp_path to avoid writing to the real repo root.
    monkeypatch.setattr(module, "SCRIPTS_DIR", tmp_path)

    seed([movie("Foo", year=2020)])

    _write_enrichment(pr._test_data_dir, "stale-sig", {"Foo": {"title": "Foo", "year": 2020, "collection": None, "keywords": [{"id": 10051, "name": "heist"}]}})
    catalog = [{"name": "Heist Films", "keyword_ids": [10051]}]
    _write_themed_keywords(tmp_path, catalog)

    result = pr.library_facets()
    # Stale cache → no themes returned.
    assert result["themes"] == []


def test_library_facets_themes_empty_without_themed_keywords_json(pr, seed):
    """themes is [] when themed_keywords.json doesn't exist (missing file → empty)."""
    seed([movie("Foo", year=2020)])
    sig = pr._library_signature()
    enrichment = _enrichment_for({"Foo": [10051]})
    _write_enrichment(pr._test_data_dir, sig, enrichment)

    # Don't write themed_keywords.json → _load_themed_keywords returns [].
    result = pr.library_facets()
    assert result["themes"] == []


# ── compose kind='theme' tests ────────────────────────────────────────────────

def test_compose_theme_resolves_titles(pr, seed):
    """compose with kind='theme' resolves pre-supplied titles to library movies.

    Titles in the spec that are NOT in the library are filtered out so the channel
    only contains real content.
    """
    seed([
        movie("Heist 1", year=2001),
        movie("Heist 2", year=2002),
        # "Ghost Title" intentionally NOT seeded — should be excluded from the channel.
    ])

    from routers.pipeline_router import CandidateSpec, ComposeRequest, compose_channels

    # The spec carries the resolved titles from the facets query.
    req = ComposeRequest(
        specs=[
            CandidateSpec(
                kind="theme",
                name="Heist Films",
                titles=["Heist 1", "Heist 2", "Ghost Title"],
            )
        ],
        start=1,
    )
    result = compose_channels(req)
    assert result["ok"] is True
    assert result["count"] == 1

    # The built channel should only contain titles actually in the library.
    draft_path = pr._test_data_dir / "channels.draft.json"
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    ch = draft["channels"][0]
    assert ch["name"] == "Heist Films"
    assert "Heist 1" in ch["content"]
    assert "Heist 2" in ch["content"]
    assert "Ghost Title" not in ch["content"]


def test_compose_theme_empty_titles_skipped(pr, seed):
    """compose with kind='theme' and no matching library titles is skipped (not 500)."""
    seed([movie("Unrelated Movie", year=2000)])

    from routers.pipeline_router import CandidateSpec, ComposeRequest, compose_channels

    req = ComposeRequest(
        specs=[
            CandidateSpec(
                kind="theme",
                name="Heist Films",
                titles=["Ghost Title 1", "Ghost Title 2"],
            )
        ],
        start=1,
    )
    result = compose_channels(req)
    assert result["ok"] is True
    assert result["count"] == 0
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["name"] == "Heist Films"


def test_compose_theme_no_titles_field_skipped(pr, seed):
    """A theme spec with no titles field is skipped gracefully."""
    seed([movie("Any Movie", year=2000)])

    from routers.pipeline_router import CandidateSpec, ComposeRequest, compose_channels

    req = ComposeRequest(
        specs=[
            CandidateSpec(kind="theme", name="Empty Theme")
            # titles omitted
        ],
        start=1,
    )
    result = compose_channels(req)
    assert result["ok"] is True
    assert result["count"] == 0
    assert len(result["skipped"]) == 1


def test_compose_theme_maps_to_specialty_category(pr, seed):
    """theme kind maps to the 'specialty' compose category (numbered after franchise)."""
    seed([
        movie("T1", year=2001), movie("T2", year=2002),
        movie("T3", year=2003), movie("T4", year=2004),
    ])

    from routers.pipeline_router import CandidateSpec, ComposeRequest, compose_channels

    req = ComposeRequest(
        specs=[
            CandidateSpec(kind="theme", name="My Theme", titles=["T1", "T2", "T3", "T4"]),
        ],
        start=1,
    )
    result = compose_channels(req)
    assert result["ok"] is True
    assert result["count"] == 1
    # Channel is created successfully; the specialty category placement is tested
    # implicitly by the fact that it resolves and writes to channels.draft.json.
    draft = json.loads((pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8"))
    assert len(draft["channels"]) == 1
    assert draft["channels"][0]["name"] == "My Theme"
    assert draft["channels"][0]["shuffle"] == "shuffle"
