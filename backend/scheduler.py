"""Live-channel scheduler.

A single in-process asyncio loop that keeps channels marked "live": true in
channels.json fresh. Each cycle re-resolves a live channel's content against the
live Tunarr library and patches the channel IN PLACE (never delete/recreate) only
when the resolved program set differs from what's currently scheduled.

Design notes:
  - No state file. The "current" side of the diff is read straight from Tunarr
    (read_channel_programming), so the loop survives container restarts for free
    and an unchanged channel is a cheap no-op (no guide churn).
  - Tunarr is the source of truth; the loop never writes channels.json. A live
    channel's content definition (show name, collection ref, or {"match": ...}
    franchise ref) stays as-authored and is simply re-resolved each cycle.
  - deploy_lock serializes the cycle against manual deploys (pipeline endpoints
    that spawn create.py acquire the same lock), so the scheduler never patches a
    channel a deploy is mid-deleting.
  - Blocking network work runs in a worker thread (asyncio.to_thread) so the cycle
    never stalls the FastAPI event loop.

Ships OFF: the loop does nothing unless config.json has recipes_enabled: true.
"""

import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("PROGRAMMARR_DATA", Path(__file__).parent.parent))
SCRIPTS_DIR = Path(os.environ.get("PROGRAMMARR_SCRIPTS", Path(__file__).parent.parent))
LOGS_DIR = DATA_DIR / "logs"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import channel_engine  # noqa: E402

# Shared with pipeline_router: any endpoint that spawns create.py acquires this so
# a manual deploy and a scheduler cycle never touch Tunarr at the same time.
deploy_lock = asyncio.Lock()

# In-memory runtime state. recipes_enabled / recipe_interval_hours are persistent
# (config.json); `paused` is a runtime kill switch that survives until restart.
_state: dict = {
    "paused": False,
    "running": False,
    "last_cycle": None,      # summary dict of the most recent cycle
    "last_auto_run": None,   # event-loop time of last automatic cycle (None = never)
}

DEFAULT_INTERVAL_HOURS = 12


# ── Config / channels ──────────────────────────────────────────────────────────

def _load_config() -> dict:
    try:
        with open(DATA_DIR / "config.json") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_channels() -> list:
    """Read channels.json defensively — a torn mid-write read just skips the cycle."""
    try:
        with open(DATA_DIR / "channels.json", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return data.get("channels", [])
    except Exception:
        return []


def _live_channels(channels: list) -> list:
    return [ch for ch in channels if ch.get("live")]


# ── Diff helpers ───────────────────────────────────────────────────────────────

def _program_ids(resolved: list) -> set:
    return {p["id"] for item in resolved for p in item["programs"]}


def _id_label_map(movie_map: dict, show_map: dict) -> dict:
    """Map each program id -> a human label (movie title, or show title for episodes)."""
    labels: dict = {}
    for p in movie_map.values():
        labels[p["id"]] = p.get("program", {}).get("title", "(movie)")
    for s in show_map.values():
        for p in s.get("programs", []):
            labels[p["id"]] = s["title"]
    return labels


def _summarize(ids: set, id_label: dict) -> list:
    """Render a set of program ids as ['Title', 'Show x8'] (dedup + counts)."""
    counts = Counter(id_label.get(i, "(unknown)") for i in ids)
    return [lbl + (f" x{n}" if n > 1 else "") for lbl, n in counts.most_common()]


# ── The cycle ──────────────────────────────────────────────────────────────────

def _run_cycle_blocking(apply: bool) -> dict:
    """Synchronous body of one cycle. Runs in a worker thread."""
    started = datetime.now(timezone.utc)
    cfg = _load_config()
    tunarr_url = cfg.get("tunarr_url", "").rstrip("/")
    plex_url = cfg.get("plex_url", "").rstrip("/")
    plex_token = cfg.get("plex_token", "")

    summary: dict = {
        "time": started.isoformat(),
        "apply": apply,
        "live": 0,
        "changed": 0,
        "changes": [],
        "skipped": [],
        "error": None,
    }

    if not tunarr_url:
        summary["error"] = "Tunarr not configured"
        return summary

    live = _live_channels(_load_channels())
    summary["live"] = len(live)
    if not live:
        return summary

    try:
        movie_map, show_map = channel_engine.build_library_index(tunarr_url)
    except channel_engine.ChannelEngineError as e:
        summary["error"] = f"library index failed: {e}"
        return summary

    id_label = _id_label_map(movie_map, show_map)

    # Plex section lookup only if a live channel uses collection refs
    plex_sections, collection_cache = [], {}
    if any(isinstance(it, dict) and "collection" in it
           for ch in live for it in ch.get("content", [])):
        if plex_url and plex_token:
            plex_sections = channel_engine.get_plex_sections(plex_url, plex_token)

    for ch in live:
        number = ch.get("number")
        name = ch.get("name", "Unnamed")
        resolved, _missing = channel_engine.resolve_content(
            ch.get("content", []), movie_map, show_map,
            plex_url=plex_url, plex_token=plex_token,
            plex_sections=plex_sections, collection_cache=collection_cache,
        )
        fresh_ids = _program_ids(resolved)

        tch = channel_engine.find_channel_by_number(tunarr_url, number)
        if not tch:
            summary["skipped"].append({"number": number, "name": name, "reason": "not in Tunarr"})
            continue
        cur_ids = channel_engine.read_channel_programming(tunarr_url, tch["id"])
        if cur_ids is None:
            summary["skipped"].append({"number": number, "name": name, "reason": "could not read programming"})
            continue

        if fresh_ids == cur_ids:
            continue  # no change — cheap no-op, no guide churn

        added, removed = fresh_ids - cur_ids, cur_ids - fresh_ids
        change = {
            "number": number,
            "name": name,
            "added": _summarize(added, id_label),
            "added_count": len(added),
            "removed_count": len(removed),
            "applied": False,
        }
        if apply:
            if not fresh_ids:
                # resolves to nothing — refuse to wipe the channel; flag it
                summary["skipped"].append({"number": number, "name": name, "reason": "resolved to empty — not patched"})
                continue
            try:
                channel_engine.update_channel_in_place(
                    tunarr_url, number, ch.get("shuffle", "shuffle"), resolved)
                change["applied"] = True
            except channel_engine.ChannelEngineError as e:
                summary["skipped"].append({"number": number, "name": name, "reason": str(e)})
                continue
        summary["changes"].append(change)

    summary["changed"] = len(summary["changes"])
    _write_log(summary)
    return summary


def _write_log(summary: dict) -> None:
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOGS_DIR / "recipes.log", "a", encoding="utf-8") as f:
            mode = "apply" if summary["apply"] else "dry-run"
            f.write(f"[{summary['time']}] cycle {mode} live={summary['live']} "
                    f"changed={summary['changed']}"
                    + (f" error={summary['error']}" if summary['error'] else "") + "\n")
            for c in summary["changes"]:
                tag = "applied" if c["applied"] else "would change"
                added = (": +" + ", ".join(c["added"])) if c["added"] else ""
                f.write(f"    #{c['number']} {c['name']} [{tag}] "
                        f"+{c['added_count']} -{c['removed_count']}{added}\n")
            for s in summary["skipped"]:
                f.write(f"    skip #{s['number']} {s['name']}: {s['reason']}\n")
    except Exception:
        pass  # logging must never break a cycle


