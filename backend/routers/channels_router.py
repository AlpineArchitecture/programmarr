import asyncio
import json
import os
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

# backend/ is on sys.path when running under uvicorn/the app; add it for direct
# imports (tests, type checkers) so channel_engine and scheduler resolve correctly.
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import channel_engine  # noqa: E402
import scheduler       # noqa: E402  (shared deploy_lock)

router = APIRouter()
DATA_DIR = Path(os.environ.get("PROGRAMMARR_DATA", Path(__file__).parent.parent.parent))


def _path() -> Path:
    return DATA_DIR / "channels.json"


def _load_config() -> dict:
    try:
        with open(DATA_DIR / "config.json") as f:
            return json.load(f)
    except Exception:
        return {}


def load() -> dict:
    try:
        with open(_path()) as f:
            data = json.load(f)
        if isinstance(data, list):
            return {"channels": data, "orphaned": [], "suggested_channels": []}
        return data
    except FileNotFoundError:
        return {"channels": [], "orphaned": [], "suggested_channels": []}
    except Exception as e:
        raise HTTPException(500, f"channels.json unreadable: {e}")


def save(data: dict):
    with open(_path(), "w") as f:
        json.dump(data, f, indent=2)


@router.get("/channels")
def get_channels():
    return load()


@router.put("/channels")
def replace_channels(data: dict):
    save(data)
    return {"ok": True}


@router.get("/channels/{number}")
def get_channel(number: int):
    for ch in load().get("channels", []):
        if ch.get("number") == number:
            return ch
    raise HTTPException(404, f"Channel {number} not found")


@router.put("/channels/{number}")
def update_channel(number: int, channel: dict):
    data = load()
    for i, ch in enumerate(data.get("channels", [])):
        if ch.get("number") == number:
            data["channels"][i] = channel
            save(data)
            return {"ok": True}
    raise HTTPException(404, f"Channel {number} not found")


@router.delete("/channels/{number}")
def delete_channel(number: int):
    data = load()
    before = len(data.get("channels", []))
    data["channels"] = [ch for ch in data.get("channels", []) if ch.get("number") != number]
    if len(data["channels"]) == before:
        raise HTTPException(404, f"Channel {number} not found")
    save(data)
    return {"ok": True}


@router.post("/channels/{number}/apply")
async def apply_channel(number: int):
    """Push ONE channel to Tunarr in place (preserves Tunarr id / Plex mapping).
    Edit-only: the channel must already exist in Tunarr — new channels go through
    the Planner deploy flow."""
    ch = next((c for c in load().get("channels", []) if c.get("number") == number), None)
    if ch is None:
        raise HTTPException(404, f"Channel {number} not in channels.json")

    cfg = _load_config()
    tunarr_url = cfg.get("tunarr_url", "").rstrip("/")
    plex_url = cfg.get("plex_url", "").rstrip("/")
    plex_token = cfg.get("plex_token", "")
    if not tunarr_url:
        raise HTTPException(400, "Tunarr not configured")

    def _do():
        movie_map, show_map = channel_engine.build_library_index(tunarr_url)

        plex_sections, collection_cache = [], {}
        if any(isinstance(it, dict) and "collection" in it for it in ch.get("content", [])):
            if plex_url and plex_token:
                plex_sections = channel_engine.get_plex_sections(plex_url, plex_token)

        resolved, _missing = channel_engine.resolve_content(
            ch.get("content", []), movie_map, show_map,
            plex_url=plex_url, plex_token=plex_token,
            plex_sections=plex_sections, collection_cache=collection_cache,
        )
        if not resolved:
            raise channel_engine.ChannelEngineError(
                "resolved to empty — refusing to wipe the channel")

        if channel_engine.find_channel_by_number(tunarr_url, number) is None:
            raise channel_engine.ChannelEngineError(
                f"Channel #{number} not in Tunarr — create it in the Planner first")

        comm = ch.get("commercials") or {}
        pad_ms = int(comm.get("pad_minutes", 5)) * 60000 if comm.get("filler_list_id") else 0
        channel_engine.update_channel_in_place(
            tunarr_url, number, ch.get("shuffle", "shuffle"), resolved, pad_ms=pad_ms)
        return len(resolved)

    try:
        async with scheduler.deploy_lock:
            count = await asyncio.to_thread(_do)
        return {"ok": True, "number": number, "program_count": count}
    except channel_engine.ChannelEngineError as e:
        raise HTTPException(409, str(e))


@router.get("/library/titles")
def library_titles():
    csv = DATA_DIR / "plex_library.csv"
    if not csv.exists():
        return []
    titles = []
    try:
        with open(csv, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i == 0:
                    continue
                parts = line.split(",", 1)
                if parts:
                    titles.append(parts[0].strip().strip('"'))
    except Exception:
        pass
    return titles
