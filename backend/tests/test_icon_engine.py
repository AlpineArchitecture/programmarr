"""icon_engine unit tests — pure logic, all HTTP stubbed. No network."""

import icon_engine


# ── normalize_title ───────────────────────────────────────────────────────────

def test_normalize_strips_article_case_punctuation():
    assert icon_engine.normalize_title("The Matrix") == "matrix"
    assert icon_engine.normalize_title("Spider-Man: No Way Home") == "spiderman no way home"
    assert icon_engine.normalize_title("  A  Bug's   Life ") == "bugs life"
    assert icon_engine.normalize_title(None) == ""


# ── verified searches ─────────────────────────────────────────────────────────

def _stub_results(monkeypatch, results):
    monkeypatch.setattr(icon_engine, "http_get",
                        lambda url, timeout=15: {"results": results})


def test_search_tv_verified_skips_name_mismatch(monkeypatch):
    # The American Horror Story bug: first result must NOT win on rank alone.
    _stub_results(monkeypatch, [
        {"id": 1, "name": "American Horror Story"},
        {"id": 2, "name": "Horror"},
    ])
    assert icon_engine.search_tv_verified("Horror", "key") == 2


def test_search_tv_verified_none_when_no_match(monkeypatch):
    _stub_results(monkeypatch, [{"id": 1, "name": "American Horror Story"}])
    assert icon_engine.search_tv_verified("Horror", "key") is None


def test_search_tv_verified_accepts_original_name(monkeypatch):
    _stub_results(monkeypatch, [{"id": 9, "name": "La Casa de Papel",
                                 "original_name": "Money Heist"}])
    assert icon_engine.search_tv_verified("Money Heist", "key") == 9


def test_search_movie_verified_matches_title_or_original(monkeypatch):
    _stub_results(monkeypatch, [
        {"id": 5, "title": "Die Hard 2", "original_title": "Die Hard 2"},
        {"id": 6, "title": "Die Hard", "original_title": "Die Hard"},
    ])
    assert icon_engine.search_movie_verified("Die Hard", "key") == 6


def test_search_company_verified(monkeypatch):
    _stub_results(monkeypatch, [
        {"id": 3, "name": "HBO Films"},
        {"id": 4, "name": "HBO"},
    ])
    assert icon_engine.search_company_verified("HBO", "key") == 4


def test_searches_handle_empty_results(monkeypatch):
    _stub_results(monkeypatch, [])
    assert icon_engine.search_tv_verified("X", "key") is None
    assert icon_engine.search_movie_verified("X", "key") is None
    assert icon_engine.search_company_verified("X", "key") is None


# ── best_logo_path ────────────────────────────────────────────────────────────

def test_best_logo_prefers_english_then_votes():
    images = {"logos": [
        {"file_path": "/de.png", "iso_639_1": "de", "vote_average": 9},
        {"file_path": "/en-lo.png", "iso_639_1": "en", "vote_average": 1},
        {"file_path": "/en-hi.png", "iso_639_1": "en", "vote_average": 5},
    ]}
    assert icon_engine.best_logo_path(images) == "/en-hi.png"


def test_best_logo_none_when_no_logos():
    assert icon_engine.best_logo_path({"logos": []}) is None
