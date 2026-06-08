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
    tmdb_api_key: str = ""
    auth_username: str = ""
    auth_password: str = ""


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
    return config


@router.post("/config")
def save_config(config: ConfigModel):
    existing = load_config()
    data = config.model_dump()
    for field in ("auth_password", "plex_token", "tmdb_api_key"):
        if data.get(field) == MASK:
            data[field] = existing.get(field, "")
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
    with open(_path(), "w") as f:
        json.dump(merged, f, indent=4)
    return {"ok": True}


@router.get("/config/status")
def config_status():
    config = load_config()
    return {
        "configured": bool(
            config.get("tunarr_url") and config.get("plex_url") and config.get("plex_token")
        ),
        "has_tmdb": bool(config.get("tmdb_api_key")),
        "has_auth": bool(config.get("auth_username") and config.get("auth_password")),
    }
