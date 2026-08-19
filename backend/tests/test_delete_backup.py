"""test_delete_backup.py — a destructive deploy must dump the lineup first.

Deleting Tunarr channels is irreversible and Programmarr's default deploy wipes
everything. A stranger pointing this at a Tunarr with a hand-built lineup would
lose it with no way back, so delete_channels writes a timestamped snapshot —
including each channel's raw programming payload, not just program ids — before
the first DELETE goes out. Probe runs must never write one.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import create


CHANNELS = [
    {"id": "a1", "number": 1, "name": "Sitcom Marathon"},
    {"id": "b2", "number": 2, "name": "80s Action"},
]


def fake_api(calls):
    """Stand in for channel_engine.api, recording every call."""
    def _api(url, method, path, body=None, timeout=60):
        calls.append((method, path))
        if method == "GET" and path == "/api/channels":
            return list(CHANNELS)
        if method == "GET" and path.endswith("/programming"):
            return {"lineup": [{"type": "content", "id": "p-" + path.split("/")[3]}],
                    "programs": {"p1": {"title": "Something"}}}
        if method == "DELETE":
            return {}
        return None
    return _api


def test_backup_written_before_delete(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(create, "api", fake_api(calls))

    create.delete_channels("http://tunarr", probe=False)

    backups = list(tmp_path.glob("tunarr_backup_*.json"))
    assert len(backups) == 1, "a destructive delete must leave exactly one snapshot"

    data = json.loads(backups[0].read_text(encoding="utf-8"))
    assert len(data["channels"]) == 2
    names = {c["channel"]["name"] for c in data["channels"]}
    assert names == {"Sitcom Marathon", "80s Action"}
    # The raw payload is what makes the file restorable.
    assert all("programming" in c for c in data["channels"])

    # Ordering is the whole point: every backup read precedes the first DELETE.
    first_delete = next(i for i, (m, _) in enumerate(calls) if m == "DELETE")
    prog_reads = [i for i, (m, p) in enumerate(calls) if m == "GET" and p.endswith("/programming")]
    assert prog_reads and max(prog_reads) < first_delete


def test_probe_writes_no_backup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(create, "api", fake_api(calls))

    create.delete_channels("http://tunarr", probe=True)

    assert not list(tmp_path.glob("tunarr_backup_*.json"))
    assert not [c for c in calls if c[0] == "DELETE"]


def test_backup_failure_does_not_block_delete(tmp_path, monkeypatch):
    """A broken backup must warn, not abort — losing the deploy to a disk error
    is its own failure mode."""
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(create, "api", fake_api(calls))
    monkeypatch.setattr(create, "open", None, raising=False)

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(create.json, "dump", boom)

    create.delete_channels("http://tunarr", probe=False)

    assert [c for c in calls if c[0] == "DELETE"], "delete must still proceed"


def test_rotation_keeps_last_n(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(create, "BACKUP_KEEP", 3)
    for i in range(5):
        (tmp_path / f"tunarr_backup_2020010{i}T000000Z.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(create, "api", fake_api([]))

    create.backup_channels("http://tunarr", CHANNELS)

    assert len(list(tmp_path.glob("tunarr_backup_*.json"))) == 3
