import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import scheduler  # noqa: E402  (backend/ on sys.path) — shared deploy_lock

router = APIRouter()
DATA_DIR = Path(os.environ.get("PROGRAMMARR_DATA", Path(__file__).parent.parent.parent))
SCRIPTS_DIR = Path(os.environ.get("PROGRAMMARR_SCRIPTS", Path(__file__).parent.parent.parent))
LOGS_DIR = DATA_DIR / "logs"


def _load_config() -> dict:
    try:
        with open(DATA_DIR / "config.json") as f:
            return json.load(f)
    except Exception:
        return {}


def _plex_get(base_url: str, token: str, path: str, timeout: int = 30):
    sep = "&" if "?" in path else "?"
    url = f"{base_url}{path}{sep}X-Plex-Token={token}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class CollectionSelection(BaseModel):
    name: str
    channel_number: int
    include: bool


class DeploySelection(BaseModel):
    original_number: int
    deploy_number: int
    include: bool


def _env():
    env = os.environ.copy()
    env["PROGRAMMARR_DATA"] = str(DATA_DIR)
    return env


async def _stream(script: str, args: list[str], tag: str) -> AsyncGenerator[str, None]:
    LOGS_DIR.mkdir(exist_ok=True)
    cmd = [sys.executable, str(SCRIPTS_DIR / script)] + args
    log_path = LOGS_DIR / f"{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    yield f"data: {json.dumps({'type': 'start', 'cmd': ' '.join(cmd), 'log': log_path.name})}\n\n"

    lines: list[str] = []
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(DATA_DIR),
        env=_env(),
    )

    async for raw in proc.stdout:  # type: ignore[union-attr]
        line = raw.decode("utf-8", errors="replace").rstrip()
        lines.append(line)
        yield f"data: {json.dumps({'type': 'line', 'text': line})}\n\n"

    await proc.wait()

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"# {tag} — {datetime.now().isoformat()}\n")
        f.write(f"# {' '.join(cmd)}\n\n")
        f.write("\n".join(lines))

    yield f"data: {json.dumps({'type': 'done', 'returncode': proc.returncode, 'log': log_path.name})}\n\n"


def _sse(gen: AsyncGenerator[str, None]) -> StreamingResponse:
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _locked_stream(script: str, args: list[str], tag: str) -> AsyncGenerator[str, None]:
    """Stream a subprocess while holding the shared deploy_lock for its full duration.

    Used for create.py runs (probe/deploy) so the live-channel scheduler can't patch
    a channel in the middle of a deploy deleting/recreating it (and vice versa).
    """
    async with scheduler.deploy_lock:
        async for chunk in _stream(script, args, tag):
            yield chunk


class ExportOptions(BaseModel):
    no_crossref: bool = False
    movie_sections: Optional[list[str]] = None  # None = auto-detect; [] = skip type entirely
    tv_sections: Optional[list[str]] = None


@router.get("/pipeline/libraries")
def list_libraries():
    cfg = _load_config()
    plex_url = cfg.get("plex_url", "").rstrip("/")
    plex_token = cfg.get("plex_token", "")
    if not plex_url or not plex_token:
        raise HTTPException(400, "Plex not configured")
    try:
        data = _plex_get(plex_url, plex_token, "/library/sections")
        sections = data["MediaContainer"].get("Directory", [])
    except Exception as e:
        raise HTTPException(502, f"Could not reach Plex: {e}")
    return [
        {"key": s["key"], "title": s["title"], "type": s["type"]}
        for s in sections
        if s.get("type") in ("movie", "show")
    ]


@router.post("/pipeline/export")
async def run_export(opts: ExportOptions = ExportOptions()):
    args = []
    if opts.no_crossref:
        args.append("--no-crossref")
    if opts.movie_sections is not None:
        args += ["--movie-sections", ",".join(opts.movie_sections)]
    if opts.tv_sections is not None:
        args += ["--tv-sections", ",".join(opts.tv_sections)]
    return _sse(_stream("export.py", args, "export"))


@router.get("/pipeline/csv")
def download_csv():
    p = DATA_DIR / "plex_library.csv"
    if not p.exists():
        raise HTTPException(404, "Run Export first")
    return FileResponse(str(p), filename="plex_library.csv", media_type="text/csv")


