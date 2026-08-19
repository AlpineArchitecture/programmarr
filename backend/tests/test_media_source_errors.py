"""test_media_source_errors.py — an unsupported Tunarr setup must say what's wrong.

Programmarr is Plex-only. A Jellyfin/Emby-backed Tunarr used to fail with
"No Plex source found in Tunarr", which reads as a broken Plex connection and
sends the user debugging Plex instead of learning they're unsupported. Each
distinct cause now gets a distinct message.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import channel_engine


def stub_sources(monkeypatch, value):
    def _api(url, method, path, body=None, timeout=60):
        if path == "/api/media-sources":
            return value
        return None
    monkeypatch.setattr(channel_engine, "api", _api)


def test_jellyfin_source_names_what_was_found(monkeypatch):
    stub_sources(monkeypatch, [{"type": "jellyfin", "name": "Jellyfin"}])
    with pytest.raises(channel_engine.ChannelEngineError) as e:
        channel_engine.build_library_index("http://tunarr")
    msg = str(e.value)
    assert "jellyfin" in msg
    assert "Plex-backed" in msg


def test_unreachable_tunarr_blames_tunarr_not_plex(monkeypatch):
    stub_sources(monkeypatch, None)          # api() returns None on any failure
    with pytest.raises(channel_engine.ChannelEngineError) as e:
        channel_engine.build_library_index("http://tunarr")
    msg = str(e.value)
    assert "tunarr_url" in msg
    assert "no media sources configured" not in msg.lower()


def test_empty_source_list_tells_user_to_add_one(monkeypatch):
    stub_sources(monkeypatch, [])
    with pytest.raises(channel_engine.ChannelEngineError) as e:
        channel_engine.build_library_index("http://tunarr")
    assert "no media sources configured" in str(e.value).lower()


def test_transcode_config_picks_first_and_reports_ambiguity(monkeypatch, capsys):
    def _api(url, method, path, body=None, timeout=60):
        if path == "/api/transcode_configs":
            return [{"id": "x1", "name": "Default"}, {"id": "x2", "name": "4K HW"}]
        return None
    monkeypatch.setattr(channel_engine, "api", _api)

    assert channel_engine.get_transcode_config("http://tunarr") == "x1"
    out = capsys.readouterr().out
    assert "Default" in out and "2 transcode configs" in out


def test_transcode_config_silent_when_unambiguous(monkeypatch, capsys):
    def _api(url, method, path, body=None, timeout=60):
        if path == "/api/transcode_configs":
            return [{"id": "only", "name": "Default"}]
        return None
    monkeypatch.setattr(channel_engine, "api", _api)

    assert channel_engine.get_transcode_config("http://tunarr") == "only"
    assert "transcode configs" not in capsys.readouterr().out


# ── P0-3: a failed library fetch must not masquerade as an empty library ───────

def _sources_with_libs(libs):
    return [{"type": "plex", "name": "Plex", "libraries": libs}]


MOVIE_LIB = {"id": "m1", "name": "Movies", "mediaType": "movie", "enabled": True}
MOVIE_LIB2 = {"id": "m2", "name": "Cartoons", "mediaType": "movie", "enabled": True}


def test_all_libraries_failing_raises_instead_of_empty_index(monkeypatch):
    """The old code reported 'Indexed 0 movies' and deployed empty channels."""
    def _api(url, method, path, body=None, timeout=60):
        if path == "/api/media-sources":
            return _sources_with_libs([MOVIE_LIB])
        return None                      # every library fetch fails
    monkeypatch.setattr(channel_engine, "api", _api)

    with pytest.raises(channel_engine.ChannelEngineError) as e:
        channel_engine.build_library_index("http://tunarr")
    assert "Movies" in str(e.value)
    assert "empty index" in str(e.value)


def test_partial_failure_warns_but_continues(monkeypatch, capsys):
    """One dead library shouldn't block a deploy — but must not pass silently."""
    def _api(url, method, path, body=None, timeout=60):
        if path == "/api/media-sources":
            return _sources_with_libs([MOVIE_LIB, MOVIE_LIB2])
        if path.endswith("/m1/programs"):
            return [{"program": {"title": "Heat"}}]
        return None                      # m2 fails
    monkeypatch.setattr(channel_engine, "api", _api)

    movie_map, _ = channel_engine.build_library_index("http://tunarr")
    assert "heat" in movie_map

    out = capsys.readouterr().out
    assert "WARNING" in out and "Cartoons" in out


