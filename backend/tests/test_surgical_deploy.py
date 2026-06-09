"""test_surgical_deploy.py — unit tests for channel_engine.classify_channels.

Covers:
  - create / delete / update / unchanged / foreign classification
  - provenance: only planner-managed (prior_managed) channels are deleted
  - live-channel safety (INVARIANT 2):
      - a live channel in ``update`` is always patched in-place (never deleted)
      - a planner-managed live channel REMOVED from desired IS deleted (intent wins)
      - a foreign live channel absent from desired is in ``foreign``, never ``delete``
  - orphan safety (Tunarr channels absent from channels.json are outside both
    input sets and never appear in any output bucket)
  - edge cases: empty inputs, case-insensitive name matching, bootstrapping
    (no prior_managed → nothing deleted)
"""

import sys
from pathlib import Path

# Ensure the repo root (where channel_engine.py lives) is on sys.path.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import channel_engine


def _ch(name, number=1, shuffle="shuffle", content=None, live=False, **extra):
    """Helper to build a minimal channel dict."""
    ch = {
        "number": number,
        "name": name,
        "shuffle": shuffle,
        "content": content if content is not None else [f"{name} title"],
    }
    if live:
        ch["live"] = True
    ch.update(extra)
    return ch


def _pm(*names):
    """Build a prior_managed set from channel names."""
    return {n.strip().lower() for n in names}


# ── Basic create / delete / update / unchanged ─────────────────────────────────

def test_all_new_channels_are_created():
    desired = [_ch("Comedy", 1), _ch("Action", 2)]
    deployed = []
    diff = channel_engine.classify_channels(desired, deployed, set())
    assert len(diff["create"]) == 2
    assert diff["delete"] == []
    assert diff["update"] == []
    assert diff["unchanged"] == []
    assert diff["foreign"] == []


def test_all_deployed_managed_removed_are_deleted():
    desired = []
    deployed = [_ch("Comedy", 1), _ch("Action", 2)]
    prior = _pm("Comedy", "Action")
    diff = channel_engine.classify_channels(desired, deployed, prior)
    assert diff["create"] == []
    assert len(diff["delete"]) == 2
    assert diff["update"] == []
    assert diff["unchanged"] == []
    assert diff["foreign"] == []


def test_unchanged_channel_is_not_touched():
    ch = _ch("Comedy", 1, content=["Funny Film"])
    diff = channel_engine.classify_channels([ch], [ch], _pm("comedy"))
    assert diff["create"] == []
    assert diff["delete"] == []
    assert diff["update"] == []
    assert len(diff["unchanged"]) == 1
    assert diff["foreign"] == []


def test_changed_content_classified_as_update():
    deployed_ch = _ch("Comedy", 1, content=["Old Film"])
    desired_ch = _ch("Comedy", 1, content=["New Film"])
    diff = channel_engine.classify_channels([desired_ch], [deployed_ch], _pm("comedy"))
    assert diff["create"] == []
    assert diff["delete"] == []
    assert len(diff["update"]) == 1
    assert diff["update"][0]["desired"]["content"] == ["New Film"]
    assert diff["update"][0]["deployed"]["content"] == ["Old Film"]
    assert diff["unchanged"] == []


def test_changed_shuffle_classified_as_update():
    deployed_ch = _ch("Comedy", 1, shuffle="shuffle")
    desired_ch = _ch("Comedy", 1, shuffle="ordered")
    diff = channel_engine.classify_channels([desired_ch], [deployed_ch], _pm("comedy"))
    assert len(diff["update"]) == 1


def test_mixed_create_update_unchanged_delete():
    desired = [
        _ch("New Channel", 10),               # create
        _ch("Updated Channel", 2, content=["Film B"]),  # update
        _ch("Unchanged Channel", 3),           # unchanged
    ]
    deployed = [
        _ch("Updated Channel", 2, content=["Film A"]),  # will be update
        _ch("Unchanged Channel", 3),           # unchanged
        _ch("Gone Channel", 4),                # planner-managed → delete
    ]
    prior = _pm("Updated Channel", "Unchanged Channel", "Gone Channel")
    diff = channel_engine.classify_channels(desired, deployed, prior)
    assert len(diff["create"]) == 1
    assert diff["create"][0]["name"] == "New Channel"
    assert len(diff["delete"]) == 1
    assert diff["delete"][0]["name"] == "Gone Channel"
    assert len(diff["update"]) == 1
    assert diff["update"][0]["desired"]["name"] == "Updated Channel"
    assert len(diff["unchanged"]) == 1
    assert diff["unchanged"][0]["name"] == "Unchanged Channel"
    assert diff["foreign"] == []


