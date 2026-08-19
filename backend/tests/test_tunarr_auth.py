"""test_tunarr_auth.py — Tunarr's optional basic auth must reach every Tunarr call.

Tunarr gained optional HTTP basic auth on its API (tunarr #1865). Programmarr sent
no credentials at all, so a locked-down Tunarr failed everywhere. Auth is module
state on channel_engine rather than a parameter on ~20 functions, which makes
"did every caller get it?" the thing worth testing — a half-wired auth layer fails
in whichever corner was missed.
"""

import base64
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import channel_engine


@pytest.fixture(autouse=True)
def reset_auth():
    channel_engine.set_tunarr_auth()
    yield
    channel_engine.set_tunarr_auth()


def test_no_auth_by_default():
    assert "Authorization" not in channel_engine.tunarr_headers()


def test_auth_header_is_valid_basic():
    channel_engine.set_tunarr_auth("admin", "s3cret")
    hdr = channel_engine.tunarr_headers()["Authorization"]
    assert hdr.startswith("Basic ")
    assert base64.b64decode(hdr.split(" ", 1)[1]).decode() == "admin:s3cret"


def test_blank_config_clears_auth():
    channel_engine.set_tunarr_auth("admin", "s3cret")
    channel_engine.set_tunarr_auth_from_config({})
    assert "Authorization" not in channel_engine.tunarr_headers()


def test_config_dict_wires_through():
    channel_engine.set_tunarr_auth_from_config(
        {"tunarr_username": "u", "tunarr_password": "p"})
    hdr = channel_engine.tunarr_headers()["Authorization"]
    assert base64.b64decode(hdr.split(" ", 1)[1]).decode() == "u:p"


def test_password_only_still_authenticates():
    """Tunarr allows a blank username; don't silently drop the credential."""
    channel_engine.set_tunarr_auth("", "p")
    assert "Authorization" in channel_engine.tunarr_headers()


def test_extra_headers_merge_without_losing_auth():
    channel_engine.set_tunarr_auth("u", "p")
    h = channel_engine.tunarr_headers({"Content-Type": "application/json"})
    assert h["Content-Type"] == "application/json"
    assert "Authorization" in h


def test_api_sends_the_auth_header(monkeypatch):
    """The engine's own api() is the highest-traffic caller — verify end to end."""
    seen = {}

    class FakeResp:
        status = 200
        def read(self):
            return b"{}"
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen["headers"] = dict(req.header_items())
        return FakeResp()

    monkeypatch.setattr(channel_engine.urllib.request, "urlopen", fake_urlopen)
    channel_engine.set_tunarr_auth("u", "p")
    channel_engine.api("http://tunarr", "GET", "/api/channels")

    # urllib title-cases header names.
    assert any(k.lower() == "authorization" for k in seen["headers"])


def test_every_tunarr_module_uses_the_shared_headers():
    """Guard against a new bare-headers Tunarr call sneaking back in.

    Each of these modules talks to Tunarr; none may hand-roll its headers, or
    enabling auth works in some places and not others.
    """
    import icon_engine, sync_plex, export  # noqa: E401

    for mod in (icon_engine, sync_plex, export):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "channel_engine.tunarr_headers" in src, (
            f"{Path(mod.__file__).name} talks to Tunarr but does not use "
            "channel_engine.tunarr_headers()")
