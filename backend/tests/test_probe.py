"""run_probe — the Deploy step must probe the in-progress draft, not the deployed record.

The probe output is the *sole* source of the Deploy review/selection list, so if it reads
channels.json (the deployed record) instead of channels.draft.json (what compose + AI extras
+ collections actually wrote), AI and collection channels never appear and never deploy.
"""

import asyncio
import json


async def _collect(pr, **kwargs):
    """Call run_probe and drain its StreamingResponse (the fake _locked_stream is a no-op)."""
    resp = await pr.run_probe(**kwargs)
    async for _ in resp.body_iterator:
        pass
    return resp


def _write(pr, filename, channels):
    data = {"channels": channels, "orphaned": [], "suggested_channels": []}
    (pr._test_data_dir / filename).write_text(json.dumps(data), encoding="utf-8")


def test_probe_targets_draft_when_present(pr):
    captured = {}

    async def fake_locked_stream(script, args, tag):
        captured["args"] = args
        return
        yield  # pragma: no cover — keeps this an async generator

    pr._locked_stream = fake_locked_stream
    _write(pr, "channels.json", [{"number": 10, "name": "Deployed", "content": []}])
    _write(pr, "channels.draft.json", [{"number": 1, "name": "Drafted", "content": []}])

    asyncio.run(_collect(pr))

    assert "--json" in captured["args"], "probe must point at an explicit file when a draft exists"
    i = captured["args"].index("--json")
    assert captured["args"][i + 1] == "channels.draft.json"


def test_probe_falls_back_to_default_without_draft(pr):
    captured = {}

    async def fake_locked_stream(script, args, tag):
        captured["args"] = args
        return
        yield  # pragma: no cover

    pr._locked_stream = fake_locked_stream
    _write(pr, "channels.json", [{"number": 10, "name": "Deployed", "content": []}])
    # no channels.draft.json

    asyncio.run(_collect(pr))

    # No --json → create.py uses its default (channels.json).
    assert "--json" not in captured["args"]


def test_probe_forwards_protected(pr):
    captured = {}

    async def fake_locked_stream(script, args, tag):
        captured["args"] = args
        return
        yield  # pragma: no cover

    pr._locked_stream = fake_locked_stream
    _write(pr, "channels.draft.json", [{"number": 1, "name": "Drafted", "content": []}])

    asyncio.run(_collect(pr, protected="10,20"))

    assert "--protect" in captured["args"]
    i = captured["args"].index("--protect")
    assert captured["args"][i + 1] == "10,20"