# ── Provenance: foreign / hand-authored channels ──────────────────────────────

def test_foreign_channel_absent_from_desired_goes_to_foreign_not_delete():
    """A channel NOT in prior_managed (hand-authored outside the planner) must
    never be deleted — it lands in the 'foreign' bucket."""
    deployed = [_ch("Hand Authored", 99)]
    desired = []
    prior = set()  # empty — no planner history
    diff = channel_engine.classify_channels(desired, deployed, prior)
    assert diff["delete"] == [], "hand-authored channel must NEVER be in delete bucket"
    assert any(c["name"] == "Hand Authored" for c in diff["foreign"])
    assert diff["create"] == []
    assert diff["update"] == []


def test_foreign_channel_with_prior_managed_others_still_goes_to_foreign():
    """Even when other channels are planner-managed, a channel whose name is not
    in prior_managed is foreign — it is never auto-deleted."""
    deployed = [_ch("Planner Chan", 1), _ch("Hand Authored", 99)]
    desired = []
    prior = _pm("Planner Chan")  # only Planner Chan is managed
    diff = channel_engine.classify_channels(desired, deployed, prior)
    assert len(diff["delete"]) == 1
    assert diff["delete"][0]["name"] == "Planner Chan"
    assert len(diff["foreign"]) == 1
    assert diff["foreign"][0]["name"] == "Hand Authored"


def test_foreign_live_channel_absent_from_desired_goes_to_foreign():
    """A foreign (hand-authored) live channel absent from desired must land in
    'foreign', not 'delete' or 'unchanged'."""
    deployed = [_ch("Live Foreign", 88, live=True)]
    desired = []
    prior = set()  # not planner-managed
    diff = channel_engine.classify_channels(desired, deployed, prior)
    assert diff["delete"] == []
    assert diff["update"] == []
    assert diff["unchanged"] == []
    assert any(c["name"] == "Live Foreign" for c in diff["foreign"])


# ── Live-channel safety (INVARIANT 2) ─────────────────────────────────────────

def test_planner_managed_live_channel_removed_from_desired_goes_to_delete():
    """A live channel that IS in prior_managed but absent from desired was
    intentionally removed by the user — it MUST land in 'delete'.

    Invariant 2 (never delete-RECREATE a live channel) is about the UPDATE path
    (changed live channels go to update-in-place, never delete+create).  A plain
    removal is allowed when the planner previously owned the channel.
    """
    deployed = [_ch("Live Show", 5, live=True)]
    desired = []  # Live Show was removed from the Planner
    prior = _pm("Live Show")
    diff = channel_engine.classify_channels(desired, deployed, prior)
    assert len(diff["delete"]) == 1, "planner-managed live channel removal must go to delete"
    assert diff["delete"][0]["name"] == "Live Show"
    assert diff["unchanged"] == []
    assert diff["foreign"] == []


def test_live_channel_with_changed_content_goes_to_update_not_delete():
    """A live channel whose content changed is classified as update-in-place.
    Invariant 2: never delete-and-recreate a live channel."""
    deployed = [_ch("Live Show", 5, live=True, content=["Old Season"])]
    desired = [_ch("Live Show", 5, live=True, content=["New Season"])]
    diff = channel_engine.classify_channels(desired, deployed, _pm("live show"))
    assert diff["delete"] == [], "live channel must NEVER be in delete bucket when still desired"
    assert len(diff["update"]) == 1
    assert diff["update"][0]["desired"]["name"] == "Live Show"


def test_live_channel_unchanged_stays_in_unchanged():
    ch = _ch("Live Show", 5, live=True)
    diff = channel_engine.classify_channels([ch], [ch], _pm("live show"))
    assert diff["delete"] == []
    assert diff["update"] == []
    assert len(diff["unchanged"]) == 1


