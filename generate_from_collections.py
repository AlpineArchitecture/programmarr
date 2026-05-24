#!/usr/bin/env python3
"""
generate_from_collections.py — Generate channels.json entries from Plex collections.

Fetches every Plex collection and writes one channel per collection into
channels.json, starting at --base (default 80). Existing channels below
the base number are preserved unchanged. The collection block is fully
regenerated each run.

Usage:
    python generate_from_collections.py              # dry run, preview changes
    python generate_from_collections.py --apply      # write to channels.json
    python generate_from_collections.py --base 90    # start channel numbers at 90
    python generate_from_collections.py --condense   # skip collections whose names
                                                     # match existing channel names
    python generate_from_collections.py --min-items 5  # skip tiny collections
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

CONFIG_FILE = "config.json"
DEFAULT_CHANNELS_FILE = "channels.json"
DEFAULT_BASE = 80


# ── Config ─────────────────────────────────────────────────────────────────────

def load_config():
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {CONFIG_FILE} not found.")
        sys.exit(1)
    for key in ("plex_url", "plex_token"):
        if not cfg.get(key):
            print(f"ERROR: '{key}' missing from {CONFIG_FILE}")
            sys.exit(1)
    return cfg


# ── Plex API ───────────────────────────────────────────────────────────────────

def plex_get(base_url, token, path, timeout=30):
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


def fetch_all_collections(plex_url, token):
    """Return list of dicts with name, count, section — in Plex display order.

    Collections with the same name in multiple sections are deduplicated;
    the first section (in Plex order) wins. resolve_collection in create.py
    also searches sections in order, so the same item will be resolved.
    """
    data = plex_get(plex_url, token, "/library/sections")
    if not data:
        return []
    sections = data["MediaContainer"].get("Directory", [])

    results = []
    seen_names = set()
    for section in sections:
        section_key = section.get("key")
        section_title = section.get("title", "")
        col_data = plex_get(plex_url, token, f"/library/sections/{section_key}/collections")
        if not col_data:
            continue
        for c in col_data["MediaContainer"].get("Metadata", []):
            name = c.get("title", "").strip()
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            results.append({
                "name": name,
                "count": int(c.get("childCount", 0)),
                "section": section_title,
            })
    return results


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate channels.json entries from Plex collections"
    )
    parser.add_argument("--json", default=DEFAULT_CHANNELS_FILE, help="channels.json path")
    parser.add_argument("--apply", action="store_true",
                        help="Write changes to channels.json (default: dry run)")
    parser.add_argument("--base", type=int, default=DEFAULT_BASE,
                        help=f"Starting channel number for collection block (default: {DEFAULT_BASE})")
    parser.add_argument("--condense", action="store_true",
                        help="Skip collections whose names match existing channels below --base")
    parser.add_argument("--min-items", type=int, default=0, metavar="N",
                        help="Skip collections with fewer than N items")
    args = parser.parse_args()

    cfg = load_config()
    plex_url = cfg["plex_url"].rstrip("/")
    plex_token = cfg["plex_token"]

    # ── Load channels.json ─────────────────────────────────────────────────────
    try:
        with open(args.json, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {args.json} not found.")
        sys.exit(1)

    existing = data.get("channels", [])
    kept = [ch for ch in existing if ch.get("number", 0) < args.base]
    replaced = [ch for ch in existing if ch.get("number", 0) >= args.base]

    # Names of kept channels for --condense matching
    kept_names = {ch.get("name", "").lower().strip() for ch in kept}

    # ── Fetch collections ──────────────────────────────────────────────────────
    print("Fetching Plex collections...")
    collections = fetch_all_collections(plex_url, plex_token)
    print(f"  Found {len(collections)} collections\n")

    # ── Build new channel block ────────────────────────────────────────────────
    new_channels = []
    skipped_condense = []
    skipped_small = []
    channel_num = args.base

    for col in collections:
        name = col["name"]
        count = col["count"]
        section = col["section"]

        if args.min_items and count < args.min_items:
            skipped_small.append(col)
            continue

        if args.condense and name.lower().strip() in kept_names:
            skipped_condense.append(col)
            continue

        new_channels.append({
            "number": channel_num,
            "name": name,
            "shuffle": "shuffle",
            "content": [{"collection": name}],
        })
        channel_num += 1

    # ── Report ─────────────────────────────────────────────────────────────────
    if not args.apply:
        print("DRY RUN — pass --apply to write to channels.json\n")

    print(f"Keeping {len(kept)} channels below #{args.base}")
    if replaced:
        print(f"Replacing {len(replaced)} existing collection channels (#{args.base}+)")
    print()

    if skipped_small:
        print(f"Skipped {len(skipped_small)} collections with fewer than {args.min_items} items:")
        for c in skipped_small:
            print(f"  [{c['section']}] {c['name']} ({c['count']} items)")
        print()

    if skipped_condense:
        print(f"Skipped {len(skipped_condense)} collections matching existing channel names (--condense):")
        for c in skipped_condense:
            print(f"  [{c['section']}] {c['name']} ({c['count']} items)")
        print()

    print(f"Collection channels ({len(new_channels)}):")
    for ch in new_channels:
        col_name = ch["content"][0]["collection"]
        info = next((c for c in collections if c["name"] == col_name), {})
        print(f"  #{ch['number']:3d}  {ch['name']}  [{info.get('section','')}]  ({info.get('count','?')} items)")

    if not args.apply:
        print(f"\nRun with --apply to write {len(kept) + len(new_channels)} channels to {args.json}")
        return

    # ── Write ──────────────────────────────────────────────────────────────────
    data["channels"] = kept + new_channels
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(data['channels'])} channels to {args.json}")
    print(f"  {len(kept)} kept + {len(new_channels)} collection channels "
          f"(#{args.base}–#{channel_num - 1})")


if __name__ == "__main__":
    main()
