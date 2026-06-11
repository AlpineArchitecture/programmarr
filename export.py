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
        print("Create it with: tunarr_url and plex_servers (or plex_url + plex_token)")
        sys.exit(1)
    if not cfg.get("tunarr_url"):
        print(f"ERROR: 'tunarr_url' missing from {CONFIG_FILE}")
        sys.exit(1)
    has_plex = cfg.get("plex_servers") or (cfg.get("plex_url") and cfg.get("plex_token"))
    if not has_plex:
        print(f"ERROR: Plex connection missing — set plex_servers or plex_url + plex_token in {CONFIG_FILE}")
        sys.exit(1)
    return cfg


def _get_plex_servers(cfg):
    """Return list of (name, url, token) for all configured Plex servers."""
    servers = cfg.get("plex_servers") or []
    if servers:
        return [
            (s.get("name", "Plex"), s["url"].rstrip("/"), s["token"])
            for s in servers
            if s.get("url") and s.get("token")
        ]
    return [("Plex", cfg["plex_url"].rstrip("/"), cfg["plex_token"])]


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
    plex_sources = [s for s in sources if s.get("type") == "plex"]
    if not plex_sources:
        print("  WARNING: No Plex source in Tunarr — skipping cross-reference")
        return None, None

    movie_titles: set = set()
    tv_titles: set    = set()

    for plex_source in plex_sources:
        libs = plex_source.get("libraries", [])
        movie_libs = [l for l in libs if l.get("mediaType") in ("movie", "movies") and l.get("enabled")]
        tv_libs    = [l for l in libs if l.get("mediaType") == "shows" and l.get("enabled")]

        for lib in movie_libs:
            programs = tunarr_get(tunarr_url, f"/api/media-libraries/{lib['id']}/programs", timeout=120) or []
            titles   = {p.get("program", {}).get("title", "").lower().strip() for p in programs}
            movie_titles |= titles
            print(f"  Tunarr has {len(titles)} movies ({lib.get('name', lib['id'])})")

        for lib in tv_libs:
            programs = tunarr_get(tunarr_url, f"/api/media-libraries/{lib['id']}/programs", timeout=120) or []
            titles   = {p.get("program", {}).get("show", {}).get("title", "").lower().strip()
                        for p in programs if p.get("program", {}).get("show")}
            tv_titles |= titles
            print(f"  Tunarr has {len(titles)} TV shows ({lib.get('name', lib['id'])})")

    if movie_titles:
        print(f"  Tunarr movie total (all sources): {len(movie_titles)}")
    if tv_titles:
        print(f"  Tunarr TV total (all sources): {len(tv_titles)}")

    return movie_titles, tv_titles


# ── Row builders ───────────────────────────────────────────────────────────────

# Top-N billed cast kept per title — enough for actor channels without the noise
# of full cast lists. Plex Role elements come back in billing order.
LEAD_CAST = 3


def _lead_actors(item):
    return "|".join(r["tag"] for r in item.get("Role", [])[:LEAD_CAST] if r.get("tag"))


def _join_tags(item, tag_name):
    """Return a pipe-joined string of tag values for a given tag array key.

    Plex returns tag arrays as lists of dicts with a "tag" key, e.g.:
        [{"tag": "France"}, {"tag": "Japan"}]
    Returns an empty string when the key is absent or the list is empty.
    Works for Genre, Country, Mood, Style, and any other tag array.
    """
    return "|".join(t["tag"] for t in item.get(tag_name, []) if t.get("tag"))


def movie_to_row(item):
    return {
        "Title": item.get("title", ""),
        "Year": item.get("year", ""),
        "Type": "Movie",
        "Rating": item.get("contentRating", ""),
        "Genres": _join_tags(item, "Genre"),
        "Director": _join_tags(item, "Director"),
        "Studio": item.get("studio", ""),
        "Actors": _lead_actors(item),
        "Seasons": "",
        "Episodes": "",
        "Country": _join_tags(item, "Country"),
        "Mood": _join_tags(item, "Mood"),
        "Style": _join_tags(item, "Style"),
    }


