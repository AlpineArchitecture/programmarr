import asyncio
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import channel_engine  # noqa: E402
import scheduler  # noqa: E402  (backend/ on sys.path) — shared deploy_lock

# scheduler's import added SCRIPTS_DIR to sys.path, so the pure pipeline modules
# at the repo root (e.g. channel_blocks) are importable in-process here.
if str(Path(os.environ.get("PROGRAMMARR_SCRIPTS", Path(__file__).parent.parent.parent))) not in sys.path:
    sys.path.insert(0, str(Path(os.environ.get("PROGRAMMARR_SCRIPTS", Path(__file__).parent.parent.parent))))
import channel_blocks  # noqa: E402

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
    # Force the child's stdout/stderr to UTF-8. On a Windows host the default is the
    # locale codec (cp1252), so a script printing a non-cp1252 title (e.g. a "⧸" in an
    # unsynced-title list) dies with UnicodeEncodeError. _stream decodes as UTF-8, so
    # this makes the pipe round-trip cleanly. No-op on Linux/Docker (already UTF-8).
    env["PYTHONIOENCODING"] = "utf-8"
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


# Planner v2 surface thresholds (min titles for a candidate to be offered).
COMBO_MIN = 6      # genre × decade
BLEND_MIN = 6      # genre ∩ genre
STUDIO_MIN = 4
DIRECTOR_MIN = 3
ACTOR_MIN = 4
TV_GENRE_MIN = 3
TV_MOVIE_MIX_MIN = 3  # minimum on each side for a cross-library mixed-genre candidate
ENTITY_CAP = 60    # cap each entity list; UI searches for the long tail


def _safe_int(val):
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _multi(val):
    return [x.strip() for x in (val or "").split("|") if x.strip()]


def _decade_start(year):
    for _, start, end in DECADE_BUCKETS:
        if year is not None and start <= year <= end:
            return start
    return None


