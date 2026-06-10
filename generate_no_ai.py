#!/usr/bin/env python3
"""
generate_no_ai.py — Generate a starter channels.json without any AI.

Reads plex_library.csv and auto-generates:
  - TV Marathon channels from shows with 50+ episodes
  - Decade movie channels from year metadata
  - Genre movie channels from genre metadata
  - Placeholder entries for franchise/specialty channels for manual editing

Channel numbers are assigned sequentially from --start, packed tight in the
category order given by --order (or the canonical default order from
channel_blocks.CANONICAL_ORDER).  Empty categories consume no numbers.

Output is a valid channels.json ready for create.py, but franchise/specialty
channels will have empty content lists that you fill in manually.

Usage:
    python generate_no_ai.py                    # reads plex_library.csv
    python generate_no_ai.py --csv myfile.csv   # custom input
    python generate_no_ai.py --out myfile.json  # custom output
    python generate_no_ai.py --genres "Comedy,Horror,Western"  # only these genres
    python generate_no_ai.py --decades 1980,1990               # only these decades
    python generate_no_ai.py --types marathons,movies          # skip placeholder blocks
    python generate_no_ai.py --order marathon,movie,franchise  # category order
    python generate_no_ai.py --start 1                         # first channel number

Toggle flags (omit any flag to keep its default = "all"):
    --genres   comma-separated Plex genre tags for movie channels
    --decades  comma-separated decade start years (1970, 1980, …)
    --types    comma-separated content types: marathons, tv_blocks, movies,
               franchise, specialty
    --order    comma-separated category keys controlling numbering order
               (default: channel_blocks.CANONICAL_ORDER)
    --min-items minimum titles for a genre/decade channel (default 5)
    --start    first channel number (default 1)
"""

import argparse
import csv
import json
import sys
from collections import defaultdict

import channel_blocks

DEFAULT_CSV = "plex_library.csv"
DEFAULT_OUT = "channels.json"
DEFAULT_START = channel_blocks.DEFAULT_START

# Decade buckets: (label, start_year, end_year).
DECADE_RANGES = [
    ("70s Movies",   1970, 1979),
    ("80s Movies",   1980, 1989),
    ("90s Movies",   1990, 1999),
    ("2000s Movies", 2000, 2009),
    ("2010s Movies", 2010, 2019),
    ("2020s Movies", 2020, 2029),
]

# Canonical movie genres: (display name, Plex genre tag).
CANONICAL_GENRES = [
    ("Comedy",      "Comedy"),
    ("Action",      "Action"),
    ("Horror",      "Horror"),
    ("Sci-Fi",      "Science Fiction"),
    ("Drama",       "Drama"),
    ("Animation",   "Animation"),
    ("Documentary", "Documentary"),
]
TAG_TO_DISPLAY = {tag.lower(): disp for disp, tag in CANONICAL_GENRES}

# Content-type blocks generate_no_ai can emit.
ALL_TYPES = ["marathons", "tv_blocks", "movies", "franchise", "specialty"]

DEFAULT_MIN_ITEMS = 5


