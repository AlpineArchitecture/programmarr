"""Update-notifier unit tests.

`is_newer` must do NUMERIC semver comparison (0.10.0 > 0.9.0, not lexical),
tolerate a leading 'v', and never raise on junk input — a broken check must
degrade to "no update", never crash the footer.
"""

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
for _p in (str(BACKEND), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from routers import status_router as sr


def test_is_newer_basic():
    assert sr.is_newer("0.6.0", "0.5.0") is True
    assert sr.is_newer("0.5.1", "0.5.0") is True
    assert sr.is_newer("1.0.0", "0.9.9") is True


def test_is_newer_equal_or_older():
    assert sr.is_newer("0.5.0", "0.5.0") is False
    assert sr.is_newer("0.5.0", "0.6.0") is False


def test_is_newer_numeric_not_lexical():
    # The classic bug: "0.10.0" < "0.9.0" lexically but is NEWER numerically.
    assert sr.is_newer("0.10.0", "0.9.0") is True


def test_is_newer_tolerates_v_prefix():
    assert sr.is_newer("v0.6.0", "0.5.0") is True


def test_is_newer_no_current_is_false():
    assert sr.is_newer("0.6.0", "") is False


def test_is_newer_junk_is_false():
    assert sr.is_newer("not-a-version", "0.5.0") is False
    assert sr.is_newer("", "0.5.0") is False


@pytest.fixture(autouse=True)
def _reset_update_cache():
    """Each test starts with an empty notifier cache."""
    sr._update_cache["at"] = 0.0
    sr._update_cache["data"] = None
    yield


def test_update_check_disabled_returns_enabled_false(monkeypatch):
    monkeypatch.setattr(sr, "load_config", lambda: {"update_check_enabled": False})
    # Even if a fetch would succeed, disabled short-circuits before any network call.
    monkeypatch.setattr(sr, "_fetch_latest_release", lambda: (_ for _ in ()).throw(AssertionError("must not fetch")))
    out = sr.update_check(current="0.5.0")
    assert out == {"enabled": False}


def test_update_check_reports_available(monkeypatch):
    monkeypatch.setattr(sr, "load_config", lambda: {})  # absent key => enabled by default
    monkeypatch.setattr(sr, "_fetch_latest_release", lambda: {
        "latest": "0.6.0", "name": "v0.6.0", "url": "https://example/releases/v0.6.0",
    })
    out = sr.update_check(current="0.5.0")
    assert out["enabled"] is True
    assert out["update_available"] is True
    assert out["latest"] == "0.6.0"
    assert out["url"] == "https://example/releases/v0.6.0"


def test_update_check_up_to_date(monkeypatch):
    monkeypatch.setattr(sr, "load_config", lambda: {})
    monkeypatch.setattr(sr, "_fetch_latest_release", lambda: {
        "latest": "0.5.0", "name": "v0.5.0", "url": "x",
    })
    out = sr.update_check(current="0.5.0")
    assert out["update_available"] is False


def test_update_check_caches_within_ttl(monkeypatch):
    monkeypatch.setattr(sr, "load_config", lambda: {})
    calls = {"n": 0}

    def fake_fetch():
        calls["n"] += 1
        return {"latest": "0.6.0", "name": "v0.6.0", "url": "x"}

    monkeypatch.setattr(sr, "_fetch_latest_release", fake_fetch)
    sr.update_check(current="0.5.0")
    sr.update_check(current="0.5.0")
    assert calls["n"] == 1, "second call within TTL must use the cache, not refetch"


def test_update_check_fetch_failure_is_safe(monkeypatch):
    monkeypatch.setattr(sr, "load_config", lambda: {})
    monkeypatch.setattr(sr, "_fetch_latest_release", lambda: None)  # network down
    out = sr.update_check(current="0.5.0")
    assert out["enabled"] is True
    assert out["update_available"] is False
    assert out["latest"] is None


def test_update_check_refetches_after_ttl(monkeypatch):
    monkeypatch.setattr(sr, "load_config", lambda: {})
    calls = {"n": 0}

    def fake_fetch():
        calls["n"] += 1
        return {"latest": "0.6.0", "name": "v0.6.0", "url": "x"}

    monkeypatch.setattr(sr, "_fetch_latest_release", fake_fetch)
    sr._update_cache["at"] = time.time() - sr._UPDATE_TTL - 1  # force-expire
    sr.update_check(current="0.5.0")   # first call re-stamps + fetches
    sr.update_check(current="0.5.0")   # second is within fresh TTL → cached
    assert calls["n"] == 1


import json as _json
import importlib


def test_update_check_enabled_persists_false(tmp_path, monkeypatch):
    """A False toggle must survive save_config's falsy-prune."""
    monkeypatch.setenv("PROGRAMMARR_DATA", str(tmp_path))
    from routers import config_router as cr
    importlib.reload(cr)  # re-bind DATA_DIR to the temp dir

    cr.save_config(cr.ConfigModel(update_check_enabled=False))
    saved = _json.loads((tmp_path / "config.json").read_text())
    assert saved["update_check_enabled"] is False

    cr.save_config(cr.ConfigModel(update_check_enabled=True))
    saved = _json.loads((tmp_path / "config.json").read_text())
    assert saved["update_check_enabled"] is True
