#!/usr/bin/env python3
"""
create.py — Create Tunarr channels from channels.json.

Reads channels.json (output from LLM or generate_no_ai.py), deletes all
existing Tunarr channels, and creates fresh ones with rolling-loop schedules.

Usage:
    python create.py                        # reads channels.json
    python create.py --json myfile.json     # use alternate file
    python create.py --probe                # dry run, no changes
    python create.py --no-delete            # create without deleting existing
"""

import argparse
import json
import sys
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timezone

CONFIG_FILE = "config.json"
DEFAULT_CHANNELS_FILE = "channels.json"

SHUFFLE_MAP = {
    "ordered": "ordered",
    "shuffle": "shuffle",
    "block":   "block",
}


# ── Config ─────────────────────────────────────────────────────────────────────

def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {CONFIG_FILE} not found.")
        sys.exit(1)


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
        print("ERROR: No Plex source found in Tunarr")
        sys.exit(1)

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


# ── Channel operations ─────────────────────────────────────────────────────────

def delete_channels(tunarr_url, probe, from_ch=None):
    existing = api(tunarr_url, "GET", "/api/channels") or []
    if not existing:
        print("  No existing channels to delete")
        return
    targets = [ch for ch in existing if from_ch is None or ch.get("number", 0) >= from_ch]
    if not targets:
        print(f"  No channels >= {from_ch} to delete")
        return
    scope = f">= #{from_ch}" if from_ch is not None else "all"
    print(f"  Deleting {len(targets)} channels ({scope})...")
    for ch in targets:
        if probe:
            print(f"    [PROBE] Would delete #{ch['number']} {ch['name']}")
        else:
            result = api(tunarr_url, "DELETE", f"/api/channels/{ch['id']}")
            if result is not None:
                print(f"    Deleted #{ch['number']} {ch['name']}")
            time.sleep(0.1)


def create_channel(tunarr_url, number, name, transcode_id):
    channel_id = str(uuid.uuid4())
    body = {
        "type": "new",
        "channel": {
            "id": channel_id,
            "number": number,
            "name": name,
            "startTime": int(datetime.now(timezone.utc).timestamp() * 1000),
            "duration": 0,
            "groupTitle": "tunarr",
            "guideMinimumDuration": 30000,
            "fillerRepeatCooldown": 30000,
            "disableFillerOverlay": False,
            "transcodeConfigId": transcode_id,
            "streamMode": "hls",
            "stealth": False,
            "subtitlesEnabled": False,
            "icon": {"path": "", "width": 0, "duration": 0, "position": "bottom-right"},
            "offline": {"mode": "pic", "picture": "", "soundtrack": ""},
            "watermark": {
                "enabled": False,
                "width": 10,
                "verticalMargin": 1,
                "horizontalMargin": 1,
                "position": "bottom-right",
                "opacity": 100,
                "animated": False,
                "fixedSize": False,
                "duration": 0,
                "url": "",
            },
            "onDemand": {"enabled": False},
        },
    }
    result = api(tunarr_url, "POST", "/api/channels", body=body)
    if result and "id" not in result:
        result["id"] = channel_id
    return result


