import json
import os
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

GITHUB_LATEST_RELEASE = (
    "https://api.github.com/repos/AlpineArchitecture/programmarr/releases/latest"
)


def _parse_semver(s: str) -> tuple[int, int, int]:
    """'v0.10.1' -> (0, 10, 1). Tolerant: missing parts -> 0; a pre-release suffix
    on a part ('1-beta') keeps only the leading digits. Raises ValueError on no digits."""
    s = (s or "").strip().lstrip("vV")
    if not s:
        raise ValueError("empty version")
    out = []
    for part in s.split(".")[:3]:
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)  # type: ignore[return-value]


def is_newer(latest: str, current: str) -> bool:
    """True iff `latest` is a strictly higher semver than `current`. Never raises;
    any unparseable input (or empty `current`) yields False so a failed check
    degrades to 'no update' rather than crashing the UI."""
    try:
        return _parse_semver(latest) > _parse_semver(current)
    except Exception:
        return False


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


def _parse_xmltv_time(s: str) -> str:
    return datetime.strptime(s.strip(), "%Y%m%d%H%M%S %z").isoformat()


def _num_from_cid(cid: str) -> int | None:
    try:
        return int(cid.split(".")[0][1:])
    except (ValueError, IndexError):
        return None


def parse_guide_xml(xml_text: str) -> dict:
    """Pure: XMLTV string -> {channels:[...], programmes:[...]}. No network. Unit-tested directly."""
    root = ET.fromstring(xml_text)

    channels = []
    for ch in root.findall("channel"):
        num = _num_from_cid(ch.get("id", ""))
        if num is None:
            continue
        name_el = ch.find("display-name")
        icon_el = ch.find("icon")
        channels.append({
            "number": num,
            "name": (name_el.text or "").strip() if name_el is not None else f"Channel {num}",
            "icon": icon_el.get("src") if icon_el is not None else None,
        })

    programmes = []
    for pr in root.findall("programme"):
        num = _num_from_cid(pr.get("channel", ""))
        if num is None:
            continue
        title_el = pr.find("title")
        sub_el = pr.find("sub-title")
        try:
            start = _parse_xmltv_time(pr.get("start", ""))
            stop = _parse_xmltv_time(pr.get("stop", ""))
        except ValueError:
            continue
        programmes.append({
            "number": num,
            "start": start,
            "stop": stop,
            "title": (title_el.text or "").strip() if title_el is not None else "",
            "episode": (sub_el.text or "").strip() if sub_el is not None else "",
        })

    channels.sort(key=lambda c: c["number"])
    return {"channels": channels, "programmes": programmes}


@router.get("/guide")
def get_guide():
    cfg = load_config()
    url = cfg.get("tunarr_url", "").rstrip("/")
    if not url:
        return {"channels": [], "programmes": [], "error": "Tunarr not configured"}
    try:
        with urllib.request.urlopen(f"{url}/api/xmltv.xml", timeout=10) as r:
            xml_text = r.read().decode("utf-8", errors="replace")
        return parse_guide_xml(xml_text)
    except Exception as e:
        return {"channels": [], "programmes": [], "error": f"Could not reach Tunarr: {e}"}


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
