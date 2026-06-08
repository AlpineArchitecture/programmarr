#!/usr/bin/env python3
"""
channel_engine.py — Shared Tunarr channel resolution engine.

Pure, importable building blocks shared by create.py (CLI deploy), the live-channel
scheduler, and the recipe-preview endpoint. Every function is parameterized by
tunarr_url / plex_url / token — nothing here reads config.json or touches argv, so
it is safe to import into the FastAPI process. CLI-only concerns (config loading,
delete/create, argparse) stay in create.py.

No dependencies beyond the Python standard library.
"""

import json
import re
import uuid
import urllib.error
import urllib.request


class ChannelEngineError(Exception):
    """Raised for unrecoverable engine conditions (e.g. no Plex source in Tunarr).

    Engine code must never call sys.exit() — it can run inside the long-lived
    FastAPI process. Callers (create.py main()) translate this into an exit.
    """


SHUFFLE_MAP = {
    "ordered": "ordered",
    "shuffle": "shuffle",
    "block":   "block",
}


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def plex_get(base_url, token, path, timeout=60):
    sep = "&" if "?" in path else "?"
    url = base_url + path + sep + f"X-Plex-Token={token}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"  ! Plex HTTP {e.code} [{path[:60]}]")
        return None
    except Exception as e:
        print(f"  ! Plex error [{path[:60]}]: {e}")
        return None


def api(tunarr_url, method, path, body=None, timeout=60):
    url = tunarr_url + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        print(f"  ! HTTP {e.code} [{method} {path}]: {raw[:200]}")
        return None
    except Exception as e:
        print(f"  ! Error [{method} {path}]: {e}")
        return None


# ── Library indexing ───────────────────────────────────────────────────────────

def get_transcode_config(tunarr_url):
    configs = api(tunarr_url, "GET", "/api/transcode_configs") or []
    return configs[0]["id"] if configs else None


def get_plex_source(tunarr_url):
    sources = api(tunarr_url, "GET", "/api/media-sources") or []
    return next((s for s in sources if s.get("type") == "plex"), None)


def build_library_index(tunarr_url):
    source = get_plex_source(tunarr_url)
    if not source:
        raise ChannelEngineError("No Plex source found in Tunarr")

    libs = source.get("libraries", [])
    movie_lib = next((l for l in libs if l.get("mediaType") in ("movie", "movies") and l.get("enabled")), None)
    tv_lib = next((l for l in libs if l.get("mediaType") == "shows" and l.get("enabled")), None)

    movie_map = {}
    show_map = {}

    if movie_lib:
        print(f"  Indexing movie library...")
        programs = api(tunarr_url, "GET", f"/api/media-libraries/{movie_lib['id']}/programs", timeout=120) or []
        for p in programs:
            title = p.get("program", {}).get("title", "")
            if title:
                movie_map[title.lower().strip()] = p
        print(f"  Indexed {len(movie_map)} movies")

    if tv_lib:
        print(f"  Indexing TV library...")
        programs = api(tunarr_url, "GET", f"/api/media-libraries/{tv_lib['id']}/programs", timeout=120) or []
        by_show = {}
        for p in programs:
            show = p.get("program", {}).get("show", {})
            show_id = show.get("uuid") or p.get("program", {}).get("showId")
            title = show.get("title", "")
            if not show_id or not title:
                continue
            key = title.lower().strip()
            if key not in by_show:
                by_show[key] = {"title": title, "showId": show_id, "programs": []}
            by_show[key]["programs"].append(p)
        show_map = by_show
        print(f"  Indexed {len(show_map)} TV shows")

    return movie_map, show_map


# ── Title resolution ───────────────────────────────────────────────────────────

def resolve_title(title, movie_map, show_map):
    key = title.lower().strip()
    if key in movie_map:
        p = movie_map[key]
        return {"type": "Movie", "title": title, "programs": [p]}
    if key in show_map:
        s = show_map[key]
        return {"type": "TV", "title": s["title"], "showId": s["showId"], "programs": s["programs"]}
    return None


# ── Franchise matching (live recipes) ──────────────────────────────────────────

def _word_boundary_match(value, title):
    """True if `value` appears in `title` on word boundaries (case-insensitive).

    Word-boundary, not raw substring: "It" matches "It Follows" but NOT
    "Little Women". Multi-word values work too ("Bad Boys" matches "Bad Boys II").
    """
    if not value:
        return False
    return re.search(r"\b" + re.escape(value) + r"\b", title, re.IGNORECASE) is not None


