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

    # Expand any {"collection": "Name"} entries to their member titles
    expanded_titles = []
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
        else:
            expanded_titles.append(entry)

    resolved = []
    for title in expanded_titles:
        item = resolve_title(title, movie_map, show_map)
        if item:
            resolved.append(item)
        else:
            missing.append(title)

    return resolved, missing


# ── Schedule builder ───────────────────────────────────────────────────────────

def build_schedule(shuffle_type, resolved_items):
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
            "padMs": 0,
            "padStyle": "episode",
            "randomDistribution": "uniform",
            "slots": slots,
        },
    }


def set_programming(tunarr_url, channel_id, schedule_payload):
    return api(tunarr_url, "POST", f"/api/channels/{channel_id}/programming", body=schedule_payload, timeout=120)
