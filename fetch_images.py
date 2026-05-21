#!/usr/bin/env python3
"""
fetch_images.py — Fetch TMDB logos for single-title channels and set them in Tunarr.

Only processes channels with exactly one content item (solo TV show or solo movie).
Multi-title channels (TGIF, genre blocks, decades) are skipped.

Requires "tmdb_api_key" in config.json. Get a free key at https://www.themoviedb.org/settings/api

Usage:
    python fetch_images.py              # dry run — shows what logo would be used
    python fetch_images.py --apply      # actually update Tunarr channel icons
    python fetch_images.py --channel 10 # dry run for one channel only
    python fetch_images.py --channel 10 --apply
    python fetch_images.py --clear      # remove all custom icons (reset to tunarr default)
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CONFIG_FILE = "config.json"
DEFAULT_CHANNELS_FILE = "channels.json"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/original"


# ── Config ─────────────────────────────────────────────────────────────────────

def load_config():
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {CONFIG_FILE} not found.")
        sys.exit(1)

    if not cfg.get("tmdb_api_key"):
        print("ERROR: 'tmdb_api_key' not found in config.json.")
        print("  Get a free key at https://www.themoviedb.org/settings/api")
        print("  Then add: \"tmdb_api_key\": \"your-key-here\" to config.json")
        sys.exit(1)

    return cfg


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ChannelMaker/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        print(f"  ! HTTP {e.code}: {url}")
        return None
    except Exception as e:
        print(f"  ! Error fetching {url}: {e}")
        return None


def tunarr_get(tunarr_url, path):
    return http_get(tunarr_url + path, timeout=30)


def tunarr_put(tunarr_url, path, body):
    url = tunarr_url + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Accept": "application/json", "Content-Type": "application/json"},
                                 method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        print(f"  ! HTTP {e.code} [PUT {path}]: {raw[:200]}")
        return None
    except Exception as e:
        print(f"  ! Error [PUT {path}]: {e}")
        return None


# ── TMDB lookup ────────────────────────────────────────────────────────────────

def tmdb_search_tv(title, api_key):
    q = urllib.parse.urlencode({"query": title, "api_key": api_key})
    data = http_get(f"https://api.themoviedb.org/3/search/tv?{q}")
    if not data or not data.get("results"):
        return None
    return data["results"][0]["id"]


def tmdb_search_movie(title, api_key):
    q = urllib.parse.urlencode({"query": title, "api_key": api_key})
    data = http_get(f"https://api.themoviedb.org/3/search/movie?{q}")
    if not data or not data.get("results"):
        return None
    return data["results"][0]["id"]


def tmdb_best_logo(images, prefer_lang="en"):
    """Pick the best logo from a TMDB images response. Returns file_path or None."""
    logos = images.get("logos", [])
    if not logos:
        return None

    # Prefer English logos, then null/no-language, then anything
    for lang in (prefer_lang, None, ""):
        candidates = [l for l in logos if l.get("iso_639_1") == lang]
        if candidates:
            best = max(candidates, key=lambda l: l.get("vote_average", 0))
            return best["file_path"]

    # Fallback: highest vote regardless of language
    best = max(logos, key=lambda l: l.get("vote_average", 0))
    return best["file_path"]


def fetch_logo_url(title, api_key):
    """
    Try TV search, then movie search. Returns (logo_url, media_type) or (None, None).
    """
    # Try TV first
    tv_id = tmdb_search_tv(title, api_key)
    if tv_id:
        q = urllib.parse.urlencode({"api_key": api_key, "include_image_language": "en,null"})
        images = http_get(f"https://api.themoviedb.org/3/tv/{tv_id}/images?{q}")
        if images:
            path = tmdb_best_logo(images)
            if path:
                return TMDB_IMAGE_BASE + path, "TV"

    time.sleep(0.25)  # be polite to TMDB rate limits

    # Try movie
    movie_id = tmdb_search_movie(title, api_key)
    if movie_id:
        q = urllib.parse.urlencode({"api_key": api_key, "include_image_language": "en,null"})
        images = http_get(f"https://api.themoviedb.org/3/movie/{movie_id}/images?{q}")
        if images:
            path = tmdb_best_logo(images)
            if path:
                return TMDB_IMAGE_BASE + path, "Movie"

    return None, None


# ── Tunarr channel helpers ─────────────────────────────────────────────────────

def get_tunarr_channels(tunarr_url):
    """Returns dict of number -> full channel object."""
    channels = tunarr_get(tunarr_url, "/api/channels") or []
    by_number = {}
    for ch in channels:
        full = tunarr_get(tunarr_url, f"/api/channels/{ch['id']}")
        if full:
            by_number[ch["number"]] = full
    return by_number


def update_channel_icon(tunarr_url, channel, icon_url, apply):
    """Set icon.path on a Tunarr channel. Returns True on success."""
    updated = dict(channel)
    updated["icon"] = dict(channel.get("icon", {}))
    updated["icon"]["path"] = icon_url
    updated["icon"]["useDefaultIconFallback"] = False

    if not apply:
        return True

    result = tunarr_put(tunarr_url, f"/api/channels/{channel['id']}", updated)
    return result is not None


def clear_channel_icon(tunarr_url, channel, apply):
    """Reset icon.path to empty/default on a Tunarr channel."""
    updated = dict(channel)
    updated["icon"] = dict(channel.get("icon", {}))
    updated["icon"]["path"] = ""
    updated["icon"]["useDefaultIconFallback"] = True

    if not apply:
        return True

    result = tunarr_put(tunarr_url, f"/api/channels/{channel['id']}", updated)
    return result is not None


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fetch TMDB logos for solo-title Tunarr channels")
    parser.add_argument("--json", default=DEFAULT_CHANNELS_FILE, help="channels.json file")
    parser.add_argument("--apply", action="store_true", help="Actually update Tunarr (default is dry run)")
    parser.add_argument("--channel", type=int, help="Process only this channel number")
    parser.add_argument("--clear", action="store_true", help="Remove all custom icons, reset to Tunarr default")
    args = parser.parse_args()

    cfg = load_config()
    tunarr_url = cfg["tunarr_url"].rstrip("/")
    tmdb_key = cfg["tmdb_api_key"]

    try:
        with open(args.json, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {args.json} not found.")
        sys.exit(1)

    channels_def = data.get("channels", [])

    if not args.apply:
        print("DRY RUN — pass --apply to update Tunarr\n")

    # ── Clear mode ─────────────────────────────────────────────────────────────
    if args.clear:
        print("Fetching Tunarr channels...")
        tunarr_chs = get_tunarr_channels(tunarr_url)
        cleared = 0
        for number, tch in sorted(tunarr_chs.items()):
            if tch.get("icon", {}).get("path"):
                label = f"#{number} {tch['name']}"
                if args.apply:
                    ok = clear_channel_icon(tunarr_url, tch, apply=True)
                    print(f"  {'Cleared' if ok else 'FAIL  '} {label}")
                    if ok:
                        cleared += 1
                else:
                    print(f"  [DRY RUN] Would clear {label}")
                    cleared += 1
        print(f"\nDone: {cleared} icons {'cleared' if args.apply else 'would be cleared'}")
        return

    # ── Normal mode: fetch logos for single-content channels ───────────────────

    # Filter to solo-content channels
    solo = [ch for ch in channels_def if len(ch.get("content", [])) == 1]
    if args.channel:
        solo = [ch for ch in solo if ch["number"] == args.channel]
        if not solo:
            ch_match = next((c for c in channels_def if c["number"] == args.channel), None)
            if ch_match:
                cnt = len(ch_match.get("content", []))
                print(f"Channel #{args.channel} has {cnt} content items — only solo channels are supported here.")
            else:
                print(f"Channel #{args.channel} not found in {args.json}")
            sys.exit(1)

    print(f"Found {len(solo)} solo-title channel(s) to process\n")

    print("Fetching Tunarr channels...")
    tunarr_chs = get_tunarr_channels(tunarr_url)
    print()

    stats = {"set": 0, "no_logo": 0, "no_channel": 0, "failed": 0}

    for ch_def in solo:
        number = ch_def["number"]
        name = ch_def["name"]
        title = ch_def["content"][0]

        tch = tunarr_chs.get(number)
        if not tch:
            print(f"  SKIP #{number} {name} — not found in Tunarr (not deployed yet?)")
            stats["no_channel"] += 1
            continue

        print(f"  #{number} {name}  [{title}]", end="", flush=True)

        logo_url, media_type = fetch_logo_url(title, tmdb_key)
        time.sleep(0.25)

        if not logo_url:
            print(f"  -- no logo found on TMDB")
            stats["no_logo"] += 1
            continue

        ok = update_channel_icon(tunarr_url, tch, logo_url, apply=args.apply)
        if ok:
            verb = "Set" if args.apply else "[DRY RUN] Would set"
            print(f"  -- {verb} {media_type} logo")
            print(f"    {logo_url}")
            stats["set"] += 1
        else:
            print(f"  -- FAILED to update Tunarr")
            stats["failed"] += 1

    print(f"\n{'Applied' if args.apply else 'Dry run'}: "
          f"{stats['set']} logos {'set' if args.apply else 'found'}, "
          f"{stats['no_logo']} not found on TMDB, "
          f"{stats['no_channel']} channels not in Tunarr"
          + (f", {stats['failed']} failed" if stats["failed"] else ""))


if __name__ == "__main__":
    main()
