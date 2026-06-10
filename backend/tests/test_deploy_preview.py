"""test_deploy_preview.py — unit tests for POST /pipeline/deploy-preview.

Covers:
  - edit mode: correct bucket classification (create / update / delete / unchanged / foreign)
    with update entries carrying the DEPLOYED number, not the draft number
  - nuke mode: all draft channels in "create", all managed-deployed in "delete",
    foreign channels (not in prior_managed) in "foreign", no "update" or "unchanged"
  - 404 when channels.draft.json is missing
"""

import json


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _channels_file(channels):
    return {"channels": channels, "orphaned": [], "suggested_channels": []}


def _ch(name, number, content=None, shuffle="shuffle"):
    return {"number": number, "name": name, "shuffle": shuffle,
            "content": content or [f"{name} title"]}


# ── Edit mode ─────────────────────────────────────────────────────────────────

def test_edit_preview_all_buckets(pr):
    """Edit mode: a mixed draft+deployed state classifies into all five buckets correctly.

    Setup:
      deployed (channels.json):
        #1  Unchanged Channel  (same in draft)
        #2  Updated Channel    (different content in draft — draft renumbers to #50)
        #3  Deleted Channel    (absent from draft, in prior_managed)
        #4  Foreign Channel    (absent from draft, NOT in prior_managed)

      desired (channels.draft.json):
        #1  Unchanged Channel  (same content — unchanged)
        #50 Updated Channel    (content differs — update-in-place at DEPLOYED #2)
        #60 New Channel        (absent from deployed — create)

    Expected:
      create:    [New Channel at #60]
      update:    [Updated Channel at deployed #2  ← not draft #50]
      delete:    [Deleted Channel at #3]
      unchanged: [Unchanged Channel at #1]
      foreign:   [Foreign Channel at #4]
    """
    deployed = [
        _ch("Unchanged Channel", 1),
        _ch("Updated Channel", 2, content=["Old Film"]),
        _ch("Deleted Channel", 3),
        _ch("Foreign Channel", 4),
    ]
    desired = [
        _ch("Unchanged Channel", 1),
        _ch("Updated Channel", 50, content=["New Film"]),  # renumbered in Add/Edit draft
        _ch("New Channel", 60),
    ]
    prior_managed = ["Unchanged Channel", "Updated Channel", "Deleted Channel"]

    data_dir = pr._test_data_dir
    _write_json(data_dir / "channels.draft.json", _channels_file(desired))
    _write_json(data_dir / "channels.json", _channels_file(deployed))
    _write_json(data_dir / "planner_state.json", {"managed_names": prior_managed})

    from routers.pipeline_router import DeployPreviewRequest
    result = pr.deploy_preview(DeployPreviewRequest(mode="edit"))

    assert len(result["create"]) == 1
    assert result["create"][0]["name"] == "New Channel"
    assert result["create"][0]["number"] == 60

    assert len(result["update"]) == 1
    assert result["update"][0]["name"] == "Updated Channel"
    # Must be the DEPLOYED number (#2), not the draft number (#50).
    assert result["update"][0]["number"] == 2, (
        "update entry must carry the deployed number so surgical-deploy targets the right channel"
    )

    assert len(result["delete"]) == 1
    assert result["delete"][0]["name"] == "Deleted Channel"
    assert result["delete"][0]["number"] == 3

    assert len(result["unchanged"]) == 1
    assert result["unchanged"][0]["name"] == "Unchanged Channel"
    assert result["unchanged"][0]["number"] == 1

    assert len(result["foreign"]) == 1
    assert result["foreign"][0]["name"] == "Foreign Channel"
    assert result["foreign"][0]["number"] == 4


def test_edit_preview_all_new(pr):
    """Edit mode with nothing deployed yet — everything goes to create."""
    desired = [_ch("Comedy", 1), _ch("Action", 2)]
    data_dir = pr._test_data_dir
    _write_json(data_dir / "channels.draft.json", _channels_file(desired))
    # No channels.json — first deploy.

    from routers.pipeline_router import DeployPreviewRequest
    result = pr.deploy_preview(DeployPreviewRequest(mode="edit"))

    assert len(result["create"]) == 2
    assert result["update"] == []
    assert result["delete"] == []
    assert result["unchanged"] == []
    assert result["foreign"] == []


