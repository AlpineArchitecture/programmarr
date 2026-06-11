import json
import os
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()
DATA_DIR = Path(os.environ.get("PROGRAMMARR_DATA", Path(__file__).parent.parent.parent))

MASK = "••••••••"


class ConfigModel(BaseModel):
    tunarr_url: str = ""
    plex_url: str = ""
    plex_token: str = ""
    # List of {name, url, token} Plex server entries. Replaces the legacy scalar
    # plex_url/plex_token pair; both are kept for CLI backward compat.
    plex_servers: list = []
    tmdb_api_key: str = ""
    auth_username: str = ""
    auth_password: str = ""
    # Ordered list of category keys controlling channel numbering order.
    # Empty ⇒ canonical default from channel_blocks.CANONICAL_ORDER at use time.
    channel_order: list = []
    # Whether the app polls GitHub for a newer release (the in-app update banner).
    # Default on; stored explicitly so the falsy-prune below can't drop a False.
    update_check_enabled: bool = True


def _path() -> Path:
    return DATA_DIR / "config.json"


def load_config() -> dict:
    try:
        with open(_path()) as f:
            return json.load(f)
    except Exception:
        return {}


@router.get("/config")
def get_config():
    config = load_config()
    if config.get("auth_password"):
        config["auth_password"] = MASK
    if config.get("plex_token"):
        config["plex_token"] = MASK
    if config.get("tmdb_api_key"):
        config["tmdb_api_key"] = MASK
    if config.get("plex_servers"):
        config["plex_servers"] = [
            {**s, "token": MASK} if s.get("token") else s
            for s in config["plex_servers"]
        ]
    return config


@router.post("/config")
def save_config(config: ConfigModel):
    existing = load_config()
    data = config.model_dump()
    for field in ("auth_password", "plex_token", "tmdb_api_key"):
        if data.get(field) == MASK:
            data[field] = existing.get(field, "")
    # Lists must bypass the falsy-prune below ([] is falsy but meaningful as "no change").
    # channel_order: only overwrite when non-empty so an Onboarding save can't wipe it.
    order = data.pop("channel_order", None) or []
    # plex_servers: restore masked tokens by matching on URL, then write if non-empty.
    plex_servers = data.pop("plex_servers", None) or []
    if plex_servers:
        existing_by_url = {s.get("url", ""): s for s in existing.get("plex_servers", [])}
        restored = []
        for srv in plex_servers:
            if srv.get("token") == MASK:
                srv = {**srv, "token": existing_by_url.get(srv.get("url", ""), {}).get("token", "")}
            restored.append(srv)
        plex_servers = restored
    # Booleans must bypass the falsy-prune below (False is falsy → would be deleted).
    update_check = bool(data.pop("update_check_enabled", True))
    # Merge onto existing so keys the UI form doesn't manage are preserved — e.g.
    # the live-channel keys (recipes_enabled, recipe_interval_hours) and the advanced
    # config keys (tunarr_channel_group, tunarr_stream_mode), which are edited directly
    # in config.json and must survive a Settings save. UI fields left empty are removed.
    merged = dict(existing)
    for k, v in data.items():
        if v:
            merged[k] = v
        else:
            merged.pop(k, None)
    if order:
        merged["channel_order"] = order
    if plex_servers:
        merged["plex_servers"] = plex_servers
        # Keep legacy scalar fields in sync with the primary server for CLI compat.
        merged["plex_url"]   = plex_servers[0].get("url", "")
        merged["plex_token"] = plex_servers[0].get("token", "")
    merged["update_check_enabled"] = update_check
    # Preserve old channel_blocks key silently (don't crash; just ignore it).
    with open(_path(), "w") as f:
        json.dump(merged, f, indent=4)
    return {"ok": True}


@router.get("/config/status")
def config_status():
    config = load_config()
    has_plex = bool(config.get("plex_servers")) or bool(
        config.get("plex_url") and config.get("plex_token")
    )
    return {
        "configured": bool(config.get("tunarr_url") and has_plex),
        "has_tmdb": bool(config.get("tmdb_api_key")),
        "has_auth": bool(config.get("auth_username") and config.get("auth_password")),
    }
