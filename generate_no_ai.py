#!/usr/bin/env python3
"""
generate_no_ai.py — Generate a starter channels.json without any AI.

Reads plex_library.csv and auto-generates:
  - Decade movie channels (Movie block) from year metadata
  - Genre movie channels (Movie block) from genre metadata
  - TV Marathon channels (Marathon block) for shows with 50+ episodes
  - Placeholder entries for franchise/themed channels for manual editing

Block numbers come from the shared channel_blocks layout (see --start / --block-sizes).

Output is a valid channels.json ready for create.py, but franchise channels
will have empty content lists that you fill in manually.

Usage:
    python generate_no_ai.py                    # reads plex_library.csv
    python generate_no_ai.py --csv myfile.csv   # custom input
    python generate_no_ai.py --out myfile.json  # custom output
    python generate_no_ai.py --genres "Comedy,Horror,Western"  # only these genres
    python generate_no_ai.py --decades 1980,1990               # only these decades
    python generate_no_ai.py --types marathons,movies          # skip placeholder blocks

Toggle flags (omit any flag to keep its default = "all"):
    --genres   comma-separated Plex genre tags for movie channels
    --decades  comma-separated decade start years (1970, 1980, …)
    --types    comma-separated content types: marathons, tv_blocks, movies,
               franchise, specialty
    --min-items minimum titles for a genre/decade channel (default 5)
    --start    first channel number (default 10); blocks accumulate from here
    --block-sizes  per-category sizes, e.g. 'marathon=10,movie=20' (default 10/10/20/20/10)
"""

import argparse
import csv
import json
import sys
from collections import defaultdict

import channel_blocks

DEFAULT_CSV = "plex_library.csv"
DEFAULT_OUT = "channels.json"

# Decade buckets: (label, start_year, end_year). Channel numbers within the
# movie block (30–49) are now assigned dynamically, not fixed per decade.
DECADE_RANGES = [
    ("70s Movies",   1970, 1979),
    ("80s Movies",   1980, 1989),
    ("90s Movies",   1990, 1999),
    ("2000s Movies", 2000, 2009),
    ("2010s Movies", 2010, 2019),
    ("2020s Movies", 2020, 2029),
]

# Canonical movie genres: (display name, Plex genre tag). Non-canonical genres
# (anything the user toggles on via "More genres") are named "<tag> Movies".
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

# Content-type blocks generate_no_ai can emit. Marathons + movies are real
# (data-driven); tv_blocks/franchise/specialty are placeholder scaffolds.
ALL_TYPES = ["marathons", "tv_blocks", "movies", "franchise", "specialty"]

DEFAULT_MIN_ITEMS = 5