def match_titles(value, movie_map, show_map, order=None, exclude=None):
    """Franchise matcher for {"match": "title_contains"} content refs.

    Scans the Tunarr library for titles containing `value` on word boundaries and
    returns (resolved_items, preview). `resolved_items` are ready for build_schedule;
    `preview` is a [{title, year}] list (same order) for the author-time confirm UI.

    order="release_date" sorts movies by releaseDate ascending (unknown dates last);
    any other value sorts alphabetically. `exclude` is a case-insensitive list of
    titles to drop (the per-recipe false-positive escape hatch).
    """
    exclude_set = {e.lower().strip() for e in (exclude or [])}
    matched = []  # (sort_release_ms, year, title, item)

    for key, p in movie_map.items():
        if key in exclude_set:
            continue
        prog = p.get("program", {})
        title = prog.get("title", "")
        if _word_boundary_match(value, title):
            release_ms = prog.get("releaseDate")
            matched.append((
                release_ms if release_ms is not None else float("inf"),
                prog.get("year"),
                title,
                {"type": "Movie", "title": title, "programs": [p]},
            ))

    for key, s in show_map.items():
        if key in exclude_set:
            continue
        title = s["title"]
        if _word_boundary_match(value, title):
            first_prog = s["programs"][0].get("program", {}) if s.get("programs") else {}
            matched.append((
                float("inf"),  # shows have no single release date — sort to the end
                first_prog.get("year"),
                title,
                {"type": "TV", "title": title, "showId": s["showId"], "programs": s["programs"]},
            ))

    if order == "release_date":
        matched.sort(key=lambda t: (t[0], t[2].lower()))
    else:
        matched.sort(key=lambda t: t[2].lower())

    resolved = [t[3] for t in matched]
    preview = [{"title": t[2], "year": t[1]} for t in matched]
    return resolved, preview


# ── Plex collection resolution ─────────────────────────────────────────────────

def get_plex_sections(plex_url, token):
    data = plex_get(plex_url, token, "/library/sections")
    if not data:
        return []
    return data["MediaContainer"].get("Directory", [])


def resolve_collection(plex_url, token, name, sections, cache):
    """Return a list of titles from a named Plex collection (cached)."""
    key = name.lower().strip()
    if key in cache:
        return cache[key]

    titles = []
    for section in sections:
        section_key = section.get("key")
        data = plex_get(plex_url, token, f"/library/sections/{section_key}/collections")
        if not data:
            continue
        collections = data["MediaContainer"].get("Metadata", [])
        match = next((c for c in collections if c.get("title", "").lower().strip() == key), None)
        if match:
            rating_key = match["ratingKey"]
            # Some Plex collection types (e.g. Kometa smart collections) return
            # size=0 from /library/metadata/{id}/children but work correctly via
            # /library/collections/{id}/children — try collections endpoint first.
            for children_path in (
                f"/library/collections/{rating_key}/children",
                f"/library/metadata/{rating_key}/children",
            ):
                items_data = plex_get(plex_url, token, children_path)
                if items_data:
                    items = items_data["MediaContainer"].get("Metadata", [])
                    titles = [item["title"] for item in items if item.get("title")]
                    if titles:
                        break
            break

    cache[key] = titles
    return titles


# ── Content resolution ─────────────────────────────────────────────────────────

def resolve_content(content_list, movie_map, show_map,
                    plex_url=None, plex_token=None, plex_sections=None, collection_cache=None):
    """Resolve a channel's content list into (resolved_items, missing).

    Each entry is either a plain title string or a {"collection": "Name"} ref.
    Collection refs are expanded to their member titles via Plex, then every
    title is matched against the Tunarr library index. Returns the list of
    resolved items (ready for build_schedule) plus the list of titles/refs that
    could not be found (for reporting).
    """
    plex_sections = plex_sections or []
    collection_cache = collection_cache if collection_cache is not None else {}

    # Expand {"collection": "Name"} → member titles; {"match": ...} → resolved items
    expanded_titles = []
    matched_items = []
    missing = []
    for entry in content_list:
        if isinstance(entry, dict) and "collection" in entry:
            col_name = entry["collection"]
            col_titles = resolve_collection(plex_url, plex_token, col_name, plex_sections, collection_cache)
            if col_titles:
                expanded_titles.extend(col_titles)
                print(f"    Collection '{col_name}': {len(col_titles)} titles")
            else:
                print(f"    WARNING: Collection '{col_name}' not found in Plex")
                missing.append(f"[collection:{col_name}]")
        elif isinstance(entry, dict) and "match" in entry:
            value = entry.get("value", "")
            if entry["match"] == "title_contains" and value:
                items, _ = match_titles(value, movie_map, show_map,
                                        order=entry.get("order"), exclude=entry.get("exclude"))
                if items:
                    matched_items.extend(items)
                    print(f"    Match '{value}': {len(items)} titles")
                else:
                    print(f"    WARNING: match '{value}' matched nothing in library")
                    missing.append(f"[match:{value}]")
            else:
                print(f"    WARNING: unsupported match ref: {entry}")
                missing.append(f"[match:{value or entry.get('match')}]")
        else:
            expanded_titles.append(entry)

    resolved = []
    for title in expanded_titles:
        item = resolve_title(title, movie_map, show_map)
        if item:
            resolved.append(item)
        else:
            missing.append(title)

    resolved.extend(matched_items)
    return resolved, missing


