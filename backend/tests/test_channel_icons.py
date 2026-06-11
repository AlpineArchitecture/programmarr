"""POST /channels/{number}/icon — pin/override a channel's Tunarr icon.

Everything external is monkeypatched on the modules channels_router imports;
no Tunarr, no TMDB, no Pillow font rendering in the endpoint tests."""

import asyncio
import json

import pytest
from fastapi import HTTPException

import badge_renderer
import channel_engine
import icon_engine
from routers import channels_router


@pytest.fixture
def chdir_data(tmp_path, monkeypatch):
    """Point channels_router at a temp DATA_DIR seeded with one channel."""
    monkeypatch.setattr(channels_router, "DATA_DIR", tmp_path)
    (tmp_path / "channels.json").write_text(json.dumps({
        "channels": [{"number": 5, "name": "Horror", "shuffle": "shuffle",
                      "content": ["It", "Scream"]}],
        "orphaned": [], "suggested_channels": [],
    }))
    (tmp_path / "config.json").write_text(json.dumps({
        "tunarr_url": "http://tunarr:8000", "tmdb_api_key": "k",
    }))
    return tmp_path


@pytest.fixture
def tunarr_ok(monkeypatch):
    """A deployed Tunarr channel #5 plus capture of icon writes."""
    calls = {}
    monkeypatch.setattr(channel_engine, "find_channel_by_number",
                        lambda url, n: {"id": "tid-5", "number": n, "name": "Horror"})
    monkeypatch.setattr(icon_engine, "get_full_channel",
                        lambda url, cid: {"id": cid, "name": "Horror", "icon": {}})
    monkeypatch.setattr(icon_engine, "set_tunarr_channel_icon",
                        lambda url, ch, icon_url: calls.update(set=icon_url) or True)
    monkeypatch.setattr(icon_engine, "clear_tunarr_channel_icon",
                        lambda url, ch: calls.update(cleared=True) or True)
    monkeypatch.setattr(icon_engine, "upload_image_to_tunarr",
                        lambda url, png, fn: "http://tunarr:8000/images/uploads/b.png")
    monkeypatch.setattr(badge_renderer, "render_badge",
                        lambda name, kind=None, genre=None: b"\x89PNGfake")
    return calls


def _call(number, body):
    return asyncio.run(channels_router.channel_icon(number, body))


def _saved_channel(tmp_path):
    data = json.loads((tmp_path / "channels.json").read_text())
    return data["channels"][0]


def test_badge_mode_uploads_sets_and_pins(chdir_data, tunarr_ok):
    res = _call(5, {"mode": "badge"})
    assert res["ok"] is True
    assert tunarr_ok["set"] == "http://tunarr:8000/images/uploads/b.png"
    pin = _saved_channel(chdir_data)["icon"]
    assert pin == {"mode": "badge",
                   "url": "http://tunarr:8000/images/uploads/b.png",
                   "pinned": True}


def test_custom_mode_sets_given_url(chdir_data, tunarr_ok):
    res = _call(5, {"mode": "custom", "url": "http://x/i.png"})
    assert res["url"] == "http://x/i.png"
    assert tunarr_ok["set"] == "http://x/i.png"
    assert _saved_channel(chdir_data)["icon"]["mode"] == "custom"


def test_custom_mode_requires_url(chdir_data, tunarr_ok):
    with pytest.raises(HTTPException) as e:
        _call(5, {"mode": "custom"})
    assert e.value.status_code == 409


def test_clear_mode_unpins(chdir_data, tunarr_ok):
    _call(5, {"mode": "badge"})
    res = _call(5, {"mode": "clear"})
    assert res["ok"] is True
    assert tunarr_ok["cleared"] is True
    assert "icon" not in _saved_channel(chdir_data)


def test_tmdb_mode_409_when_no_verified_logo(chdir_data, tunarr_ok, monkeypatch):
    monkeypatch.setattr(icon_engine, "resolve_tmdb_logo", lambda a, k: None)
    with pytest.raises(HTTPException) as e:
        _call(5, {"mode": "tmdb"})
    assert e.value.status_code == 409


def test_tmdb_mode_sets_verified_logo(chdir_data, tunarr_ok, monkeypatch):
    monkeypatch.setattr(icon_engine, "resolve_tmdb_logo",
                        lambda a, k: "http://img/logo.png")
    res = _call(5, {"mode": "tmdb"})
    assert res["url"] == "http://img/logo.png"
    assert _saved_channel(chdir_data)["icon"]["mode"] == "tmdb"


def test_unknown_channel_404(chdir_data, tunarr_ok):
    with pytest.raises(HTTPException) as e:
        _call(99, {"mode": "badge"})
    assert e.value.status_code == 404


def test_undeployed_channel_409(chdir_data, tunarr_ok, monkeypatch):
    monkeypatch.setattr(channel_engine, "find_channel_by_number", lambda u, n: None)
    with pytest.raises(HTTPException) as e:
        _call(5, {"mode": "badge"})
    assert e.value.status_code == 409


def test_bad_mode_422(chdir_data, tunarr_ok):
    with pytest.raises(HTTPException) as e:
        _call(5, {"mode": "sparkly"})
    assert e.value.status_code == 422
