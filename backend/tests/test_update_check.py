"""Update-notifier unit tests.

`is_newer` must do NUMERIC semver comparison (0.10.0 > 0.9.0, not lexical),
tolerate a leading 'v', and never raise on junk input — a broken check must
degrade to "no update", never crash the footer.
"""

import sys
from pathlib import Path

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