@router.get("/pipeline/facets")
def library_facets(min_items: int = 5):
    """Library facets that drive the Planner v2 candidate list.

    One pass over plex_library.csv yields: genre counts (canonical always returned,
    'more' above min_items), decades present, genre×decade matrix and genre∩genre
    blend counts (movies, above COMBO_MIN/BLEND_MIN), stand-alone entity lists
    (studio/director/actor above their thresholds, capped), TV genre counts for
    blocks, and the marathon-eligible show count.
    """
    import csv as _csv
    from itertools import combinations
    p = DATA_DIR / "plex_library.csv"
    if not p.exists():
        return {"exists": False}

    DECADE_LABEL = {start: label for label, start, _ in DECADE_BUCKETS}
    genre_counts: dict[str, int] = {}
    decade_counts = {start: 0 for _, start, _ in DECADE_BUCKETS}
    studio_counts: dict[str, int] = {}
    director_counts: dict[str, int] = {}
    actor_counts: dict[str, int] = {}
    tv_genre_counts: dict[str, int] = {}
    movie_recs: list[tuple[list[str], int | None]] = []  # (genres, decade_start) for matrix/blends
    show_recs: list[dict] = []  # per-show marathon candidates
    movies = tv = marathon = 0

    with open(p, encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            t = row.get("Type", "")
            if t == "Movie":
                movies += 1
                genres = _multi(row.get("Genres"))
                for g in genres:
                    genre_counts[g] = genre_counts.get(g, 0) + 1
                ds = _decade_start(_safe_int(row.get("Year")))
                if ds is not None:
                    decade_counts[ds] += 1
                for s in _multi(row.get("Studio")):
                    studio_counts[s] = studio_counts.get(s, 0) + 1
                for d in _multi(row.get("Director")):
                    director_counts[d] = director_counts.get(d, 0) + 1
                for a in _multi(row.get("Actors")):
                    actor_counts[a] = actor_counts.get(a, 0) + 1
                movie_recs.append((genres, ds))
            elif t == "TV":
                tv += 1
                for g in _multi(row.get("Genres")):
                    tv_genre_counts[g] = tv_genre_counts.get(g, 0) + 1
                eps = _safe_int(row.get("Episodes")) or 0
                if eps >= 50:
                    marathon += 1
                title = row.get("Title", "")
                if title and eps >= 2:
                    show_recs.append({"title": title, "episodes": eps, "seasons": _safe_int(row.get("Seasons")) or 0})

    # Genre chips the UI offers: canonical (always) + 'more' above min_items.
    canonical_tags = {tag.lower() for _, tag in CANONICAL_GENRES}
    ci_counts = {tag.lower(): n for tag, n in genre_counts.items()}
    canonical = [
        {"display": disp, "tag": tag, "count": ci_counts.get(tag.lower(), 0)}
        for disp, tag in CANONICAL_GENRES
    ]
    more = sorted(
        ({"display": tag, "tag": tag, "count": n}
         for tag, n in genre_counts.items()
         if tag.lower() not in canonical_tags and n >= min_items),
        key=lambda x: (-x["count"], x["tag"].lower()),
    )
    shown = canonical + more
    display_of = {g["tag"]: g["display"] for g in shown}
    shown_tags = set(display_of)

    # Genre × decade matrix and genre ∩ genre blends, restricted to shown genres.
    gd_counts: dict[tuple[str, int], int] = {}
    pair_counts: dict[tuple[str, str], int] = {}
    for genres, ds in movie_recs:
        present = sorted({g for g in genres if g in shown_tags})
        if ds is not None:
            for g in present:
                gd_counts[(g, ds)] = gd_counts.get((g, ds), 0) + 1
        for a, b in combinations(present, 2):
            pair_counts[(a, b)] = pair_counts.get((a, b), 0) + 1

    genre_decade = sorted(
        ({"genre": g, "display": display_of[g], "decade_start": ds,
          "decade_label": DECADE_LABEL[ds], "count": n}
         for (g, ds), n in gd_counts.items() if n >= COMBO_MIN),
        key=lambda x: (x["decade_start"], -x["count"]),
    )
    blends = sorted(
        ({"genres": [a, b], "displays": [display_of[a], display_of[b]], "count": n}
         for (a, b), n in pair_counts.items() if n >= BLEND_MIN),
        key=lambda x: -x["count"],
    )

    def entity_list(counts, floor):
        return sorted(
            ({"value": v, "count": n} for v, n in counts.items() if v and n >= floor),
            key=lambda x: (-x["count"], x["value"].lower()),
        )[:ENTITY_CAP]

    decades = [
        {"label": label, "start": start, "end": end, "count": decade_counts[start]}
        for label, start, end in DECADE_BUCKETS if decade_counts[start] > 0
    ]
    tv_genres = sorted(
        ({"genre": g, "count": n} for g, n in tv_genre_counts.items() if n >= TV_GENRE_MIN),
        key=lambda x: (-x["count"], x["genre"].lower()),
    )
    marathons = sorted(show_recs, key=lambda s: -s["episodes"])

    # Cross-library genres: genres present in BOTH movies and TV above their respective floors.
    # Shape: [{"genre": "Comedy", "tv_count": N, "movie_count": M}] sorted by tv_count+movie_count desc.
    tv_movie_genres = sorted(
        (
            {"genre": g, "tv_count": tv_genre_counts[g], "movie_count": genre_counts.get(g, 0)}
            for g in tv_genre_counts
            if tv_genre_counts[g] >= TV_MOVIE_MIX_MIN and genre_counts.get(g, 0) >= TV_MOVIE_MIX_MIN
        ),
        key=lambda x: -(x["tv_count"] + x["movie_count"]),
    )

    return {
        "exists": True,
        "movies": movies,
        "tv_shows": tv,
        "marathon_count": marathon,
        "min_items": min_items,
        "genres": {"canonical": canonical, "more": more},
        "decades": decades,
        "genre_decade": genre_decade,
        "blends": blends,
        "studios": entity_list(studio_counts, STUDIO_MIN),
        "directors": entity_list(director_counts, DIRECTOR_MIN),
        "actors": entity_list(actor_counts, ACTOR_MIN),
        "tv_genres": tv_genres,
        "marathons": marathons,
        "tv_movie_genres": tv_movie_genres,
    }


ANCHOR = "## Channel Numbering Scheme"
TYPE_LABELS = {
    "marathons": "TV Marathons", "tv_blocks": "TV Blocks", "movies": "Movie channels",
    "franchise": "Franchise series", "specialty": "Specialty channels",
}

# Per-category prose for the LLM prompt's numbering guidance section.
_BLOCK_DESC = {
    "marathon":          "TV Marathons — 24/7 single-show loops (needs 50+ episodes to qualify)",
    "tv_block":          "TV Blocks — themed multi-show rotations (era blocks, genre blocks, etc.)",
    "tv_movie_mix":      "TV & Movie Mix — mixed-genre channels spanning both shows and films",
    "movie":             "Movie Channels — genre and decade-based pools",
    "entity":            "Studios / Directors / Actors — curated by creator or studio",
    "network":           "Networks — all shows from a single network (HBO, NBC, etc.)",
    "programming_block": "Classic TV Blocks — historical programming lineups (TGIF, Must See TV, etc.)",
    "franchise":         "Franchise & Curated Series — ordered collections (film series in release order, etc.)",
    "specialty":         "Specialty — single-movie loops, holiday, niche themes",
}
# Matches the bullet list under the scheme heading, regardless of the ranges in it.
_SCHEME_BULLETS_RE = re.compile(
    r"(Assign channel numbers following this cable TV block structure:\n)(?:-[^\n]*\n)+"
)


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


def _regen_numbering_scheme(content: str, start: int) -> str:
    """Rewrite PROMPT.md's numbering bullets + example numbers from the live layout.

    Channel numbers are assigned sequentially tight-packed in category order (no
    fixed sizes).  We produce a representative example using one channel per
    non-empty category so the LLM sees realistic numbers.  PROMPT.md's static text
    is only the default (used verbatim by the CLI).
    """
    cfg_order = channel_blocks.resolve_order(_load_config().get("channel_order"))
    # One representative channel per category to show the packing.
    example_counts = {k: 1 for k in cfg_order}
    numbers = channel_blocks.assign_numbers(cfg_order, example_counts, start)
    bullets = "\n".join(
        f"- **{numbers[k][0]}+**: {_BLOCK_DESC.get(k, channel_blocks.BLOCK_LABELS.get(k, k))}"
        for k in cfg_order if k in numbers
    )
    content = _SCHEME_BULLETS_RE.sub(lambda m: m.group(1) + bullets + "\n", content)
    # Update JSONL example numbers using the first three occupied positions.
    occupied = [numbers[k][0] for k in cfg_order if k in numbers]
    if len(occupied) >= 1:
        content = content.replace('"number": 10,', f'"number": {occupied[0]},')
    if len(occupied) >= 2:
        content = content.replace('"number": 20,', f'"number": {occupied[1]},')
    if len(occupied) >= 3:
        content = content.replace('"number": 30,', f'"number": {occupied[2]},')
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
    return _regen_numbering_scheme(content, start)


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
async def validate(
    file: Optional[UploadFile] = File(None),
    content: Optional[str] = Form(None),
    append: bool = Form(False),
):
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

    new_channels = data.get("channels", [])
    if append:
        # Merge AI-discovered channels on top of the in-progress draft lineup,
        # renumbering any collisions to the next free slot so nothing is overwritten.
        existing = {"channels": [], "orphaned": [], "suggested_channels": []}
        cpath = DATA_DIR / "channels.draft.json"
        if cpath.exists():
            with open(cpath, encoding="utf-8") as f:
                existing = json.load(f)
        kept = existing.get("channels", [])
        used = {c.get("number") for c in kept}
        seen_names = {(c.get("name") or "").strip().lower() for c in kept}
        next_free = (max(used) + 1) if used else 1
        added = 0
        skipped_dupes = 0
        for ch in new_channels:
            # Skip anything we already have by name (case-insensitive) — re-running the
            # AI step shouldn't stack a second "Time Travel" channel.
            nm = (ch.get("name") or "").strip().lower()
            if nm and nm in seen_names:
                skipped_dupes += 1
                continue
            n = ch.get("number")
            if n in used or n is None:
                while next_free in used:
                    next_free += 1
                ch["number"] = next_free
            used.add(ch["number"])
            seen_names.add(nm)
            next_free = max(next_free, ch["number"] + 1)
            kept.append(ch)
            added += 1
        existing["channels"] = sorted(kept, key=lambda c: c.get("number", 0))
        data = existing
        with open(cpath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return {"ok": True, "count": len(data["channels"]), "added": added,
                "skipped_dupes": skipped_dupes, "channels": data["channels"]}

    with open(DATA_DIR / "channels.draft.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return {"ok": True, "count": len(new_channels), "channels": new_channels}


class DiscoverOptions(BaseModel):
    discover: bool = True
    curate_pools: list[str] = []  # human descriptions of broad pools to split by tone


@router.post("/pipeline/discover-prompt")
def discover_prompt(opts: DiscoverOptions = DiscoverOptions()):
    """Build the AI-extras prompt, seeded with the existing (deterministic) lineup.

    Two jobs the AI can be asked to do, depending on `opts`:
      - curate_pools: replace a broad pool (e.g. "Comedy") with several tonally-coherent
        channels, or trim to a best-of — what genre tags can't express.
      - discover: suggest ADDITIONAL themed channels that don't duplicate the lineup.
    New channels are numbered from the next free channel up; the merge step renumbers
    any collisions anyway.
    """
    existing: list[dict] = []
    cpath = DATA_DIR / "channels.draft.json"
    if cpath.exists():
        try:
            with open(cpath, encoding="utf-8") as f:
                existing = json.load(f).get("channels", [])
        except Exception:
            existing = []
    maxnum = max((c.get("number", 0) for c in existing), default=9)
    start = maxnum + 1
    listing = "\n".join(
        f'- #{c.get("number")} {c.get("name")}'
        for c in sorted(existing, key=lambda c: c.get("number", 0))
    ) or "(none yet)"

    parts = [
        "You are a TV channel programmer. The user has a self-hosted media library "
        "(attached as plex_library.csv) and has ALREADY built these channels:\n\n"
        f"{listing}",
        "Use ONLY exact titles from the attached plex_library.csv. Do not invent titles "
        "or duplicate the channels above. Each channel you output needs at least 4 fitting titles.",
    ]

    if opts.curate_pools:
        pool_lines = "\n".join(f"- {p}" for p in opts.curate_pools)
        parts.append(
            "## Curate these pools by tone\n\n"
            "Each pool below is too broad to feel hand-programmed — a single 'Comedy' channel "
            "lurches from gross-out to rom-com. For EACH pool, replace it with 2–4 tighter "
            "channels grouped by tone/mood/vibe so titles flow without jarring transitions "
            "(e.g. split Comedy into 'Feel-Good Comedies', 'Raunchy Comedies', 'Dark Comedies'; "
            "or trim to a tight best-of). Only use titles that match that pool's described filter.\n\n"
            f"{pool_lines}"
        )

    if opts.discover:
        parts.append(
            "## Discover additional channels\n\n"
            "Suggest ADDITIONAL themed channels that plain genre/decade filters miss — e.g. "
            "Heist Films, Courtroom Dramas, Road Trip Movies, Time Travel, Mind-Benders, "
            "Feel-Good Rainy Day, Whodunits, Coming-of-Age, Holiday/Christmas, Sports Underdogs."
        )

    parts.append(
        f"Number every new channel sequentially starting at {start}. Output one channel per "
        "line as a JSON object (JSONL) — no commentary, no markdown fences, just one {...} per line:\n"
        f'{{"number": {start}, "name": "Feel-Good Comedies", "shuffle": "shuffle", "content": ["Groundhog Day", "Elf", "School of Rock"]}}'
    )

    return {"content": "\n\n".join(parts) + "\n", "start": start, "existing_count": len(existing)}


# ── Planner v2: deterministic candidate composition ──────────────────────────────

class CandidateSpec(BaseModel):
    kind: str  # genre | genre_decade | blend | studio | director | actor | tv_genre | marathon
    name: Optional[str] = None
    genre: Optional[str] = None
    genres: Optional[list[str]] = None
    decade_start: Optional[int] = None
    value: Optional[str] = None        # studio/director/actor name, or marathon show title
    shuffle: Optional[str] = None      # override; else category default


class ComposeRequest(BaseModel):
    specs: list[CandidateSpec]
    start: int = 1
    # Applied to every channel built in this batch (surfaced as Planner toggles):
    live: bool = False                      # mark channels auto-updating
    commercials: dict | None = None         # {filler_list_id, filler_list_name?, pad_minutes?}


# Which compose category (bucket) each candidate kind maps to, and its shuffle default.
# Buckets align with channel_blocks.CANONICAL_ORDER keys.
_CATEGORY = {
    "marathon":     ("marathon",     "ordered"),
    "tv_genre":     ("tv_block",     "block"),
    "genre":        ("movie",        "shuffle"),
    "genre_decade": ("movie",        "shuffle"),
    "blend":        ("movie",        "shuffle"),
    "studio":       ("entity",       "shuffle"),
    "director":     ("entity",       "shuffle"),
    "actor":        ("entity",       "shuffle"),
    "tv_movie_mix": ("tv_movie_mix", "shuffle"),
}
# Compose categories in the order they appear in CANONICAL_ORDER (subset).
_CATEGORY_ORDER = ["marathon", "tv_block", "tv_movie_mix", "movie", "entity"]
_DECADE_LABEL = {start: label for label, start, _ in DECADE_BUCKETS}


def _load_library():
    import csv as _csv
    p = DATA_DIR / "plex_library.csv"
    if not p.exists():
        return [], []
    movies, shows = [], []
    with open(p, encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            (movies if row.get("Type") == "Movie" else shows if row.get("Type") == "TV" else []).append(row)
    return movies, shows


def _resolve_spec(spec: CandidateSpec, movies: list[dict], shows: list[dict]) -> list[str]:
    """Return the sorted, de-duplicated title list a candidate spec selects."""
    def has_genre(row, g):
        gl = g.lower()
        return any(x.lower() == gl for x in _multi(row.get("Genres")))

    titles: list[str] = []
    if spec.kind == "genre" and spec.genre:
        titles = [m["Title"] for m in movies if has_genre(m, spec.genre)]
    elif spec.kind == "genre_decade" and spec.genre and spec.decade_start is not None:
        titles = [m["Title"] for m in movies
                  if has_genre(m, spec.genre) and _decade_start(_safe_int(m.get("Year"))) == spec.decade_start]
    elif spec.kind == "blend" and spec.genres:
        titles = [m["Title"] for m in movies if all(has_genre(m, g) for g in spec.genres)]
    elif spec.kind == "studio" and spec.value:
        v = spec.value.lower()
        titles = [m["Title"] for m in movies if any(s.lower() == v for s in _multi(m.get("Studio")))]
    elif spec.kind == "director" and spec.value:
        v = spec.value.lower()
        titles = [m["Title"] for m in movies if any(d.lower() == v for d in _multi(m.get("Director")))]
    elif spec.kind == "actor" and spec.value:
        v = spec.value.lower()
        titles = [m["Title"] for m in movies if any(a.lower() == v for a in _multi(m.get("Actors")))]
    elif spec.kind == "tv_genre" and spec.genre:
        titles = [s["Title"] for s in shows if has_genre(s, spec.genre)]
    elif spec.kind == "marathon" and spec.value:
        titles = [s["Title"] for s in shows if s["Title"] == spec.value]
    elif spec.kind == "tv_movie_mix" and spec.genre:
        # Mixed channel: both TV shows AND movies that share this genre, shuffled together.
        movie_titles = [m["Title"] for m in movies if has_genre(m, spec.genre)]
        show_titles = [s["Title"] for s in shows if has_genre(s, spec.genre)]
        titles = movie_titles + show_titles
    return sorted({t for t in titles if t})


def _auto_name(spec: CandidateSpec) -> str:
    if spec.kind == "genre":
        return f"{spec.genre} Movies"
    if spec.kind == "genre_decade":
        return f"{_DECADE_LABEL.get(spec.decade_start, '')} {spec.genre}".strip()
    if spec.kind == "blend":
        return " & ".join(spec.genres or [])
    if spec.kind == "studio":
        return spec.value or "Studio"
    if spec.kind == "director":
        return f"Directed by {spec.value}"
    if spec.kind == "actor":
        return f"{spec.value} Movies"
    if spec.kind == "tv_genre":
        return f"{spec.genre} TV"
    if spec.kind == "marathon":
        return f"{spec.value} 24/7"
    if spec.kind == "tv_movie_mix":
        return spec.genre or "Mixed"
    return spec.name or "Channel"


@router.post("/pipeline/compose")
def compose_channels(req: ComposeRequest):
    """Deterministically build channels.json from picked Planner candidate specs.

    Each spec is resolved against plex_library.csv into a title list; empties are
    skipped and reported.  Numbers are assigned sequentially tight-packed in the
    configured category order (channel_order config key), starting from req.start.
    Empty categories consume no numbers; input order within a category is preserved.
    """
    movies, shows = _load_library()
    if not movies and not shows:
        raise HTTPException(404, "Run Export first — plex_library.csv not found")

    # Resolve + bucket by category, preserving input order within each.
    buckets: dict[str, list[dict]] = {c: [] for c in _CATEGORY_ORDER}
    skipped: list[dict] = []
    for spec in req.specs:
        meta = _CATEGORY.get(spec.kind)
        if not meta:
            skipped.append({"name": spec.name or spec.kind, "reason": f"unknown kind '{spec.kind}'"})
            continue
        category, default_shuffle = meta
        content = _resolve_spec(spec, movies, shows)
        name = spec.name or _auto_name(spec)
        if not content:
            skipped.append({"name": name, "reason": "no matching titles"})
            continue
        shuffle = spec.shuffle if spec.shuffle in ("ordered", "shuffle", "block") else default_shuffle
        buckets[category].append({"name": name, "shuffle": shuffle, "content": content})

    # Batch-wide extras from the Planner toggles, applied to every built channel.
    extras: dict = {}
    if req.live:
        extras["live"] = True
    if req.commercials and req.commercials.get("filler_list_id"):
        extras["commercials"] = req.commercials

    # Sequential tight-packed numbering: categories in configured order, no fixed sizes,
    # empty categories skip entirely.  req.start is the first number (1 for a fresh deploy).
    cfg_order = channel_blocks.resolve_order(_load_config().get("channel_order"))
    counts = {cat: len(buckets.get(cat, [])) for cat in cfg_order}
    numbers = channel_blocks.assign_numbers(cfg_order, counts, req.start)

    channels: list[dict] = []
    for cat in cfg_order:
        items = buckets.get(cat, [])
        cat_numbers = numbers.get(cat, [])
        for num, ch in zip(cat_numbers, items):
            channels.append({"number": num, **ch, **extras})

    data = {"channels": channels, "orphaned": [], "suggested_channels": []}
    with open(DATA_DIR / "channels.draft.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return {
        "ok": True,
        "count": len(channels),
        "channels": [{"number": c["number"], "name": c["name"], "items": len(c["content"])} for c in channels],
        "skipped": skipped,
    }


@router.post("/pipeline/no-ai")
async def run_no_ai(
    start: int = Query(1),
    genres: Optional[str] = Query(None),
    decades: Optional[str] = Query(None),
    types: Optional[str] = Query(None),
    min_items: Optional[int] = Query(None),
):
    args = []
    if start != 1:
        args += ["--start", str(start)]
    if genres is not None:
        args += ["--genres", genres]
    if decades is not None:
        args += ["--decades", decades]
    if types is not None:
        args += ["--types", types]
    if min_items is not None:
        args += ["--min-items", str(min_items)]
    # Pass the configured category order so the CLI generator matches the Planner.
    order = channel_blocks.resolve_order(_load_config().get("channel_order"))
    args += ["--order", ",".join(order)]
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
async def run_probe(from_channel: Optional[str] = Query(None), protected: str = Query("")):
    # Review the in-progress Planner lineup (compose + AI extras + collections all write
    # channels.draft.json), NOT the already-deployed channels.json. The draft is what
    # deploy-selective pushes, so the probe must read the same file. Fall back to
    # create.py's default (channels.json) when there's no draft.
    args = ["--probe"]
    if (DATA_DIR / "channels.draft.json").exists():
        args += ["--json", "channels.draft.json"]
    if from_channel:
        args += ["--from", from_channel]
    if protected:
        # Keep the "would delete" preview honest in keep-mode (protected channels survive).
        args += ["--protect", protected]
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


def _reconcile_channels_json(protected_numbers: list[int]) -> None:
    """Write channels.json to mirror what create.py ACTUALLY pushed, then clear staging files.

    The deployed set is deploy_temp.json — the selected, number-remapped subset that
    deploy-selective built and create.py read.  Do NOT read channels.draft.json here:
    the draft may still contain channels the user DESELECTED and pre-remap numbers.
      wipe (no protected) -> channels.json = deployed set.
      keep (protected)    -> channels.json = existing protected entries merged with deployed set.
    Called ONLY after a successful create.py run.
    """
    deployed_path = DATA_DIR / "deploy_temp.json"
    canon_path = DATA_DIR / "channels.json"
    draft_path = DATA_DIR / "channels.draft.json"

    with open(deployed_path, encoding="utf-8") as f:
        deployed = json.load(f)
    deployed_channels = deployed.get("channels", [])

    if protected_numbers:
        protected = set(protected_numbers)
        try:
            with open(canon_path, encoding="utf-8") as f:
                existing = json.load(f).get("channels", [])
        except FileNotFoundError:
            existing = []
        by_num = {c["number"]: c for c in existing if c.get("number") in protected}
        for c in deployed_channels:
            by_num[c["number"]] = c  # just-deployed wins on collision
        out = {**deployed, "channels": sorted(by_num.values(), key=lambda c: c["number"])}
    else:
        out = deployed

    with open(canon_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    # Persist managed_names so surgical-deploy knows which channels the planner owns.
    deployed_names = [(c.get("name") or "").strip() for c in deployed_channels if c.get("name")]
    planner_state_path = DATA_DIR / "planner_state.json"
    existing_ps: dict = {}
    if planner_state_path.exists():
        try:
            with open(planner_state_path, encoding="utf-8") as f:
                existing_ps = json.load(f)
        except Exception:
            existing_ps = {}
    updated_ps = {**existing_ps, "managed_names": deployed_names}
    try:
        tmp = planner_state_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(updated_ps, f, indent=2, ensure_ascii=False)
        tmp.replace(planner_state_path)
    except Exception:
        pass  # Non-fatal — deploy already succeeded

    for p in (draft_path, deployed_path):
        if p.exists():
            p.unlink()


async def _deploy_and_reconcile(args: list[str], protected_numbers: list[int]):
    """Stream create.py; reconcile channels.json from the deployed set on success.

    Reconcile runs BEFORE forwarding the terminal 'done' event so any client
    acting on 'done' already sees a consistent channels.json.  A failed deploy
    never writes channels.json.
    """
    async for chunk in _locked_stream("create.py", args, "deploy"):
        if chunk.startswith("data: "):
            try:
                payload = json.loads(chunk[6:].strip())
            except Exception:
                payload = None
            if payload and payload.get("type") == "done" and payload.get("returncode") == 0:
                try:
                    _reconcile_channels_json(protected_numbers)
                except Exception as e:
                    yield f"data: {json.dumps({'type': 'line', 'text': f'WARNING: reconcile failed: {e}'})}\n\n"
        yield chunk


@router.post("/pipeline/deploy-selective")
async def run_deploy_selective(req: DeployRequest):
    draft_path = DATA_DIR / "channels.draft.json"
    if not draft_path.exists():
        raise HTTPException(404, "channels.draft.json not found — compose a lineup first")

    with open(draft_path, encoding="utf-8") as f:
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
    return _sse(_deploy_and_reconcile(args, req.protected_numbers))


@router.get("/pipeline/draft")
def get_draft():
    """The in-progress Planner lineup (channels.draft.json): compose + AI extras so far.

    Distinct from GET /channels, which is the DEPLOYED record. The Collections step needs
    this so it places collections ABOVE the freshly-built lineup (including AI extras), not
    above the stale deployed set — otherwise apply_collections clobbers the AI channels.
    """
    p = DATA_DIR / "channels.draft.json"
    if not p.exists():
        return {"channels": [], "orphaned": [], "suggested_channels": []}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"channels": [], "orphaned": [], "suggested_channels": []}


@router.get("/pipeline/planner-state")
def get_planner_state():
    """Return the persisted Planner intent (data/planner_state.json), or {} if absent.

    Saved after every successful Build; restored when the user opens Add/Edit mode.
    Cleared (file deleted) when the user chooses Nuke.
    """
    p = DATA_DIR / "planner_state.json"
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


@router.put("/pipeline/planner-state")
def save_planner_state(state: dict):
    """Persist the full Planner intent so Add/Edit mode can restore prior selections."""
    p = DATA_DIR / "planner_state.json"
    try:
        tmp = DATA_DIR / "planner_state.json.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        tmp.replace(p)
    except Exception as e:
        raise HTTPException(500, f"Could not save planner state: {e}")
    return {"ok": True}


@router.delete("/pipeline/planner-state")
def delete_planner_state():
    """Clear planner_state.json (called on Nuke, so the next Add/Edit starts blank)."""
    p = DATA_DIR / "planner_state.json"
    if p.exists():
        p.unlink()
    return {"ok": True}


class SurgicalDeployRequest(BaseModel):
    # No extra parameters needed: desired = draft, deployed = channels.json.
    # These flags mirror DeployRequest for the cascade.
    pass


@router.post("/pipeline/surgical-deploy")
async def run_surgical_deploy():
    """Surgical diff deploy for Add/Edit mode.

    Desired state  = channels.draft.json  (the planner's fresh output).
    Current state  = channels.json        (managed channels only — no orphans).

    Classifies each channel as create / delete / update-in-place / unchanged
    using channel_engine.classify_channels, then executes the minimum set of
    Tunarr operations:
      - create  → channels.json is written first, then create.py deploys just
                  those channels (via a temp file).
      - delete  → removed from Tunarr and from channels.json.
      - update  → update_channel_in_place (preserves Tunarr id + Plex DVR mapping).
      - unchanged → no Tunarr calls.

    Invariants (enforced by classify_channels + route):
      1. Live channels are NEVER in the delete bucket — they land in update-in-place.
      2. Orphan channels (in Tunarr but absent from channels.json) are outside both
         input sets and are never touched.

    Holds scheduler.deploy_lock for the full operation.
    """
    draft_path = DATA_DIR / "channels.draft.json"
    if not draft_path.exists():
        raise HTTPException(404, "channels.draft.json not found — compose a lineup first")

    canon_path = DATA_DIR / "channels.json"

    with open(draft_path, encoding="utf-8") as f:
        draft_data = json.load(f)
    desired: list[dict] = draft_data.get("channels", [])

    if canon_path.exists():
        with open(canon_path, encoding="utf-8") as f:
            canon_data = json.load(f)
        deployed: list[dict] = canon_data.get("channels", []) if isinstance(canon_data, dict) else canon_data
    else:
        deployed = []

    # Load prior_managed from planner_state.json for provenance-based delete safety.
    planner_state_path = DATA_DIR / "planner_state.json"
    planner_state: dict = {}
    if planner_state_path.exists():
        try:
            with open(planner_state_path, encoding="utf-8") as f:
                planner_state = json.load(f)
        except Exception:
            planner_state = {}
    prior_managed: set[str] = {
        n.strip().lower() for n in planner_state.get("managed_names", []) if n
    }

    diff = channel_engine.classify_channels(desired, deployed, prior_managed)

    cfg = _load_config()
    tunarr_url = cfg.get("tunarr_url", "").rstrip("/")
    plex_url = cfg.get("plex_url", "").rstrip("/")
    plex_token = cfg.get("plex_token", "")
    if not tunarr_url:
        raise HTTPException(400, "Tunarr not configured")

    async def _stream_surgical() -> AsyncGenerator[str, None]:
        def _emit(text: str) -> str:
            return f"data: {json.dumps({'type': 'line', 'text': text})}\n\n"

        yield f"data: {json.dumps({'type': 'start', 'cmd': 'surgical-deploy', 'log': 'surgical'})}\n\n"
        yield _emit(f"Surgical deploy: {len(diff['create'])} create, {len(diff['delete'])} delete, "
                    f"{len(diff['update'])} update, {len(diff['unchanged'])} unchanged, "
                    f"{len(diff['foreign'])} foreign (untouched)")

        errors: list[str] = []

        async with scheduler.deploy_lock:
            # ── 0. Build Tunarr library index once for all updates ────────────
            # Hoisted out of the per-channel closure so the index is fetched only once
            # regardless of how many channels need updating (Fix 3 — efficiency).
            if diff["update"]:
                library_index = await asyncio.to_thread(
                    channel_engine.build_library_index, tunarr_url
                )
                movie_map_shared, show_map_shared = library_index
            else:
                movie_map_shared, show_map_shared = {}, {}

            # ── 1. Updates in place ───────────────────────────────────────────
            for item in diff["update"]:
                desired_ch = item["desired"]
                num = desired_ch.get("number") or item["deployed"].get("number")
                name = desired_ch.get("name", "")
                yield _emit(f"  Updating #{num} {name} in place…")

                def _do_update(ch=desired_ch, n=num, mv=movie_map_shared, sh=show_map_shared):
                    plex_sections, collection_cache = [], {}
                    if any(isinstance(it, dict) and "collection" in it for it in ch.get("content", [])):
                        if plex_url and plex_token:
                            plex_sections = channel_engine.get_plex_sections(plex_url, plex_token)
                    resolved, missing = channel_engine.resolve_content(
                        ch.get("content", []), mv, sh,
                        plex_url=plex_url, plex_token=plex_token,
                        plex_sections=plex_sections, collection_cache=collection_cache,
                    )
                    if not resolved:
                        raise channel_engine.ChannelEngineError(
                            f"Channel #{n}: resolved to empty — refusing to update")
                    comm = ch.get("commercials") or {}
                    pad_ms = int(comm.get("pad_minutes", 5)) * 60000 if comm.get("filler_list_id") else 0
                    channel_engine.update_channel_in_place(
                        tunarr_url, n, ch.get("shuffle", "shuffle"), resolved, pad_ms=pad_ms)
                    return missing

                try:
                    missing = await asyncio.to_thread(_do_update)
                    if missing:
                        yield _emit(f"    WARNING: {len(missing)} titles not found in library: {', '.join(missing[:5])}")
                    yield _emit(f"  ✓ Updated #{num} {name}")
                except channel_engine.ChannelEngineError as e:
                    errors.append(f"#{num} {name}: {e}")
                    yield _emit(f"  ! Error updating #{num} {name}: {e}")

            # ── 2. Deletes ────────────────────────────────────────────────────
            for dep_ch in diff["delete"]:
                num = dep_ch.get("number")
                name = dep_ch.get("name", "")
                yield _emit(f"  Deleting #{num} {name}…")

                def _do_delete(n=num):
                    tunarr_ch = channel_engine.find_channel_by_number(tunarr_url, n)
                    if tunarr_ch:
                        channel_engine.api(tunarr_url, "DELETE", f"/api/channels/{tunarr_ch['id']}")
                    return tunarr_ch is not None

                try:
                    found = await asyncio.to_thread(_do_delete)
                    if not found:
                        yield _emit(f"    (#{num} not in Tunarr — skipped)")
                    yield _emit(f"  ✓ Deleted #{num} {name}")
                except Exception as e:
                    errors.append(f"delete #{num} {name}: {e}")
                    yield _emit(f"  ! Error deleting #{num} {name}: {e}")

            # ── 3. Creates — run via create.py on a temp file ─────────────────
            if diff["create"]:
                create_temp = DATA_DIR / "surgical_create_temp.json"
                create_data = {**draft_data, "channels": diff["create"]}
                with open(create_temp, "w", encoding="utf-8") as f:
                    json.dump(create_data, f, indent=2, ensure_ascii=False)
                yield _emit(f"  Creating {len(diff['create'])} new channel(s) via create.py…")

                collected: list[str] = []
                create_ok = False
                async for chunk in _stream("create.py", ["--json", "surgical_create_temp.json", "--no-delete"], "surgical_create"):
                    if chunk.startswith("data: "):
                        try:
                            payload = json.loads(chunk[6:].strip())
                            if payload.get("type") == "line":
                                collected.append(payload["text"])
                                yield chunk
                            elif payload.get("type") == "done":
                                create_ok = payload.get("returncode") == 0
                                yield chunk
                        except Exception:
                            yield chunk
                    else:
                        yield chunk

                if create_temp.exists():
                    create_temp.unlink()

                if not create_ok:
                    errors.append("create.py failed for new channels")

            # ── 4. Write channels.json — merge all buckets ────────────────────
            # The new channels.json contains:
            #   • all desired channels (create + update + unchanged — from the draft)
            #   • all foreign channels (hand-authored, absent from desired, NOT in
            #     prior_managed — must be preserved untouched)
            # Channels in diff["delete"] are intentionally excluded.
            new_managed = list(desired)  # create + update(desired-side) + unchanged

            # Append foreign channels — they were not in desired but must be kept.
            new_managed.extend(diff["foreign"])

            new_managed.sort(key=lambda c: c.get("number", 0))
            out_data = {
                "channels": new_managed,
                "orphaned": [],
                "suggested_channels": [],
            }
            with open(canon_path, "w", encoding="utf-8") as f:
                json.dump(out_data, f, indent=2, ensure_ascii=False)

            # Persist managed_names so future surgical deploys know which channels
            # were planner-built (provenance for delete safety).
            new_managed_names = [(ch.get("name") or "").strip() for ch in desired if ch.get("name")]
            updated_planner_state = {**planner_state, "managed_names": new_managed_names}
            try:
                tmp = planner_state_path.with_suffix(".json.tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(updated_planner_state, f, indent=2, ensure_ascii=False)
                tmp.replace(planner_state_path)
            except Exception as e:
                # Non-fatal — log but don't fail the deploy.
                yield _emit(f"  WARNING: could not update planner_state.json managed_names: {e}")

            # Clear the draft.
            if draft_path.exists():
                draft_path.unlink()

        if errors:
            yield _emit(f"Completed with {len(errors)} error(s): {'; '.join(errors)}")
            yield f"data: {json.dumps({'type': 'done', 'returncode': 1, 'log': 'surgical'})}\n\n"
        else:
            yield _emit(f"Done: {len(diff['create'])} created, {len(diff['delete'])} deleted, "
                        f"{len(diff['update'])} updated, {len(diff['unchanged'])} unchanged, "
                        f"{len(diff['foreign'])} foreign kept")
            yield f"data: {json.dumps({'type': 'done', 'returncode': 0, 'log': 'surgical'})}\n\n"

    return _sse(_stream_surgical())


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
    channels_path = DATA_DIR / "channels.draft.json"
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