def set_programming(tunarr_url, channel_id, schedule_payload):
    return api(tunarr_url, "POST", f"/api/channels/{channel_id}/programming", body=schedule_payload, timeout=120)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Create Tunarr channels from channels.json")
    parser.add_argument("--json", default=DEFAULT_CHANNELS_FILE, help="Channel definition JSON file")
    parser.add_argument("--probe", action="store_true", help="Dry run — show what would be created")
    parser.add_argument("--no-delete", action="store_true", help="Skip deleting existing channels")
    parser.add_argument("--from", dest="from_ch", type=int, default=None, metavar="N",
                        help="Only operate on channels numbered N and above (preserves lower channels)")
    args = parser.parse_args()

    cfg = load_config()
    tunarr_url = cfg["tunarr_url"].rstrip("/")
    plex_url = cfg.get("plex_url", "").rstrip("/")
    plex_token = cfg.get("plex_token", "")

    # ── Load channel definitions ───────────────────────────────────────────────
    try:
        with open(args.json, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {args.json} not found. Run the LLM step first.")
        sys.exit(1)

    channels = data.get("channels", [])
    if not channels:
        print("ERROR: No channels found in JSON")
        sys.exit(1)

    channels.sort(key=lambda c: c.get("number", 999))
    if args.from_ch is not None:
        channels = [c for c in channels if c.get("number", 0) >= args.from_ch]
        print(f"Loaded {len(channels)} channels from {args.json} (filtered to #{args.from_ch}+)")
    else:
        print(f"Loaded {len(channels)} channels from {args.json}")

    # ── Set up Plex collection lookup if needed ────────────────────────────────
    uses_collections = any(
        isinstance(item, dict) and "collection" in item
        for ch in channels
        for item in ch.get("content", [])
    )
    plex_sections = []
    collection_cache = {}
    if uses_collections:
        if not plex_url or not plex_token:
            print("ERROR: plex_url and plex_token required in config.json for collection support")
            sys.exit(1)
        print("\nDiscovering Plex sections for collection lookup...")
        plex_sections = get_plex_sections(plex_url, plex_token)
        print(f"  Found {len(plex_sections)} sections")

    # ── Build library index ────────────────────────────────────────────────────
    print("\nIndexing Tunarr library...")
    movie_map, show_map = build_library_index(tunarr_url)

    transcode_id = get_transcode_config(tunarr_url)
    if not transcode_id and not args.probe:
        print("ERROR: No transcode config found in Tunarr")
        sys.exit(1)

    # ── Delete existing channels ───────────────────────────────────────────────
    if not args.no_delete:
        print("\nDeleting existing channels...")
        delete_channels(tunarr_url, args.probe, from_ch=args.from_ch)

    # ── Create channels ────────────────────────────────────────────────────────
    print(f"\n{'[PROBE] ' if args.probe else ''}Creating {len(channels)} channels...")
    stats = {"created": 0, "skipped": 0, "missing_titles": []}

    for ch in channels:
        number = ch.get("number")
        name = ch.get("name", "Unnamed")
        shuffle = SHUFFLE_MAP.get(ch.get("shuffle", "shuffle"), "shuffle")
        content_list = ch.get("content", [])

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

        if not resolved:
            print(f"  SKIP #{number} {name} — no content found in library")
            stats["skipped"] += 1
            if missing:
                stats["missing_titles"].extend([(name, t) for t in missing])
            continue

        if probe := args.probe:
            tv_count = sum(1 for r in resolved if r["type"] == "TV")
            movie_count = sum(1 for r in resolved if r["type"] == "Movie")
            ep_count = sum(len(r["programs"]) for r in resolved if r["type"] == "TV")
            print(f"  [PROBE] #{number} {name} | shuffle={shuffle} | "
                  f"{tv_count} shows ({ep_count} eps) + {movie_count} movies")
            if missing:
                print(f"    Missing: {', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}")
            stats["created"] += 1
            continue

        # Create channel
        ch_result = create_channel(tunarr_url, number, name, transcode_id)
        if not ch_result:
            print(f"  FAIL #{number} {name} — channel creation failed")
            stats["skipped"] += 1
            continue

        channel_id = ch_result.get("id")

        # Build and post schedule
        schedule = build_schedule(shuffle, resolved)
        if not schedule:
            print(f"  FAIL #{number} {name} — could not build schedule")
            stats["skipped"] += 1
            continue

        prog_result = set_programming(tunarr_url, channel_id, schedule)
        if prog_result is not None:
            ep_count = sum(len(r["programs"]) for r in resolved)
            print(f"  Created #{number} {name} ({ep_count} programs, shuffle={shuffle})")
            if missing:
                print(f"    Not found: {', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}")
            stats["created"] += 1
        else:
            print(f"  FAIL #{number} {name} — programming failed")
            stats["skipped"] += 1

        time.sleep(0.2)

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{'[PROBE] ' if args.probe else ''}Done: {stats['created']} created, {stats['skipped']} skipped")

    if stats["missing_titles"]:
        print(f"\nTitles not found in Tunarr library ({len(stats['missing_titles'])} total):")
        for channel_name, title in stats["missing_titles"][:20]:
            print(f"  [{channel_name}] {title}")
        if len(stats["missing_titles"]) > 20:
            print(f"  ... and {len(stats['missing_titles']) - 20} more")


if __name__ == "__main__":
    main()