def show_to_row(item):
    return {
        "Title": item.get("title", ""),
        "Year": item.get("year", ""),
        "Type": "TV",
        "Rating": item.get("contentRating", ""),
        "Genres": _join_tags(item, "Genre"),
        "Director": "",
        "Studio": item.get("studio", ""),
        "Actors": _lead_actors(item),
        "Seasons": item.get("childCount", ""),
        "Episodes": item.get("leafCount", ""),
        "Country": _join_tags(item, "Country"),
        "Mood": _join_tags(item, "Mood"),
        "Style": _join_tags(item, "Style"),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Export Plex library to CSV")
    parser.add_argument("--out", default=OUTPUT_FILE, help="Output CSV path")
    parser.add_argument("--no-crossref", action="store_true", help="Skip Tunarr sync check")
    parser.add_argument("--movie-sections", default=None,
                        help="Comma-separated section keys for movies (auto-detect if omitted, empty = skip). Applied to all servers.")
    parser.add_argument("--tv-sections", default=None,
                        help="Comma-separated section keys for TV shows (auto-detect if omitted, empty = skip). Applied to all servers.")
    args = parser.parse_args()

    cfg = load_config()
    tunarr_url = cfg["tunarr_url"].rstrip("/")
    plex_server_list = _get_plex_servers(cfg)
    multi = len(plex_server_list) > 1

    # ── Discover and fetch from all Plex servers ───────────────────────────────
    print(f"\n[1/4] Discovering Plex library sections ({len(plex_server_list)} server(s))...")

    plex_movies: list = []
    plex_shows: list  = []
    seen_movie_titles: set = set()
    seen_show_titles: set  = set()

    for srv_name, srv_url, srv_token in plex_server_list:
        print(f"\n  Server: {srv_name} ({srv_url})")
        sections = get_plex_sections(srv_url, srv_token)
        if not sections:
            print(f"  WARNING: Could not reach {srv_name} or no sections found — skipping")
            continue

        if args.movie_sections is not None:
            keys = {k.strip() for k in args.movie_sections.split(",") if k.strip()}
            movie_sections = [s for s in sections if s.get("key") in keys and s.get("type") == "movie"]
        else:
            movie_sections = [s for s in sections if s.get("type") == "movie"]

        if args.tv_sections is not None:
            keys = {k.strip() for k in args.tv_sections.split(",") if k.strip()}
            tv_sections = [s for s in sections if s.get("key") in keys and s.get("type") == "show"]
        else:
            tv_sections = [s for s in sections if s.get("type") == "show"]

        for s in movie_sections:
            print(f"  Movie section: [{s['key']}] {s['title']}")
        for s in tv_sections:
            print(f"  TV section:    [{s['key']}] {s['title']}")

        # ── Fetch Plex content ─────────────────────────────────────────────────
        print(f"\n[2/4] Fetching content from {srv_name}...")
        for sec in movie_sections:
            for item in fetch_plex_movies(srv_url, srv_token, sec["key"]):
                t = item.get("title", "").lower().strip()
                if t not in seen_movie_titles:
                    seen_movie_titles.add(t)
                    item["_source_name"] = srv_name if multi else ""
                    plex_movies.append(item)

        for sec in tv_sections:
            for item in fetch_plex_shows(srv_url, srv_token, sec["key"]):
                t = item.get("title", "").lower().strip()
                if t not in seen_show_titles:
                    seen_show_titles.add(t)
                    item["_source_name"] = srv_name if multi else ""
                    plex_shows.append(item)

    if not plex_movies and not plex_shows:
        print("ERROR: No content fetched from any Plex server")
        sys.exit(1)

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
        row = movie_to_row(item)
        row["Source"] = item.get("_source_name", "")
        rows.append(row)

    for item in plex_shows:
        title = item.get("title", "")
        if tunarr_shows is not None and title.lower().strip() not in tunarr_shows:
            skipped_shows.append(title)
            continue
        row = show_to_row(item)
        row["Source"] = item.get("_source_name", "")
        rows.append(row)

    # ── Write CSV ──────────────────────────────────────────────────────────────
    fieldnames = ["Title", "Year", "Type", "Rating", "Genres", "Director", "Studio", "Actors", "Seasons", "Episodes",
                  "Country", "Mood", "Style", "Source"]
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

    with open("export_summary.json", "w", encoding="utf-8") as f:
        json.dump({
            "movies": movies_written,
            "tv_shows": shows_written,
            "skipped_movies": len(skipped_movies),
            "skipped_shows": len(skipped_shows),
        }, f)


if __name__ == "__main__":
    main()