def test_genuinely_empty_library_is_not_an_error(monkeypatch):
    """An empty library is a real, valid state — only failures raise."""
    def _api(url, method, path, body=None, timeout=60):
        if path == "/api/media-sources":
            return _sources_with_libs([MOVIE_LIB])
        return []
    monkeypatch.setattr(channel_engine, "api", _api)

    movie_map, show_map = channel_engine.build_library_index("http://tunarr")
    assert movie_map == {} and show_map == {}


# ── P0-2: capability detection instead of a guessed version gate ──────────────

def test_missing_endpoint_blames_an_old_tunarr(monkeypatch):
    """A 404 on /api/media-sources is directly observable; a version number is a
    guess. Report the endpoint, not a threshold."""
    def _api(url, method, path, body=None, timeout=60):
        if path == "/api/version":
            return {"tunarr": "0.9.2"}
        return None
    monkeypatch.setattr(channel_engine, "api", _api)
    monkeypatch.setattr(channel_engine, "_endpoint_status", lambda u, p, timeout=10: 404)

    with pytest.raises(channel_engine.ChannelEngineError) as e:
        channel_engine.build_library_index("http://tunarr")
    msg = str(e.value)
    assert "/api/media-sources" in msg
    assert "update Tunarr" in msg
    assert "0.9.2" in msg, "the reported version belongs in the message"


def test_unreachable_is_not_reported_as_too_old(monkeypatch):
    """A dead host returns no status at all — that's a connection problem, and
    telling the user to upgrade Tunarr would send them the wrong way."""
    monkeypatch.setattr(channel_engine, "api", lambda *a, **k: None)
    monkeypatch.setattr(channel_engine, "_endpoint_status", lambda u, p, timeout=10: None)

    with pytest.raises(channel_engine.ChannelEngineError) as e:
        channel_engine.build_library_index("http://tunarr")
    msg = str(e.value)
    assert "tunarr_url" in msg
    assert "too old" not in msg


def test_version_is_optional(monkeypatch):
    """Tunarr may not answer /api/version; that must not break the error path."""
    monkeypatch.setattr(channel_engine, "api", lambda *a, **k: None)
    monkeypatch.setattr(channel_engine, "_endpoint_status", lambda u, p, timeout=10: 404)

    with pytest.raises(channel_engine.ChannelEngineError) as e:
        channel_engine.build_library_index("http://tunarr")
    assert "version None" not in str(e.value)


def test_get_tunarr_version_reads_the_tunarr_field(monkeypatch):
    monkeypatch.setattr(channel_engine, "api",
                        lambda u, m, p, **k: {"tunarr": "1.3.5", "ffmpeg": "7.0", "nodejs": "22"})
    assert channel_engine.get_tunarr_version("http://tunarr") == "1.3.5"


def test_get_tunarr_version_tolerates_junk(monkeypatch):
    monkeypatch.setattr(channel_engine, "api", lambda u, m, p, **k: "not-a-dict")
    assert channel_engine.get_tunarr_version("http://tunarr") is None


# ── 401 from Tunarr: say which of the two auth problems it is ─────────────────

def test_401_with_no_credentials_says_to_set_them(monkeypatch):
    monkeypatch.setattr(channel_engine, "api", lambda *a, **k: None)
    monkeypatch.setattr(channel_engine, "_endpoint_status", lambda u, p, timeout=10: 401)
    channel_engine.set_tunarr_auth()

    with pytest.raises(channel_engine.ChannelEngineError) as e:
        channel_engine.build_library_index("http://tunarr")
    msg = str(e.value)
    assert "requires a username and password" in msg
    assert "none are configured" in msg


def test_401_with_credentials_says_they_are_wrong(monkeypatch):
    """Different advice: they HAVE credentials, so the fix is to correct them."""
    monkeypatch.setattr(channel_engine, "api", lambda *a, **k: None)
    monkeypatch.setattr(channel_engine, "_endpoint_status", lambda u, p, timeout=10: 401)
    channel_engine.set_tunarr_auth("admin", "wrong")
    try:
        with pytest.raises(channel_engine.ChannelEngineError) as e:
            channel_engine.build_library_index("http://tunarr")
        assert "rejected the username and password" in str(e.value)
    finally:
        channel_engine.set_tunarr_auth()


def test_403_is_treated_the_same_as_401(monkeypatch):
    monkeypatch.setattr(channel_engine, "api", lambda *a, **k: None)
    monkeypatch.setattr(channel_engine, "_endpoint_status", lambda u, p, timeout=10: 403)
    channel_engine.set_tunarr_auth()

    with pytest.raises(channel_engine.ChannelEngineError) as e:
        channel_engine.build_library_index("http://tunarr")
    assert "403" in str(e.value)