@router.get("/pipeline/csv/info")
def csv_info():
    import csv as _csv
    p = DATA_DIR / "plex_library.csv"
    if not p.exists():
        return {"exists": False}
    stat = p.stat()
    rows, movies, tv_shows, preview = 0, 0, 0, []
    try:
        with open(p, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < 21:
                    preview.append(line.rstrip())
        with open(p, encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                rows += 1
                t = row.get("Type", "")
                if t == "Movie":
                    movies += 1
                elif t == "TV":
                    tv_shows += 1
    except Exception:
        pass
    result: dict = {
        "exists": True,
        "size": stat.st_size,
        "rows": rows,
        "movies": movies,
        "tv_shows": tv_shows,
        "modified": stat.st_mtime,
        "preview": preview,
    }
    summary_p = DATA_DIR / "export_summary.json"
    if summary_p.exists():
        try:
            with open(summary_p) as f:
                s = json.load(f)
                result["skipped_movies"] = s.get("skipped_movies", 0)
                result["skipped_shows"] = s.get("skipped_shows", 0)
        except Exception:
            pass
    return result


# Canonical movie genres (display, Plex tag) and decade buckets.
# KEEP IN SYNC with generate_no_ai.py CANONICAL_GENRES / DECADE_RANGES.
CANONICAL_GENRES = [
    ("Comedy", "Comedy"), ("Action", "Action"), ("Horror", "Horror"),
    ("Sci-Fi", "Science Fiction"), ("Drama", "Drama"),
    ("Animation", "Animation"), ("Documentary", "Documentary"),
]
DECADE_BUCKETS = [
    ("70s", 1970, 1979), ("80s", 1980, 1989), ("90s", 1990, 1999),
    ("2000s", 2000, 2009), ("2010s", 2010, 2019), ("2020s", 2020, 2029),
]


def _safe_int(val):
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


@router.get("/pipeline/facets")
def library_facets(min_items: int = 5):
    """Genre/decade/marathon facets derived from plex_library.csv, with counts.

    Drives the Planner toggles: canonical genres (always returned, even at 0 so the
    UI can decide to show/hide), 'more' genres above min_items, decades present in
    the library, and the count of marathon-eligible shows (50+ episodes).
    """
    import csv as _csv
    p = DATA_DIR / "plex_library.csv"
    if not p.exists():
        return {"exists": False}

    genre_counts: dict[str, int] = {}
    decade_counts = {start: 0 for _, start, _ in DECADE_BUCKETS}
    movies = tv = marathon = 0
    with open(p, encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            t = row.get("Type", "")
            if t == "Movie":
                movies += 1
                for g in (row.get("Genres", "") or "").split("|"):
                    g = g.strip()
                    if g:
                        genre_counts[g] = genre_counts.get(g, 0) + 1
                yr = _safe_int(row.get("Year"))
                if yr is not None:
                    for _, start, end in DECADE_BUCKETS:
                        if start <= yr <= end:
                            decade_counts[start] += 1
                            break
            elif t == "TV":
                tv += 1
                eps = _safe_int(row.get("Episodes"))
                if eps is not None and eps >= 50:
                    marathon += 1

    # Case-insensitive lookup for canonical tags.
    ci_counts = {tag.lower(): n for tag, n in genre_counts.items()}
    canonical_tags = {tag.lower() for _, tag in CANONICAL_GENRES}
    canonical = [
        {"display": disp, "tag": tag, "count": ci_counts.get(tag.lower(), 0)}
        for disp, tag in CANONICAL_GENRES
    ]
    more = sorted(
        (
            {"display": tag, "tag": tag, "count": n}
            for tag, n in genre_counts.items()
            if tag.lower() not in canonical_tags and n >= min_items
        ),
        key=lambda x: (-x["count"], x["tag"].lower()),
    )
    decades = [
        {"label": label, "start": start, "end": end, "count": decade_counts[start]}
        for label, start, end in DECADE_BUCKETS
        if decade_counts[start] > 0
    ]
    return {
        "exists": True,
        "movies": movies,
        "tv_shows": tv,
        "marathon_count": marathon,
        "min_items": min_items,
        "genres": {"canonical": canonical, "more": more},
        "decades": decades,
    }


ANCHOR = "## Channel Numbering Scheme"
TYPE_LABELS = {
    "marathons": "TV Marathons", "tv_blocks": "TV Blocks", "movies": "Movie channels",
    "franchise": "Franchise series", "specialty": "Specialty channels",
}


def _read_prompt_source() -> str:
    for candidate in [DATA_DIR / "PROMPT.md", SCRIPTS_DIR / "PROMPT.md"]:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise HTTPException(404, "PROMPT.md not found")


def _strip_meta(content: str) -> str:
    """Drop the human-facing meta header above the first '---' separator line.

    Those lines (model recommendation, attach-vs-paste guidance) belong in the UI
    walkthrough, not the copied prompt. The CLI still reads the full file directly.
    """
    lines = content.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            return "\n".join(lines[i + 1:]).lstrip("\n")
    return content


def _apply_target_prefs_start(content: str, target: str, preferences: str, start: int) -> str:
    if target:
        content = content.replace("{TARGET}", target)
    if preferences:
        inj = (
            "\n## User Preferences\n\n"
            "The user has specifically requested the following channels or themes. "
            "Treat these as high-priority — if the library has enough content to support them, "
            "they must appear in the output:\n\n"
            f"{preferences}\n"
        )
        content = content.replace(ANCHOR, inj + "\n" + ANCHOR)
    if start != 10:
        o = start - 10
        content = content.replace("**10–19**", f"**{10+o}–{19+o}**")
        content = content.replace("**20–29**", f"**{20+o}–{29+o}**")
        content = content.replace("**30–49**", f"**{30+o}–{49+o}**")
        content = content.replace("**50–69**", f"**{50+o}–{69+o}**")
        content = content.replace("**70–79**", f"**{70+o}–{79+o}**")
        content = content.replace('"number": 10,', f'"number": {10+o},')
        content = content.replace('"number": 20,', f'"number": {20+o},')
        content = content.replace('"number": 30,', f'"number": {30+o},')
    return content


@router.get("/pipeline/prompt")
def get_prompt(target: str = "", preferences: str = "", start: int = 10):
    # Legacy GET: full file (meta included), used by the current Run UI. Kept
    # intact so the live UI isn't degraded before the new flow (PR2) ships.
    content = _apply_target_prefs_start(_read_prompt_source(), target, preferences, start)
    return {"content": content}


class PromptOptions(BaseModel):
    target: str = ""
    preferences: str = ""
    start: int = 10
    include_genres: list[str] = []
    exclude_genres: list[str] = []
    include_decades: list[str] = []   # labels, e.g. "90s"
    exclude_decades: list[str] = []
    include_types: list[str] = []     # marathons, tv_blocks, movies, franchise, specialty
    exclude_types: list[str] = []


def _what_to_build(opts: "PromptOptions") -> str:
    def line(prefix, items, labels=None):
        if not items:
            return None
        names = [labels.get(i, i) if labels else i for i in items]
        return f"- {prefix}: {', '.join(names)}"

    inc = [x for x in (
        line("Channel types", opts.include_types, TYPE_LABELS),
        line("Movie genres", opts.include_genres),
        line("Decades", opts.include_decades),
    ) if x]
    exc = [x for x in (
        line("Channel types", opts.exclude_types, TYPE_LABELS),
        line("Movie genres", opts.exclude_genres),
        line("Decades", opts.exclude_decades),
    ) if x]
    if not inc and not exc:
        return ""

    s = "\n## What To Build\n\n"
    if inc:
        s += "Definitely include channels for these when the library has enough content:\n"
        s += "\n".join(inc) + "\n\n"
    if exc:
        s += "Do NOT create any channels for these:\n"
        s += "\n".join(exc) + "\n\n"
    s += (
        "Beyond the must-include list above, you are encouraged to create additional "
        "themed channels you discover in the library — franchises, directors, sub-genres, "
        "holiday blocks, and other clusters. Surprising, well-curated channels are welcome, "
        "as long as they don't fall under the 'do not create' list.\n"
    )
    return s


@router.post("/pipeline/prompt")
def build_prompt(opts: PromptOptions = PromptOptions()):
    # New flow: meta stripped (UI carries that guidance) + toggle-driven What To Build.
    content = _strip_meta(_read_prompt_source())
    wtb = _what_to_build(opts)
    if wtb:
        content = content.replace(ANCHOR, wtb + "\n" + ANCHOR)
    content = _apply_target_prefs_start(content, opts.target, opts.preferences, opts.start)
    return {"content": content}


@router.post("/pipeline/validate")
async def validate(file: Optional[UploadFile] = File(None), content: Optional[str] = Form(None)):
    if file:
        raw = (await file.read()).decode("utf-8", errors="replace")
    elif content:
        raw = content
    else:
        raise HTTPException(400, "Provide file or content")

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            data = {"channels": data, "orphaned": [], "suggested_channels": []}
        elif not (isinstance(data, dict) and "channels" in data):
            raise ValueError("not a channel dict")
    except Exception:
        channels = []
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    obj = json.loads(line)
                    if "number" in obj:
                        channels.append(obj)
                except Exception:
                    pass
        if not channels:
            return {"ok": False, "error": "No valid channel objects found"}
        data = {"channels": channels, "orphaned": [], "suggested_channels": []}

    with open(DATA_DIR / "channels.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return {"ok": True, "count": len(data.get("channels", [])), "channels": data.get("channels", [])}


@router.post("/pipeline/no-ai")
async def run_no_ai(start: int = Query(10)):
    args = []
    if start != 10:
        args += ["--start", str(start)]
    return _sse(_stream("generate_no_ai.py", args, "no_ai"))


@router.post("/pipeline/collections")
async def run_collections(
    base: str = Query("80"),
    min_items: str = Query("3"),
    condense: bool = Query(False),
):
    args = ["--apply", "--base", base, "--min-items", min_items]
    if condense:
        args.append("--condense")
    return _sse(_stream("generate_from_collections.py", args, "collections"))


@router.post("/pipeline/probe")
async def run_probe(from_channel: Optional[str] = Query(None)):
    args = ["--probe"]
    if from_channel:
        args += ["--from", from_channel]
    return _sse(_locked_stream("create.py", args, "probe"))


@router.post("/pipeline/deploy")
async def run_deploy(from_channel: Optional[str] = Query(None), protected: str = Query(""), no_delete: bool = Query(False)):
    args = []
    if no_delete:
        args.append("--no-delete")
    if from_channel:
        args += ["--from", from_channel]
    if protected:
        args += ["--protect", protected]
    return _sse(_locked_stream("create.py", args, "deploy"))


class DeployRequest(BaseModel):
    selections: list[DeploySelection]
    protected_numbers: list[int] = []
    no_delete: bool = False


@router.post("/pipeline/deploy-selective")
async def run_deploy_selective(req: DeployRequest):
    channels_path = DATA_DIR / "channels.json"
    if not channels_path.exists():
        raise HTTPException(404, "channels.json not found")

    with open(channels_path, encoding="utf-8") as f:
        data = json.load(f)

    sel_map = {s.original_number: s for s in req.selections if s.include}
    new_channels = [
        {**ch, "number": sel_map[ch["number"]].deploy_number}
        for ch in data.get("channels", [])
        if ch.get("number") in sel_map
    ]
    data["channels"] = new_channels

    temp_path = DATA_DIR / "deploy_temp.json"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    args = ["--json", "deploy_temp.json"]
    if req.no_delete:
        args.append("--no-delete")
    if req.protected_numbers:
        args += ["--protect", ",".join(str(n) for n in req.protected_numbers)]
    return _sse(_locked_stream("create.py", args, "deploy"))


@router.post("/pipeline/images")
async def run_images():
    return _sse(_stream("fetch_images.py", ["--apply"], "images"))


@router.post("/pipeline/sync")
async def run_sync():
    return _sse(_stream("sync_plex.py", [], "sync"))


@router.get("/pipeline/collections")
def list_collections():
    cfg = _load_config()
    plex_url = cfg.get("plex_url", "").rstrip("/")
    plex_token = cfg.get("plex_token", "")
    if not plex_url or not plex_token:
        raise HTTPException(400, "Plex not configured")
    try:
        sections_data = _plex_get(plex_url, plex_token, "/library/sections")
        sections = sections_data["MediaContainer"].get("Directory", [])
    except Exception as e:
        raise HTTPException(502, f"Could not reach Plex: {e}")

    results = []
    seen: set[str] = set()
    for section in sections:
        try:
            col_data = _plex_get(plex_url, plex_token, f"/library/sections/{section['key']}/collections")
            for c in col_data.get("MediaContainer", {}).get("Metadata", []):
                name = c.get("title", "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                results.append({
                    "id": c.get("ratingKey", ""),
                    "name": name,
                    "count": int(c.get("childCount", 0)),
                    "section": section.get("title", ""),
                    "summary": c.get("summary", ""),
                    "has_poster": bool(c.get("thumb", "")),
                })
        except Exception:
            continue
    return results


@router.get("/pipeline/collections/{collection_id}/poster")
def collection_poster(collection_id: str):
    cfg = _load_config()
    plex_url = cfg.get("plex_url", "").rstrip("/")
    plex_token = cfg.get("plex_token", "")
    if not plex_url or not plex_token:
        raise HTTPException(400, "Plex not configured")
    url = f"{plex_url}/library/metadata/{collection_id}/thumb?X-Plex-Token={plex_token}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as r:
            content = r.read()
            content_type = r.headers.get("Content-Type", "image/jpeg")
        return Response(content=content, media_type=content_type)
    except Exception as e:
        raise HTTPException(502, f"Could not fetch poster: {e}")


@router.post("/pipeline/collections/apply")
def apply_collections(selections: list[CollectionSelection]):
    channels_path = DATA_DIR / "channels.json"
    if channels_path.exists():
        with open(channels_path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"channels": [], "orphaned": [], "suggested_channels": []}

    included = [s for s in selections if s.include]
    if not included:
        return {"ok": True, "added": 0}

    min_ch = min(s.channel_number for s in included)
    kept = [ch for ch in data.get("channels", []) if ch.get("number", 0) < min_ch]
    new_channels = [
        {
            "number": s.channel_number,
            "name": s.name,
            "shuffle": "shuffle",
            "content": [{"collection": s.name}],
        }
        for s in sorted(included, key=lambda x: x.channel_number)
    ]
    data["channels"] = kept + new_channels
    with open(channels_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return {"ok": True, "added": len(new_channels)}