# ── Bootstrapping: no prior_managed → nothing deleted ─────────────────────────

def test_no_prior_managed_nothing_deleted():
    """When prior_managed is empty (first run / bootstrapping), no deployed channel
    is deleted — they all go to 'foreign' as a safe conservative fallback."""
    deployed = [_ch("Comedy", 1), _ch("Action", 2)]
    desired = []
    diff = channel_engine.classify_channels(desired, deployed, set())
    assert diff["delete"] == []
    assert len(diff["foreign"]) == 2


def test_prior_managed_none_defaults_to_empty_no_deletes():
    """Passing prior_managed=None is the same as empty — nothing is deleted."""
    deployed = [_ch("Comedy", 1)]
    desired = []
    diff = channel_engine.classify_channels(desired, deployed, None)
    assert diff["delete"] == []
    assert len(diff["foreign"]) == 1


# ── Orphan safety (INVARIANT 3) ───────────────────────────────────────────────

def test_orphan_channels_are_never_in_any_bucket():
    """Orphan channels (in Tunarr but absent from channels.json) are outside
    both the desired and deployed input sets.  They cannot appear in any
    bucket.  This test demonstrates the contract: the route feeds
    channels.json (managed channels) as 'deployed', so orphans are simply
    never passed in.
    """
    # Simulated: channels.json has one managed channel; Tunarr has an orphan.
    # The orphan is never included in the 'deployed' input to classify_channels.
    desired = [_ch("Managed Channel", 1)]
    deployed = [_ch("Managed Channel", 1)]  # orphan is NOT here
    # Orphan would be some channel in Tunarr not in channels.json.

    diff = channel_engine.classify_channels(desired, deployed, _pm("managed channel"))
    names_in_diff = (
        {c["name"] for c in diff["create"]}
        | {c["name"] for c in diff["delete"]}
        | {item["desired"]["name"] for item in diff["update"]}
        | {c["name"] for c in diff["unchanged"]}
        | {c["name"] for c in diff["foreign"]}
    )
    assert "Orphan Channel" not in names_in_diff
    assert len(diff["unchanged"]) == 1


# ── Case-insensitive name matching ────────────────────────────────────────────

def test_name_matching_is_case_insensitive():
    # Same channel content, just different capitalisation in the name.
    content = ["Some Film"]
    desired = [_ch("comedy movies", 1, content=content)]
    deployed = [_ch("Comedy Movies", 1, content=content)]
    diff = channel_engine.classify_channels(desired, deployed, _pm("comedy movies"))
    # Same name (case-insensitive) and same content → unchanged
    assert diff["create"] == []
    assert diff["delete"] == []
    assert diff["update"] == []
    assert len(diff["unchanged"]) == 1


def test_name_matching_strips_whitespace():
    content = ["Some Film"]
    desired = [_ch("  Comedy  ", 1, content=content)]
    deployed = [_ch("Comedy", 1, content=content)]
    diff = channel_engine.classify_channels(desired, deployed, _pm("comedy"))
    assert diff["create"] == []
    assert diff["delete"] == []
    assert len(diff["unchanged"]) == 1


# ── Empty inputs ──────────────────────────────────────────────────────────────

def test_both_empty():
    diff = channel_engine.classify_channels([], [], set())
    assert diff == {"create": [], "delete": [], "update": [], "unchanged": [], "foreign": []}


def test_desired_only():
    diff = channel_engine.classify_channels([_ch("A")], [], set())
    assert len(diff["create"]) == 1
    assert diff["delete"] == diff["update"] == diff["unchanged"] == diff["foreign"] == []


def test_deployed_only_with_prior_managed():
    diff = channel_engine.classify_channels([], [_ch("A")], _pm("a"))
    assert len(diff["delete"]) == 1
    assert diff["create"] == diff["update"] == diff["unchanged"] == diff["foreign"] == []


def test_deployed_only_without_prior_managed():
    diff = channel_engine.classify_channels([], [_ch("A")], set())
    assert len(diff["foreign"]) == 1
    assert diff["create"] == diff["delete"] == diff["update"] == diff["unchanged"] == []
