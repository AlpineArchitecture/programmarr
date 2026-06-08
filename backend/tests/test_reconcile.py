"""_reconcile_channels_json — wipe and keep-mode, staging-file cleanup."""

import json


def _write(pr, filename: str, channels: list[dict], extras: dict = {}):
    data = {"channels": channels, "orphaned": [], "suggested_channels": [], **extras}
    (pr._test_data_dir / filename).write_text(json.dumps(data), encoding="utf-8")


def _read(pr, filename: str) -> dict:
    return json.loads((pr._test_data_dir / filename).read_text(encoding="utf-8"))


def test_wipe_mode_channels_json_equals_deployed(pr):
    """Wipe (no protected): channels.json becomes exactly the deployed set."""
    _write(pr, "deploy_temp.json", [
        {"number": 30, "name": "Action", "shuffle": "shuffle", "content": ["A"]},
        {"number": 31, "name": "Comedy", "shuffle": "shuffle", "content": ["B"]},
    ])
    # Seed an old channels.json (should be fully replaced in wipe mode)
    _write(pr, "channels.json", [{"number": 10, "name": "Old", "content": []}])
    # Also seed a draft that should be deleted
    _write(pr, "channels.draft.json", [{"number": 99, "name": "Draft", "content": []}])

    pr._reconcile_channels_json([])

    result = _read(pr, "channels.json")
    nums = [c["number"] for c in result["channels"]]
    assert nums == [30, 31]
    assert not (pr._test_data_dir / "deploy_temp.json").exists()
    assert not (pr._test_data_dir / "channels.draft.json").exists()


def test_keep_mode_merges_protected_and_deployed(pr):
    """Keep mode: channels.json = protected existing entries + deployed channels."""
    _write(pr, "channels.json", [
        {"number": 10, "name": "Kept Marathon", "shuffle": "ordered", "content": ["X"]},
        {"number": 20, "name": "Non-protected", "shuffle": "shuffle", "content": ["Y"]},
    ])
    _write(pr, "deploy_temp.json", [
        {"number": 30, "name": "New Action", "shuffle": "shuffle", "content": ["A"]},
    ])

    pr._reconcile_channels_json([10])  # only channel 10 is protected

    result = _read(pr, "channels.json")
    by_num = {c["number"]: c for c in result["channels"]}

    assert 10 in by_num, "protected entry must survive"
    assert by_num[10]["name"] == "Kept Marathon"
    assert 30 in by_num, "deployed entry must be present"
    assert 20 not in by_num, "non-protected old entry must be gone"


def test_keep_mode_deployed_wins_on_collision(pr):
    """If protected and deployed share a number, deployed wins."""
    _write(pr, "channels.json", [
        {"number": 10, "name": "Old Name", "content": []},
    ])
    _write(pr, "deploy_temp.json", [
        {"number": 10, "name": "New Name", "content": ["A"]},
    ])

    pr._reconcile_channels_json([10])

    result = _read(pr, "channels.json")
    assert result["channels"][0]["name"] == "New Name"


def test_keep_mode_missing_channels_json_is_ok(pr):
    """Keep mode with no existing channels.json doesn't crash."""
    _write(pr, "deploy_temp.json", [
        {"number": 30, "name": "Action", "content": []},
    ])

    pr._reconcile_channels_json([10])  # protected #10 doesn't exist — just skip it

    result = _read(pr, "channels.json")
    assert [c["number"] for c in result["channels"]] == [30]


def test_staging_files_deleted_after_reconcile(pr):
    """Both deploy_temp.json and channels.draft.json are cleaned up."""
    _write(pr, "deploy_temp.json", [{"number": 10, "name": "X", "content": []}])
    _write(pr, "channels.draft.json", [{"number": 99, "name": "Draft", "content": []}])

    pr._reconcile_channels_json([])

    assert not (pr._test_data_dir / "deploy_temp.json").exists()
    assert not (pr._test_data_dir / "channels.draft.json").exists()