async def run_cycle(apply: bool = True) -> dict:
    """Run one cycle under the deploy lock. Blocking work offloaded to a thread."""
    async with deploy_lock:
        _state["running"] = True
        try:
            summary = await asyncio.to_thread(_run_cycle_blocking, apply)
        finally:
            _state["running"] = False
    _state["last_cycle"] = summary
    return summary


# ── Background loop ────────────────────────────────────────────────────────────

async def scheduler_loop() -> None:
    """Wake every minute; run a cycle when enabled, not paused, and interval elapsed.

    Checking every 60s (rather than sleeping the full interval) lets config toggles
    — recipes_enabled, recipe_interval_hours — and the runtime pause take effect
    within a minute, mirroring how the auth middleware re-reads config each request.
    """
    while True:
        try:
            cfg = _load_config()
            enabled = bool(cfg.get("recipes_enabled", False))
            interval_h = float(cfg.get("recipe_interval_hours", DEFAULT_INTERVAL_HOURS) or DEFAULT_INTERVAL_HOURS)
            interval_s = max(60.0, interval_h * 3600.0)
            now = asyncio.get_event_loop().time()
            last = _state["last_auto_run"]
            due = last is None or (now - last) >= interval_s
            if enabled and not _state["paused"] and due:
                _state["last_auto_run"] = now
                await run_cycle(apply=True)
        except Exception as e:  # never let the loop die
            _write_log({"time": datetime.now(timezone.utc).isoformat(), "apply": True,
                        "live": 0, "changed": 0, "changes": [], "skipped": [],
                        "error": f"loop error: {e}"})
        await asyncio.sleep(60)


# ── Status (for the recipes router / UI) ───────────────────────────────────────

def get_status() -> dict:
    cfg = _load_config()
    return {
        "enabled": bool(cfg.get("recipes_enabled", False)),
        "paused": _state["paused"],
        "running": _state["running"],
        "interval_hours": float(cfg.get("recipe_interval_hours", DEFAULT_INTERVAL_HOURS) or DEFAULT_INTERVAL_HOURS),
        "live_count": len(_live_channels(_load_channels())),
        "last_cycle": _state["last_cycle"],
    }


def set_paused(paused: bool) -> dict:
    _state["paused"] = bool(paused)
    return get_status()