def load_csv(path):
    try:
        with open(path, encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        print(f"ERROR: {path} not found. Run export.py first.")
        sys.exit(1)


def parse_year(val):
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def parse_genres(val):
    if not val:
        return []
    return [g.strip() for g in val.split("|") if g.strip()]


def genre_channel_name(tag):
    """Display name for a genre channel: canonical genres get their friendly name."""
    return f"{TAG_TO_DISPLAY.get(tag.lower(), tag)} Movies"


def parse_list(val):
    """Comma-separated CLI list → trimmed, non-empty items."""
    if not val:
        return []
    return [x.strip() for x in val.split(",") if x.strip()]


def main():
    parser = argparse.ArgumentParser(description="Generate starter channels.json without AI")
    parser.add_argument("--csv", default=DEFAULT_CSV, help="Input CSV from export.py")
    parser.add_argument("--out", default=DEFAULT_OUT, help="Output JSON path")
    parser.add_argument("--start", type=int, default=DEFAULT_START, metavar="N",
                        help="Starting channel number — the first category begins here (default: 1)")
    parser.add_argument("--order", default=None, metavar="KEY,KEY",
                        help="Comma-separated category keys controlling numbering order "
                             "(e.g. 'marathon,movie,franchise'). Default: canonical order from "
                             "channel_blocks.CANONICAL_ORDER.")
    parser.add_argument("--genres", default=None, metavar="TAG,TAG",
                        help="Comma-separated Plex genre tags to build movie channels for "
                             "(e.g. 'Comedy,Science Fiction,Western'). Default: all canonical genres.")
    parser.add_argument("--decades", default=None, metavar="YEAR,YEAR",
                        help="Comma-separated decade start years to build (e.g. '1970,1990'). "
                             "Default: all decades present in the library.")
    parser.add_argument("--types", default=None, metavar="TYPE,TYPE",
                        help=f"Comma-separated content types to emit (any of: {', '.join(ALL_TYPES)}). "
                             "Default: all. No-AI only truly generates marathons + movies; the rest "
                             "are placeholder scaffolds.")
    parser.add_argument("--min-items", type=int, default=DEFAULT_MIN_ITEMS, metavar="N",
                        help=f"Minimum titles for a genre/decade movie channel (default: {DEFAULT_MIN_ITEMS}).")
    args = parser.parse_args()

    order = channel_blocks.resolve_order(parse_list(args.order) or None)

    # Resolve toggle selections (None = use defaults / all).
    sel_genres = parse_list(args.genres) if args.genres is not None else [tag for _, tag in CANONICAL_GENRES]
    sel_decade_starts = ({int(y) for y in parse_list(args.decades)}
                         if args.decades is not None else None)  # None = all decades
    sel_types = set(parse_list(args.types)) if args.types is not None else set(ALL_TYPES)

    rows = load_csv(args.csv)
    movies = [r for r in rows if r["Type"] == "Movie"]
    shows = [r for r in rows if r["Type"] == "TV"]

    print(f"Loaded {len(movies)} movies, {len(shows)} TV shows from {args.csv}")

    # ── Build channels per category, collecting them before numbering ─────────
    # Each category bucket holds channel dicts without numbers yet.
    marathon_channels: list[dict] = []
    tv_block_channels: list[dict] = []
    movie_channels: list[dict] = []
    franchise_channels: list[dict] = []
    specialty_channels: list[dict] = []

    # ── TV Marathons: shows with 50+ episodes ────────────────────────────────
    if "marathons" in sel_types:
        print("\nBuilding TV Marathon channels (50+ episodes)...")
        marathon_shows = sorted(
            [s for s in shows if parse_year(s.get("Episodes")) and int(s["Episodes"]) >= 50],
            key=lambda s: -int(s["Episodes"])
        )
        for show_row in marathon_shows:
            marathon_channels.append({
                "name": f"{show_row['Title']} 24/7",
                "shuffle": "ordered",
                "content": [show_row["Title"]],
                "_note": f"{show_row['Episodes']} episodes, {show_row['Seasons']} seasons",
            })
            print(f"  {show_row['Title']} 24/7 ({show_row['Episodes']} eps)")

    # ── TV Block placeholders ─────────────────────────────────────────────────
    if "tv_blocks" in sel_types:
        print("\nAdding TV block placeholder channels (edit content manually)...")
        tv_placeholders = [
            ("TGIF",                      "block", []),
            ("Saturday Morning Cartoons",  "block", []),
            ("Animated TV Block",          "block", []),
        ]
        for name, shuffle, content in tv_placeholders:
            tv_block_channels.append({
                "name": name,
                "shuffle": shuffle,
                "content": content,
                "_note": "EDIT: add show titles manually from plex_library.csv",
            })
            print(f"  {name} (placeholder)")

    # ── Movie channels: decades then genres ──────────────────────────────────
    if "movies" in sel_types:
        print("\nBuilding decade channels...")
        for name, yr_start, yr_end in DECADE_RANGES:
            if sel_decade_starts is not None and yr_start not in sel_decade_starts:
                continue
            titles = [
                r["Title"] for r in movies
                if parse_year(r["Year"]) and yr_start <= parse_year(r["Year"]) <= yr_end
            ]
            if not titles:
                continue
            if len(titles) < args.min_items:
                print(f"  Skipping {name}: only {len(titles)} titles (min {args.min_items})")
                continue
            movie_channels.append({
                "name": name,
                "shuffle": "shuffle",
                "content": sorted(titles),
            })
            print(f"  {name}: {len(titles)} movies")

        print("\nBuilding genre channels...")
        for genre_tag in sel_genres:
            genre_lower = genre_tag.lower()
            titles = [
                r["Title"] for r in movies
                if any(g.lower() == genre_lower for g in parse_genres(r.get("Genres", "")))
            ]
            if len(titles) < args.min_items:
                print(f"  Skipping {genre_channel_name(genre_tag)}: only {len(titles)} titles (min {args.min_items})")
                continue
            movie_channels.append({
                "name": genre_channel_name(genre_tag),
                "shuffle": "shuffle",
                "content": sorted(titles),
            })
            print(f"  {genre_channel_name(genre_tag)}: {len(titles)} movies")

    # ── Franchise placeholders ────────────────────────────────────────────────
    if "franchise" in sel_types:
        print("\nAdding franchise placeholder channels (edit content manually)...")
        placeholders = [
            ("Marvel MCU",     "ordered", []),
            ("Star Wars",      "ordered", []),
            ("Indiana Jones",  "ordered", []),
            ("James Bond",     "ordered", []),
            ("The Matrix",     "ordered", []),
        ]
        for name, shuffle, content in placeholders:
            franchise_channels.append({
                "name": name,
                "shuffle": shuffle,
                "content": content,
                "_note": "EDIT: add titles manually from plex_library.csv",
            })
            print(f"  {name} (placeholder)")

    # ── Specialty placeholders ────────────────────────────────────────────────
    if "specialty" in sel_types:
        print("\nAdding specialty placeholder channels...")
        specialty_list = [
            ("Hackers 24/7",  "ordered", ["Hackers"]),
            ("Holiday Cheer", "shuffle", []),
        ]
        for name, shuffle, content in specialty_list:
            specialty_channels.append({
                "name": name,
                "shuffle": shuffle,
                "content": content,
                "_note": "" if content else "EDIT: add titles manually",
            })
            print(f"  {name}")

    # ── Assign numbers using sequential tight packing ─────────────────────────
    # Map generate_no_ai type buckets to channel_blocks category keys.
    bucket_map = {
        "marathon":  marathon_channels,
        "tv_block":  tv_block_channels,
        "movie":     movie_channels,
        "franchise": franchise_channels,
        "specialty": specialty_channels,
    }
    counts = {cat: len(bucket_map.get(cat, [])) for cat in channel_blocks.CANONICAL_ORDER}
    numbers = channel_blocks.assign_numbers(order, counts, args.start)

    print("\nCategory order and numbers:")
    for cat in order:
        if numbers.get(cat):
            label = channel_blocks.BLOCK_LABELS.get(cat, cat)
            nums = numbers[cat]
            print(f"  {label}: {nums[0]}–{nums[-1]}")

    channels: list[dict] = []
    for cat in order:
        cat_channels = bucket_map.get(cat, [])
        cat_numbers = numbers.get(cat, [])
        for num, ch in zip(cat_numbers, cat_channels):
            channels.append({"number": num, **ch})

    # ── Write output ───────────────────────────────────────────────────────────
    channels.sort(key=lambda c: c["number"])
    output = {
        "channels": channels,
        "orphaned": [],
        "suggested_channels": [],
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(channels)} channels to {args.out}")
    print("Edit placeholder channels (content: []) before running create.py")


if __name__ == "__main__":
    main()
