"""test_stream_failures.py — a broken pipeline run must end, not hang.

The SSE generator yields 'start', then lines, then 'done'. The browser keeps a job
spinning until it sees 'done'. Anything raising after the response has started
(missing interpreter, bad SCRIPTS_DIR, unwritable log dir) used to kill the
generator mid-stream: no error, no return code, a spinner forever.
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

from routers import pipeline_router as pr


def drain(gen):
    async def _run():
        return [chunk async for chunk in gen]
    return asyncio.run(_run())


def events(chunks):
    out = []
    for c in chunks:
        for line in c.splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


def test_subprocess_launch_failure_still_emits_done(monkeypatch, tmp_path):
    monkeypatch.setattr(pr, "LOGS_DIR", tmp_path / "logs")

    async def boom(*a, **k):
        raise FileNotFoundError("no such interpreter")
    monkeypatch.setattr(pr.asyncio, "create_subprocess_exec", boom)

    evs = events(drain(pr._stream("export.py", [], "export")))
    kinds = [e["type"] for e in evs]
    assert kinds[0] == "start"
    assert kinds[-1] == "done", "a launch failure must still terminate the stream"
    assert evs[-1]["returncode"] == -1
    assert "no such interpreter" in evs[-1]["error"]


def test_launch_failure_reports_the_reason_as_a_line(monkeypatch, tmp_path):
    """The user reads the inline terminal — the reason has to appear there."""
    monkeypatch.setattr(pr, "LOGS_DIR", tmp_path / "logs")

    async def boom(*a, **k):
        raise PermissionError("denied")
    monkeypatch.setattr(pr.asyncio, "create_subprocess_exec", boom)

    evs = events(drain(pr._stream("create.py", [], "deploy")))
    assert any(e["type"] == "line" and "denied" in e["text"] for e in evs)


class FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)
    def __aiter__(self):
        return self
    async def __anext__(self):
        if not self._lines:
            raise StopAsyncIteration
        return self._lines.pop(0)


class FakeProc:
    def __init__(self, lines, returncode=0):
        self.stdout = FakeStdout(lines)
        self.returncode = returncode
    async def wait(self):
        return self.returncode


def test_successful_run_still_completes_normally(monkeypatch, tmp_path):
    monkeypatch.setattr(pr, "LOGS_DIR", tmp_path / "logs")

    async def fake_exec(*a, **k):
        return FakeProc([b"hello\n", b"world\n"], returncode=0)
    monkeypatch.setattr(pr.asyncio, "create_subprocess_exec", fake_exec)

    evs = events(drain(pr._stream("export.py", [], "export")))
    assert [e["text"] for e in evs if e["type"] == "line"] == ["hello", "world"]
    assert evs[-1]["type"] == "done" and evs[-1]["returncode"] == 0
    assert evs[-1]["log"], "a successful run names its log file"


def test_unwritable_log_does_not_sink_a_successful_run(monkeypatch, tmp_path):
    monkeypatch.setattr(pr, "LOGS_DIR", tmp_path / "logs")

    async def fake_exec(*a, **k):
        return FakeProc([b"done\n"], returncode=0)
    monkeypatch.setattr(pr.asyncio, "create_subprocess_exec", fake_exec)

    real_open = open
    def bad_open(path, *a, **k):
        if str(path).endswith(".log"):
            raise OSError("read-only filesystem")
        return real_open(path, *a, **k)
    monkeypatch.setattr("builtins.open", bad_open)

    evs = events(drain(pr._stream("export.py", [], "export")))
    assert evs[-1]["type"] == "done"
    assert evs[-1]["returncode"] == 0, "the run succeeded; only the log failed"
    assert any("Could not write log" in e.get("text", "") for e in evs)


def test_mid_stream_failure_still_emits_done(monkeypatch, tmp_path):
    monkeypatch.setattr(pr, "LOGS_DIR", tmp_path / "logs")

    class ExplodingStdout:
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise RuntimeError("pipe died")

    class P:
        stdout = ExplodingStdout()
        returncode = None
        async def wait(self):
            return None

    async def fake_exec(*a, **k):
        return P()
    monkeypatch.setattr(pr.asyncio, "create_subprocess_exec", fake_exec)

    evs = events(drain(pr._stream("create.py", [], "deploy")))
    assert evs[-1]["type"] == "done" and evs[-1]["returncode"] == -1
    assert "pipe died" in evs[-1]["error"]
