#!/usr/bin/env python3
"""
generate_no_ai.py — Generate a starter channels.json without any AI.

Reads plex_library.csv and auto-generates:
  - Decade movie channels (30s block) from year metadata
  - Genre movie channels (30s block) from genre metadata
  - TV Marathon placeholders (10s block) for shows with 50+ episodes
  - Placeholder entries for franchise/themed channels for manual editing

Output is a valid channels.json ready for create.py, but franchise channels
will have empty content lists that you fill in manually.

Usage:
    python generate_no_ai.py                    # reads plex_library.csv
    python generate_no_ai.py --csv myfile.csv   # custom input
    python generate_no_ai.py --out myfile.json  # custom output
"""

import argparse
import csv
import json
import sys
from collections import defaultdict

DEFAULT_CSV = "plex_library.csv"
DEFAULT_OUT = "channels.json"

DECADE_RANGES = [
    ("70s Movies",         30, 1970, 1979),
    ("80s Movies",         31, 1980, 1989),
    ("90s Movies",         32, 1990, 1999),
    ("2000s Movies",       33, 2000, 2009),
    ("2010s Movies",       34, 2010, 2019),
    ("2020s Movies",       35, 2020, 2029),
]

GENRE_CHANNELS = [
    ("Comedy Movies",      36, "Comedy"),
    ("Action Movies",      37, "Action"),
    ("Horror Movies",      38, "Horror"),
    ("Sci-Fi Movies",      39, "Science Fiction"),
    ("Drama Movies",       40, "Drama"),
    ("Animation Movies",   41, "Animation"),
    ("Documentary Movies", 42, "Documentary"),
]

TV_MARATHON_START = 10
PLAYLIST_PLACEHOLDER_START = 50


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


def main():
    parser = argparse.ArgumentParser(description="Generate starter channels.json without AI")
    parser.add_argument("--csv", default=DEFAULT_CSV, help="Input CSV from export.py")
    parser.add_argument("--out", default=DEFAULT_OUT, help="Output JSON path")
    args = parser.parse_args()

    rows = load_csv(args.csv)
    movies = [r for r in rows if r["Type"] == "Movie"]
    shows = [r for r in rows if r["Type"] == "TV"]

    print(f"Loaded {len(movies)} movies, {len(shows)} TV shows from {args.csv}")

    channels = []

    # ── TV Marathons (10s): shows with 50+ episodes ────────────────────────────
    print("\nBuilding TV Marathon channels (50+ episodes)...")
    ch_num = TV_MARATHON_START
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
        if ch_num > 19:
            print("  (10s block full — remaining marathon candidates skipped)")
            break

    # ── Decade channels (30s) ──────────────────────────────────────────────────
    print("\nBuilding decade channels...")
    decades_used = set()
    for name, ch_num, start, end in DECADE_RANGES:
        titles = [
            r["Title"] for r in movies
            if parse_year(r["Year"]) and start <= parse_year(r["Year"]) <= end
        ]
        if not titles:
            continue
        channels.append({
            "number": ch_num,
            "name": name,
            "shuffle": "shuffle",
            "content": sorted(titles),
        })
        decades_used.add(ch_num)
        print(f"  #{ch_num} {name}: {len(titles)} movies")

    # ── Genre channels (36+) ───────────────────────────────────────────────────
    print("\nBuilding genre channels...")
    next_num = 36
    for name, suggested_num, genre_tag in GENRE_CHANNELS:
        # Don't collide with decade channels
        while next_num in decades_used or any(c["number"] == next_num for c in channels):
            next_num += 1
        if next_num > 49:
            print("  (30s block full — remaining genre channels skipped)")
            break

        genre_lower = genre_tag.lower()
        titles = [
            r["Title"] for r in movies
            if any(g.lower() == genre_lower for g in parse_genres(r.get("Genres", "")))
        ]
        if len(titles) < 5:
            print(f"  Skipping {name}: only {len(titles)} titles")
            continue

        channels.append({
            "number": next_num,
            "name": name,
            "shuffle": "shuffle",
            "content": sorted(titles),
        })
        print(f"  #{next_num} {name}: {len(titles)} movies")
        next_num += 1

    # ── Franchise placeholders (50s) ──────────────────────────────────────────
    print("\nAdding franchise placeholder channels (edit content manually)...")
    placeholders = [
        (50, "Marvel MCU",                  "ordered",  []),
        (51, "Star Wars",                   "ordered",  []),
        (52, "Indiana Jones",               "ordered",  []),
        (53, "James Bond",                  "ordered",  []),
        (54, "The Matrix",                  "ordered",  []),
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

    # ── TV Block placeholders (20s) ────────────────────────────────────────────
    print("\nAdding TV block placeholder channels (edit content manually)...")
    tv_placeholders = [
        (20, "TGIF",                     "block",   []),
        (21, "Saturday Morning Cartoons", "block",  []),
        (22, "Animated TV Block",         "block",  []),
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

    # ── Specialty placeholders (70s) ──────────────────────────────────────────
    print("\nAdding specialty placeholder channels...")
    specialty = [
        (70, "Hackers 24/7",      "ordered", ["Hackers"]),
        (71, "Holiday Cheer",     "shuffle", []),
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
