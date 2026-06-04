"""Live-channel recipe endpoints.

Currently exposes the author-time franchise-match preview. This is the first
place the backend imports channel_engine in-process (rather than spawning it as
a subprocess), so it also establishes the sys.path wiring the future scheduler
reuses: SCRIPTS_DIR holds the pipeline scripts but isn't on the path by default.
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

DATA_DIR = Path(os.environ.get("PROGRAMMARR_DATA", Path(__file__).parent.parent.parent))
SCRIPTS_DIR = Path(os.environ.get("PROGRAMMARR_SCRIPTS", Path(__file__).parent.parent.parent))

# channel_engine.py lives at SCRIPTS_DIR (repo root in dev, /app in Docker), which
# is not on sys.path for the backend process — add it before importing.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import channel_engine  # noqa: E402

router = APIRouter()


def _load_config() -> dict:
    try:
        with open(DATA_DIR / "config.json") as f:
            return json.load(f)
    except Exception:
        return {}


class PreviewRequest(BaseModel):
    value: str
    exclude: list[str] = []
    order: Optional[str] = None


@router.post("/recipes/preview")
def preview_recipe(req: PreviewRequest):
    """Show exactly which current Tunarr titles a title_contains rule matches.

    Powers the author-time confirm step: the user sees the matched titles (in the
    order they'll air) before saving a live recipe, so a bad rule is caught up front.
    """
    if not req.value.strip():
        raise HTTPException(400, "match value is required")

    cfg = _load_config()
    tunarr_url = cfg.get("tunarr_url", "").rstrip("/")
    if not tunarr_url:
        raise HTTPException(400, "Tunarr not configured")

    try:
        movie_map, show_map = channel_engine.build_library_index(tunarr_url)
    except channel_engine.ChannelEngineError as e:
        raise HTTPException(502, f"Tunarr library unavailable: {e}")

    _, preview = channel_engine.match_titles(
        req.value, movie_map, show_map, order=req.order, exclude=req.exclude
    )
    return {"value": req.value, "order": req.order, "count": len(preview), "matches": preview}