def test_edit_preview_unchanged_only(pr):
    """Edit mode when draft exactly matches deployed — nothing to do."""
    ch = _ch("Sci-Fi", 5)
    data_dir = pr._test_data_dir
    _write_json(data_dir / "channels.draft.json", _channels_file([ch]))
    _write_json(data_dir / "channels.json", _channels_file([ch]))
    _write_json(data_dir / "planner_state.json", {"managed_names": ["Sci-Fi"]})

    from routers.pipeline_router import DeployPreviewRequest
    result = pr.deploy_preview(DeployPreviewRequest(mode="edit"))

    assert result["create"] == []
    assert result["update"] == []
    assert result["delete"] == []
    assert len(result["unchanged"]) == 1
    assert result["foreign"] == []


# ── Nuke mode ─────────────────────────────────────────────────────────────────

def test_nuke_preview_all_create_and_managed_delete(pr):
    """Nuke mode: all draft channels are "create"; all managed-deployed are "delete";
    foreign channels (not in prior_managed) go to "foreign"; no update or unchanged.
    """
    deployed = [
        _ch("Old Channel A", 1),   # managed (prior_managed)
        _ch("Old Channel B", 2),   # managed (prior_managed)
        _ch("Hand Authored", 99),  # NOT in prior_managed → foreign
    ]
    desired = [
        _ch("New Channel X", 10),
        _ch("New Channel Y", 11),
    ]
    prior_managed = ["Old Channel A", "Old Channel B"]

    data_dir = pr._test_data_dir
    _write_json(data_dir / "channels.draft.json", _channels_file(desired))
    _write_json(data_dir / "channels.json", _channels_file(deployed))
    _write_json(data_dir / "planner_state.json", {"managed_names": prior_managed})

    from routers.pipeline_router import DeployPreviewRequest
    result = pr.deploy_preview(DeployPreviewRequest(mode="nuke"))

    # All draft channels are "create" in nuke mode.
    assert len(result["create"]) == 2
    create_names = {c["name"] for c in result["create"]}
    assert create_names == {"New Channel X", "New Channel Y"}

    # Nuke never produces "update" or "unchanged".
    assert result["update"] == []
    assert result["unchanged"] == []

    # All managed-deployed channels will be deleted.
    assert len(result["delete"]) == 2
    delete_names = {c["name"] for c in result["delete"]}
    assert delete_names == {"Old Channel A", "Old Channel B"}

    # Foreign channel (not managed) is untouched.
    assert len(result["foreign"]) == 1
    assert result["foreign"][0]["name"] == "Hand Authored"


def test_nuke_preview_no_deployed(pr):
    """Nuke mode with nothing deployed — all draft channels create, no deletes."""
    desired = [_ch("Horror", 30), _ch("Action", 31)]
    data_dir = pr._test_data_dir
    _write_json(data_dir / "channels.draft.json", _channels_file(desired))
    # No channels.json.

    from routers.pipeline_router import DeployPreviewRequest
    result = pr.deploy_preview(DeployPreviewRequest(mode="nuke"))

    assert len(result["create"]) == 2
    assert result["delete"] == []
    assert result["update"] == []
    assert result["unchanged"] == []
    assert result["foreign"] == []


def test_nuke_preview_existing_channel_also_in_draft_is_create(pr):
    """Nuke mode: even a channel that exists in both draft and deployed goes to
    "create" — nuke wipes everything and rebuilds from scratch.  The deployed
    channel goes to "delete" (if managed).
    """
    ch_deployed = _ch("Comedy", 1, content=["Film A"])
    ch_desired = _ch("Comedy", 1, content=["Film A"])  # identical content
    prior_managed = ["Comedy"]

    data_dir = pr._test_data_dir
    _write_json(data_dir / "channels.draft.json", _channels_file([ch_desired]))
    _write_json(data_dir / "channels.json", _channels_file([ch_deployed]))
    _write_json(data_dir / "planner_state.json", {"managed_names": prior_managed})

    from routers.pipeline_router import DeployPreviewRequest
    result = pr.deploy_preview(DeployPreviewRequest(mode="nuke"))

    # In nuke mode, the channel is recreated — it appears in both create AND delete.
    assert len(result["create"]) == 1
    assert result["create"][0]["name"] == "Comedy"
    assert len(result["delete"]) == 1
    assert result["delete"][0]["name"] == "Comedy"
    assert result["update"] == []
    assert result["unchanged"] == []


# ── Error cases ────────────────────────────────────────────────────────────────

def test_preview_404_when_no_draft(pr):
    """POST /pipeline/deploy-preview must 404 when channels.draft.json is absent."""
    from fastapi import HTTPException
    import pytest

    from routers.pipeline_router import DeployPreviewRequest
    with pytest.raises(HTTPException) as exc_info:
        pr.deploy_preview(DeployPreviewRequest(mode="edit"))

    assert exc_info.value.status_code == 404
