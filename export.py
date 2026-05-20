#!/usr/bin/env python3
"""
export.py — Export Plex library to CSV for LLM channel generation.

Fetches full metadata from Plex (genres, ratings, directors, episode counts),
cross-references against Tunarr to keep only synced content, and writes
plex_library.csv ready to paste into any LLM.

Usage:
    python export.py                    # writes plex_library.csv
    python export.py --out myfile.csv   # custom output path
    python export.py --no-crossref      # skip Tunarr sync check
"""

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request

CONFIG_FILE = "config.json"
OUTPUT_FILE = "plex_library.csv"


# ── Config ─────────────────────────────────────────────────────────────────────

def load_config():
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {CONFIG_FILE} not found.")
        print("Create it with: tunarr_url, plex_url, plex_token")
        sys.exit(1)
    for key in ("tunarr_url", "plex_url", "plex_token"):
        if not cfg.get(key):
            print(f"ERROR: '{key}' missing from {CONFIG_FILE}")
            sys.exit(1)
    return cfg


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


def tunarr_get(base_url, path, timeout=60):
    req = urllib.request.Request(base_url + path, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  ! Tunarr error [{path}]: {e}")
        return None


# ── Plex fetchers ──────────────────────────────────────────────────────────────

def get_plex_sections(plex_url, token):
    data = plex_get(plex_url, token, "/library/sections")
    if not data:
        return []
    return data["MediaContainer"].get("Directory", [])


def fetch_plex_movies(plex_url, token, section_key):
    print(f"  Fetching Plex movies (section {section_key})...")
    data = plex_get(plex_url, token, f"/library/sections/{section_key}/all?type=1", timeout=120)
    if not data:
        return []
    items = data["MediaContainer"].get("Metadata", [])
    print(f"  Found {len(items)} movies in Plex")
    return items


def fetch_plex_shows(plex_url, token, section_key):
    print(f"  Fetching Plex TV shows (section {section_key})...")
    data = plex_get(plex_url, token, f"/library/sections/{section_key}/all?type=2", timeout=120)
    if not data:
        return []
    items = data["MediaContainer"].get("Metadata", [])
    print(f"  Found {len(items)} shows in Plex")
    return items


# ── Tunarr cross-reference ─────────────────────────────────────────────────────

def build_tunarr_title_sets(tunarr_url):
    print("  Fetching Tunarr library for cross-reference...")
    sources = tunarr_get(tunarr_url, "/api/media-sources") or []
    plex_source = next((s for s in sources if s.get("type") == "plex"), None)
    if not plex_source:
        print("  WARNING: No Plex source in Tunarr — skipping cross-reference")
        return None, None

    libs = plex_source.get("libraries", [])
    movie_lib = next((l for l in libs if l.get("mediaType") in ("movie", "movies") and l.get("enabled")), None)
    tv_lib = next((l for l in libs if l.get("mediaType") == "shows" and l.get("enabled")), None)

    movie_titles = set()
    tv_titles = set()

    if movie_lib:
        programs = tunarr_get(tunarr_url, f"/api/media-libraries/{movie_lib['id']}/programs", timeout=120) or []
        movie_titles = {p.get("program", {}).get("title", "").lower().strip() for p in programs}
        print(f"  Tunarr has {len(movie_titles)} movies")

    if tv_lib:
        programs = tunarr_get(tunarr_url, f"/api/media-libraries/{tv_lib['id']}/programs", timeout=120) or []
        tv_titles = {p.get("program", {}).get("show", {}).get("title", "").lower().strip() for p in programs if p.get("program", {}).get("show")}
        print(f"  Tunarr has {len(tv_titles)} TV shows")

    return movie_titles, tv_titles


# ── Row builders ───────────────────────────────────────────────────────────────

def movie_to_row(item):
    genres = "|".join(g["tag"] for g in item.get("Genre", []))
    directors = "|".join(d["tag"] for d in item.get("Director", []))
    return {
        "Title": item.get("title", ""),
        "Year": item.get("year", ""),
        "Type": "Movie",
        "Rating": item.get("contentRating", ""),
        "Genres": genres,
        "Director": directors,
        "Seasons": "",
        "Episodes": "",
    }


def show_to_row(item):
    genres = "|".join(g["tag"] for g in item.get("Genre", []))
    return {
        "Title": item.get("title", ""),
        "Year": item.get("year", ""),
        "Type": "TV",
        "Rating": item.get("contentRating", ""),
        "Genres": genres,
        "Director": "",
        "Seasons": item.get("childCount", ""),
        "Episodes": item.get("leafCount", ""),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Export Plex library to CSV")
    parser.add_argument("--out", default=OUTPUT_FILE, help="Output CSV path")
    parser.add_argument("--no-crossref", action="store_true", help="Skip Tunarr sync check")
    args = parser.parse_args()

    cfg = load_config()
    plex_url = cfg["plex_url"].rstrip("/")
    plex_token = cfg["plex_token"]
    tunarr_url = cfg["tunarr_url"].rstrip("/")

    # ── Discover Plex sections ─────────────────────────────────────────────────
    print("\n[1/4] Discovering Plex library sections...")
    sections = get_plex_sections(plex_url, plex_token)
    if not sections:
        print("ERROR: Could not reach Plex or no sections found")
        sys.exit(1)

    movie_section = next((s for s in sections if s.get("type") == "movie"), None)
    tv_section = next((s for s in sections if s.get("type") == "show"), None)

    if not movie_section:
        print("ERROR: No movie library found in Plex")
        sys.exit(1)
    if not tv_section:
        print("ERROR: No TV show library found in Plex")
        sys.exit(1)

    print(f"  Movie section: [{movie_section['key']}] {movie_section['title']}")
    print(f"  TV section:    [{tv_section['key']}] {tv_section['title']}")

    # ── Fetch Plex content ─────────────────────────────────────────────────────
    print("\n[2/4] Fetching Plex content...")
    plex_movies = fetch_plex_movies(plex_url, plex_token, movie_section["key"])
    plex_shows = fetch_plex_shows(plex_url, plex_token, tv_section["key"])

    # ── Cross-reference with Tunarr ────────────────────────────────────────────
    tunarr_movies = None
    tunarr_shows = None

    if not args.no_crossref:
        print("\n[3/4] Cross-referencing with Tunarr...")
        tunarr_movies, tunarr_shows = build_tunarr_title_sets(tunarr_url)
    else:
        print("\n[3/4] Skipping Tunarr cross-reference (--no-crossref)")

    # ── Filter and build rows ──────────────────────────────────────────────────
    print("\n[4/4] Building export...")
    rows = []
    skipped_movies = []
    skipped_shows = []

    for item in plex_movies:
        title = item.get("title", "")
        if tunarr_movies is not None and title.lower().strip() not in tunarr_movies:
            skipped_movies.append(title)
            continue
        rows.append(movie_to_row(item))

    for item in plex_shows:
        title = item.get("title", "")
        if tunarr_shows is not None and title.lower().strip() not in tunarr_shows:
            skipped_shows.append(title)
            continue
        rows.append(show_to_row(item))

    # ── Write CSV ──────────────────────────────────────────────────────────────
    fieldnames = ["Title", "Year", "Type", "Rating", "Genres", "Director", "Seasons", "Episodes"]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # ── Summary ────────────────────────────────────────────────────────────────
    movies_written = sum(1 for r in rows if r["Type"] == "Movie")
    shows_written = sum(1 for r in rows if r["Type"] == "TV")

    print(f"\n  Exported {movies_written} movies, {shows_written} TV shows -> {args.out}")

    if skipped_movies:
        print(f"\n  Skipped {len(skipped_movies)} movies not in Tunarr (not synced):")
        for t in sorted(skipped_movies)[:10]:
            print(f"    - {t}")
        if len(skipped_movies) > 10:
            print(f"    ... and {len(skipped_movies) - 10} more")

    if skipped_shows:
        print(f"\n  Skipped {len(skipped_shows)} shows not in Tunarr (not synced):")
        for t in sorted(skipped_shows):
            print(f"    - {t}")

    print(f"\nDone. Feed {args.out} to your LLM with the prompt in PROMPT.md")


if __name__ == "__main__":
    main()
