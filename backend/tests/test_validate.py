"""validate(append=True) — collision renumber AND name-dedup (skipped_dupes)."""

import asyncio
import json


def _run(coro):
    return asyncio.run(coro)


def _write_channels(pr, channels):
    data = {"channels": channels, "orphaned": [], "suggested_channels": []}
    (pr._test_data_dir / "channels.json").write_text(json.dumps(data), encoding="utf-8")


def test_fresh_write_from_jsonl(pr):
    jsonl = (
        '{"number": 10, "name": "Comedy", "shuffle": "shuffle", "content": ["A"]}\n'
        '{"number": 11, "name": "Horror", "shuffle": "shuffle", "content": ["B"]}'
    )
    # file=None explicitly avoids the File(None) sentinel being truthy.
    res = _run(pr.validate(file=None, content=jsonl, append=False))
    assert res["ok"] is True
    assert res["count"] == 2
    written = json.loads((pr._test_data_dir / "channels.json").read_text(encoding="utf-8"))
    assert [c["number"] for c in written["channels"]] == [10, 11]


def test_fresh_write_accepts_bare_array(pr):
    arr = '[{"number": 5, "name": "X", "content": []}]'
    res = _run(pr.validate(file=None, content=arr, append=False))
    assert res["ok"] is True
    assert res["count"] == 1


def test_append_renumbers_collision(pr):
    _write_channels(pr, [{"number": 10, "name": "Comedy", "content": ["A"]}])
    incoming = '{"number": 10, "name": "Heist Films", "content": ["B"]}'
    res = _run(pr.validate(file=None, content=incoming, append=True))
    assert res["added"] == 1
    nums = {c["name"]: c["number"] for c in res["channels"]}
    assert nums["Comedy"] == 10
    assert nums["Heist Films"] == 11   # bumped off the collision


def test_append_skips_name_duplicate_case_insensitive(pr):
    _write_channels(pr, [{"number": 10, "name": "Comedy", "content": ["A"]}])
    incoming = '{"number": 99, "name": "comedy", "content": ["B"]}'
    res = _run(pr.validate(file=None, content=incoming, append=True))
    assert res["added"] == 0
    assert res["skipped_dupes"] == 1
    assert res["count"] == 1  # nothing stacked


def test_append_mixed_batch(pr):
    _write_channels(pr, [{"number": 10, "name": "Comedy", "content": ["A"]}])
    incoming = (
        '{"number": 10, "name": "Heist Films", "content": ["B"]}\n'   # collision -> renumber
        '{"number": 12, "name": "COMEDY", "content": ["C"]}\n'        # dup name -> skip
        '{"number": 20, "name": "Whodunits", "content": ["D"]}'       # clean add
    )
    res = _run(pr.validate(file=None, content=incoming, append=True))
    assert res["added"] == 2
    assert res["skipped_dupes"] == 1
    names = {c["name"] for c in res["channels"]}
    assert names == {"Comedy", "Heist Films", "Whodunits"}


def test_invalid_input_reports_error(pr):
    res = _run(pr.validate(file=None, content="not json at all", append=False))
    assert res["ok"] is False
