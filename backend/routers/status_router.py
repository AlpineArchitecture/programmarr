import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()
DATA_DIR = Path(os.environ.get("PROGRAMMARR_DATA", Path(__file__).parent.parent.parent))


def load_config() -> dict:
    try:
        with open(DATA_DIR / "config.json") as f:
            return json.load(f)
    except Exception:
        return {}


def probe(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return {"ok": True, "status": r.status}
    except urllib.error.HTTPError as e:
        return {"ok": True, "status": e.code}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/status")
def get_status():
    cfg = load_config()
    tunarr = cfg.get("tunarr_url", "").rstrip("/")
    plex = cfg.get("plex_url", "").rstrip("/")
    token = cfg.get("plex_token", "")

    tr = {"ok": False, "error": "Not configured", "url": tunarr}
    pr = {"ok": False, "error": "Not configured", "url": plex}

    if tunarr:
        tr = {**probe(f"{tunarr}/api/channels"), "url": tunarr}
    if plex and token:
        pr = {**probe(f"{plex}/?X-Plex-Token={token}"), "url": plex}

    return {"tunarr": tr, "plex": pr}


@router.get("/tunarr/channels")
def tunarr_channels():
    cfg = load_config()
    url = cfg.get("tunarr_url", "").rstrip("/")
    if not url:
        return []
    try:
        with urllib.request.urlopen(f"{url}/api/channels", timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return []


@router.get("/tunarr/filler-lists")
def tunarr_filler_lists():
    """Filler lists in Tunarr — powers the Commercials picker in the channel editor.

    Returns [{id, name, contentCount}]. The user creates/manages these in Tunarr;
    Programmarr only references one by id when a channel has commercials enabled.
    """
    cfg = load_config()
    url = cfg.get("tunarr_url", "").rstrip("/")
    if not url:
        return []
    try:
        with urllib.request.urlopen(f"{url}/api/filler-lists", timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return []