def parse_block_sizes(val):
    """Parse a 'marathon=10,movie=20,...' CLI string into a size dict.

    Partial maps are fine — channel_blocks.normalize_sizes fills the rest from
    defaults. Malformed pairs are ignored (defaults apply).
    """
    sizes = {}
    for pair in parse_list(val):
        if "=" not in pair:
            continue
        key, _, num = pair.partition("=")
        try:
            sizes[key.strip()] = int(num)
        except ValueError:
            pass
    return sizes


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
    parser.add_argument("--start", type=int, default=10, metavar="N",
                        help="Starting channel number — the first block begins here (default: 10)")
    parser.add_argument("--block-sizes", default=None, metavar="K=N,K=N",
                        help="Per-category block sizes, e.g. 'marathon=10,movie=20'. Omitted "
                             "categories use defaults (10/10/20/20/10). Blocks are placed by "
                             "accumulating sizes from --start.")
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

    layout = channel_blocks.resolve_layout(parse_block_sizes(args.block_sizes), args.start)

    # Resolve toggle selections (None = use defaults / all).
    sel_genres = parse_list(args.genres) if args.genres is not None else [tag for _, tag in CANONICAL_GENRES]
    sel_decade_starts = ({int(y) for y in parse_list(args.decades)}
                         if args.decades is not None else None)  # None = all decades
    sel_types = set(parse_list(args.types)) if args.types is not None else set(ALL_TYPES)

    rows = load_csv(args.csv)
    movies = [r for r in rows if r["Type"] == "Movie"]
    shows = [r for r in rows if r["Type"] == "TV"]

    print(f"Loaded {len(movies)} movies, {len(shows)} TV shows from {args.csv}")
    print("Channel blocks: " + " · ".join(
        f"{channel_blocks.BLOCK_LABELS[k]} {layout[k]['start']}–{layout[k]['end']}"
        for k in channel_blocks.CANONICAL_ORDER))

    channels = []

    # ── TV Marathons (10s): shows with 50+ episodes ────────────────────────────
    if "marathons" in sel_types:
        print("\nBuilding TV Marathon channels (50+ episodes)...")
        ch_num = layout["marathon"]["start"]
        marathon_shows = sorted(
            [s for s in shows if parse_year(s.get("Episodes")) and int(s["Episodes"]) >= 50],
            key=lambda s: -int(s["Episodes"])
        )
        for show in marathon_shows:
            channels.append({
                "number": ch_num,
                "name": f"{show['Title']} 24/7",
                "shuffle": "ordered",
                "content": [show["Title"]],
                "_note": f"{show['Episodes']} episodes, {show['Seasons']} seasons",
            })
            print(f"  #{ch_num} {show['Title']} 24/7 ({show['Episodes']} eps)")
            ch_num += 1
            if ch_num > layout["marathon"]["end"]:
                print("  (TV Marathon block full — remaining marathon candidates skipped)")
                break

    # ── Movie channels (30–49): decades then genres, numbered sequentially ──────
    # Decade and genre channels share the movie block; numbers are assigned in
    # order so an arbitrary set of toggles never collides or leaves fixed gaps.
    if "movies" in sel_types:
        next_num = layout["movie"]["start"]
        block_end = layout["movie"]["end"]

        def emit_movie_channel(name, titles):
            nonlocal next_num
            if next_num > block_end:
                return False
            if len(titles) < args.min_items:
                print(f"  Skipping {name}: only {len(titles)} titles (min {args.min_items})")
                return True
            channels.append({
                "number": next_num,
                "name": name,
                "shuffle": "shuffle",
                "content": sorted(titles),
            })
            print(f"  #{next_num} {name}: {len(titles)} movies")
            next_num += 1
            return True

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
            if not emit_movie_channel(name, titles):
                print("  (movies block full — remaining decade channels skipped)")
                break

        print("\nBuilding genre channels...")
        for genre_tag in sel_genres:
            if next_num > block_end:
                print("  (movies block full — remaining genre channels skipped)")
                break
            genre_lower = genre_tag.lower()
            titles = [
                r["Title"] for r in movies
                if any(g.lower() == genre_lower for g in parse_genres(r.get("Genres", "")))
            ]
            emit_movie_channel(genre_channel_name(genre_tag), titles)

    # ── Franchise placeholders ────────────────────────────────────────────────
    if "franchise" in sel_types:
        print("\nAdding franchise placeholder channels (edit content manually)...")
        _base = layout["franchise"]["start"]
        placeholders = [
            (_base + 0, "Marvel MCU",     "ordered", []),
            (_base + 1, "Star Wars",      "ordered", []),
            (_base + 2, "Indiana Jones",  "ordered", []),
            (_base + 3, "James Bond",     "ordered", []),
            (_base + 4, "The Matrix",     "ordered", []),
        ]
        for num, name, shuffle, content in placeholders:
            channels.append({
                "number": num,
                "name": name,
                "shuffle": shuffle,
                "content": content,
                "_note": "EDIT: add titles manually from plex_library.csv",
            })
            print(f"  #{num} {name} (placeholder)")

    # ── TV Block placeholders ──────────────────────────────────────────────────
    if "tv_blocks" in sel_types:
        print("\nAdding TV block placeholder channels (edit content manually)...")
        _base = layout["tv_block"]["start"]
        tv_placeholders = [
            (_base + 0, "TGIF",                      "block", []),
            (_base + 1, "Saturday Morning Cartoons",  "block", []),
            (_base + 2, "Animated TV Block",          "block", []),
        ]
        for num, name, shuffle, content in tv_placeholders:
            channels.append({
                "number": num,
                "name": name,
                "shuffle": shuffle,
                "content": content,
                "_note": "EDIT: add show titles manually from plex_library.csv",
            })
            print(f"  #{num} {name} (placeholder)")

    # ── Specialty placeholders ────────────────────────────────────────────────
    if "specialty" in sel_types:
        print("\nAdding specialty placeholder channels...")
        _base = layout["specialty"]["start"]
        specialty = [
            (_base + 0, "Hackers 24/7",  "ordered", ["Hackers"]),
            (_base + 1, "Holiday Cheer", "shuffle", []),
        ]
        for num, name, shuffle, content in specialty:
            channels.append({
                "number": num,
                "name": name,
                "shuffle": shuffle,
                "content": content,
                "_note": "" if content else "EDIT: add titles manually",
            })
            print(f"  #{num} {name}")

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