# ── Schedule builder ───────────────────────────────────────────────────────────

def build_schedule(shuffle_type, resolved_items, pad_ms=0):
    """Build a rolling random schedule.

    pad_ms > 0 rounds each program up to the next pad_ms boundary, opening a flex
    gap after it (flexPreference="end"). That gap is what the channel's attached
    filler list ("commercials") fills at playback — see the Commercials feature.
    pad_ms == 0 (default) keeps episodes back-to-back, unchanged from before.
    """
    all_programs = [p for item in resolved_items for p in item["programs"]]
    if not all_programs:
        return None

    is_ordered = shuffle_type == "ordered"
    is_block = shuffle_type == "block"

    slots = []
    seen_show_ids = set()
    has_movies = False

    for item in resolved_items:
        if item["type"] == "TV":
            show_id = item.get("showId")
            if show_id and show_id not in seen_show_ids:
                seen_show_ids.add(show_id)
                slots.append({
                    "type": "show",
                    "id": str(uuid.uuid4()),
                    "cooldownMs": 0,
                    "weight": 1,
                    "order": "next" if (is_ordered or is_block) else "shuffle",
                    "showId": show_id,
                })
        else:
            has_movies = True

    if has_movies:
        slots.append({
            "type": "movie",
            "id": str(uuid.uuid4()),
            "cooldownMs": 0,
            "weight": 1,
            "order": "chronological" if is_ordered else "shuffle",
        })

    return {
        "type": "random",
        "programs": [p["id"] for p in all_programs],
        "schedule": {
            "type": "random",
            "flexPreference": "end",
            "maxDays": 30,
            "padMs": pad_ms,
            "padStyle": "episode",
            "randomDistribution": "uniform",
            "slots": slots,
        },
    }


def set_programming(tunarr_url, channel_id, schedule_payload):
    return api(tunarr_url, "POST", f"/api/channels/{channel_id}/programming", body=schedule_payload, timeout=120)


# ── In-place channel updates (live recipes) ────────────────────────────────────

def find_channel_by_number(tunarr_url, number):
    """Return the live Tunarr channel dict (incl. id) for a channel number, or None."""
    for ch in api(tunarr_url, "GET", "/api/channels") or []:
        if ch.get("number") == number:
            return ch
    return None


def read_channel_programming(tunarr_url, channel_id):
    """Return the set of program IDs currently scheduled on a channel, or None on error.

    Uses GET /api/channels/{id}/programming. The `programs` field is a dict keyed by
    program ID (the same id-space as build_library_index's p["id"]), so its keys are
    the current content set. Falls back to distinct content lineup ids if absent.
    This set is the "current" side of the scheduler's change-detection diff.
    """
    pr = api(tunarr_url, "GET", f"/api/channels/{channel_id}/programming")
    if not pr:
        return None
    programs = pr.get("programs")
    if isinstance(programs, dict):
        return set(programs.keys())
    return {i["id"] for i in pr.get("lineup", []) if i.get("type") == "content" and i.get("id")}


def update_channel_in_place(tunarr_url, number, shuffle, resolved, pad_ms=0):
    """Patch an existing channel's programming in place — never delete/recreate.

    Looks the channel up by number (preserving its Tunarr id and Plex DVR mapping),
    rebuilds the schedule from `resolved`, and POSTs it. This is the primitive the
    live-channel scheduler calls after detecting a content change. Raises
    ChannelEngineError if the channel is missing or no schedule can be built.

    pad_ms preserves a commercials channel's gap on live updates (the attached filler
    list survives — only programming is replaced — but the pad must be re-applied or the
    gap, and thus the commercials, would vanish after a cycle).
    """
    ch = find_channel_by_number(tunarr_url, number)
    if not ch:
        raise ChannelEngineError(f"Channel #{number} not found in Tunarr")
    schedule = build_schedule(SHUFFLE_MAP.get(shuffle, "shuffle"), resolved, pad_ms=pad_ms)
    if not schedule:
        raise ChannelEngineError(f"Channel #{number}: no schedule could be built (no content resolved)")
    return set_programming(tunarr_url, ch["id"], schedule)
