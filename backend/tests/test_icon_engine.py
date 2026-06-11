"""icon_engine unit tests — pure logic, all HTTP stubbed. No network."""

import json
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


# ── icon policy ───────────────────────────────────────────────────────────────

def test_badge_only_kinds_never_consult_tmdb():
    ch = {"name": "Horror", "content": ["It", "Scream", "The Thing"]}
    for kind in ("genre", "genre_decade", "blend", "tv_genre", "tv_movie_mix",
                 "theme", "country", "mood", "style", "programming_block",
                 "director", "actor"):
        assert icon_engine.icon_attempts(ch, kind) == [], kind


def test_unknown_multi_title_channel_is_badge_only():
    # The exact channel shape that used to produce false positives.
    ch = {"name": "Horror", "content": ["It", "Scream"]}
    assert icon_engine.icon_attempts(ch, None) == []


def test_solo_title_channel_tries_its_title_regardless_of_kind():
    ch = {"name": "Die Hard 24/7", "content": ["Die Hard"]}
    assert icon_engine.icon_attempts(ch, "genre") == [("tv", "Die Hard"),
                                                      ("movie", "Die Hard")]
    assert icon_engine.icon_attempts(ch, None) == [("tv", "Die Hard"),
                                                   ("movie", "Die Hard")]


def test_marathon_searches_tv_by_show_title():
    ch = {"name": "Seinfeld Marathon", "content": ["Seinfeld"]}
    assert icon_engine.icon_attempts(ch, "marathon") == [("tv", "Seinfeld"),
                                                         ("movie", "Seinfeld")]


def test_franchise_strips_suffix_and_tries_tv_then_movie():
    ch = {"name": "Star Wars Saga", "content": ["A New Hope", "Empire"]}
    assert icon_engine.icon_attempts(ch, "franchise") == [("tv", "Star Wars"),
                                                          ("movie", "Star Wars")]


def test_network_and_studio_search_company():
    ch = {"name": "HBO", "content": ["The Wire", "The Sopranos"]}
    assert icon_engine.icon_attempts(ch, "network") == [("company", "HBO")]
    ch2 = {"name": "A24", "content": ["Hereditary", "Lady Bird"]}
    assert icon_engine.icon_attempts(ch2, "studio") == [("company", "A24")]


def test_collection_ref_content_is_not_solo():
    ch = {"name": "Kometa Picks", "content": [{"collection": "Picks"}]}
    assert icon_engine.icon_attempts(ch, None) == []


# ── resolve_tmdb_logo ─────────────────────────────────────────────────────────

def test_resolve_walks_attempts_in_order(monkeypatch):
    monkeypatch.setattr(icon_engine, "search_tv_verified", lambda t, k: None)
    monkeypatch.setattr(icon_engine, "search_movie_verified",
                        lambda t, k: 42 if t == "Star Wars" else None)
    monkeypatch.setattr(icon_engine, "movie_logo_url",
                        lambda mid, k: "http://img/sw.png" if mid == 42 else None)
    attempts = [("tv", "Star Wars"), ("movie", "Star Wars")]
    assert icon_engine.resolve_tmdb_logo(attempts, "key") == "http://img/sw.png"


def test_resolve_verified_id_without_logo_falls_through(monkeypatch):
    monkeypatch.setattr(icon_engine, "search_tv_verified", lambda t, k: 7)
    monkeypatch.setattr(icon_engine, "tv_logo_url", lambda tid, k: None)
    monkeypatch.setattr(icon_engine, "search_movie_verified", lambda t, k: None)
    assert icon_engine.resolve_tmdb_logo([("tv", "X"), ("movie", "X")], "key") is None


def test_resolve_empty_attempts_is_none():
    assert icon_engine.resolve_tmdb_logo([], "key") is None


# ── planner spec hints ────────────────────────────────────────────────────────

def test_load_spec_hints(tmp_path):
    ps = tmp_path / "planner_state.json"
    ps.write_text('{"selected": {"a": {"kind": "genre", "name": "Horror", '
                  '"genre": "horror"}, "bad": {"kind": "x"}}}')
    hints = icon_engine.load_spec_hints(ps)
    assert hints == {"horror": {"kind": "genre", "name": "Horror", "genre": "horror"}}


def test_load_spec_hints_missing_file(tmp_path):
    assert icon_engine.load_spec_hints(tmp_path / "nope.json") == {}


def test_spec_genre_prefers_genre_then_genres():
    assert icon_engine.spec_genre({"genre": "horror"}) == "horror"
    assert icon_engine.spec_genre({"genres": ["western", "comedy"]}) == "western"
    assert icon_engine.spec_genre({}) is None

# ── Tunarr helpers ────────────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()
    def read(self):
        return self._payload
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def test_upload_image_multipart(monkeypatch):
    captured = {}
    def fake_urlopen(req, timeout=30):
        captured["req"] = req
        return _FakeResp({"name": "x.png",
                          "fileUrl": "http://t/images/uploads/x.png"})
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    url = icon_engine.upload_image_to_tunarr("http://t", b"\x89PNGfake", "x.png")

    assert url == "http://t/images/uploads/x.png"
    req = captured["req"]
    assert req.full_url == "http://t/api/upload/image"
    assert req.get_header("Content-type", "").startswith(
        "multipart/form-data; boundary=")
    assert b"\x89PNGfake" in req.data
    assert b'filename="x.png"' in req.data
    assert b'name="file"' in req.data


def test_set_tunarr_channel_icon(monkeypatch):
    sent = {}
    def fake_put(tunarr_url, path, body):
        sent["path"], sent["body"] = path, body
        return body
    monkeypatch.setattr(icon_engine, "_tunarr_put", fake_put)

    ch = {"id": "abc", "name": "X", "icon": {"path": "old"}}
    ok = icon_engine.set_tunarr_channel_icon("http://t", ch, "http://img/new.png")

    assert ok is True
    assert sent["path"] == "/api/channels/abc"
    assert sent["body"]["icon"]["path"] == "http://img/new.png"
    assert sent["body"]["icon"]["useDefaultIconFallback"] is False
    assert ch["icon"]["path"] == "old"  # input not mutated


def test_clear_tunarr_channel_icon(monkeypatch):
    sent = {}
    monkeypatch.setattr(icon_engine, "_tunarr_put",
                        lambda u, p, b: sent.update(body=b) or b)
    ok = icon_engine.clear_tunarr_channel_icon("http://t", {"id": "abc"})
    assert ok is True
    assert sent["body"]["icon"]["path"] == ""
    assert sent["body"]["icon"]["useDefaultIconFallback"] is True


def test_set_icon_reports_failure(monkeypatch):
    monkeypatch.setattr(icon_engine, "_tunarr_put", lambda u, p, b: None)
    assert icon_engine.set_tunarr_channel_icon("http://t", {"id": "x"}, "u") is False


def test_best_logo_prefers_raster_over_higher_voted_svg():
    # Plex guide icons must be raster; an SVG logo renders broken in the guide.
    images = {"logos": [
        {"file_path": "/logo.svg", "iso_639_1": "en", "vote_average": 9},
        {"file_path": "/logo.png", "iso_639_1": "en", "vote_average": 2},
    ]}
    assert icon_engine.best_logo_path(images) == "/logo.png"


def test_best_logo_none_when_only_svg():
    images = {"logos": [{"file_path": "/only.svg", "iso_639_1": "en", "vote_average": 9}]}
    assert icon_engine.best_logo_path(images) is None
