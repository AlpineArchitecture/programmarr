# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## What This Is

A Python 3 CLI pipeline that exports a Plex library, feeds it to an LLM for channel curation, and creates themed virtual TV channels in [Tunarr](https://github.com/chrisbenincasa/tunarr).

## Recommended Entry Point

```powershell
python channelmaker.py
```

`channelmaker.py` is the interactive CLI wrapper. It handles first-time config setup,
walks through the full workflow for whichever path the user picks, always runs a probe
before deploying, and offers Plex sync at the end. Most users should never need to run
the individual scripts directly.

## Workflow

```
export.py  ->  LLM (Gemini/Claude/ChatGPT)  ->  create.py
               or
export.py  ->  generate_no_ai.py  ->  create.py
```

Plex collections (managed by Kometa/Trakt/Letterboxd) can be turned into
channels directly without the export/LLM step:

```
generate_from_collections.py --apply  ->  create.py
```

## Running the Scripts (advanced / direct use)

```powershell
# Step 1 — export Plex library to CSV
python export.py

# Step 2a — AI path: paste plex_library.csv + PROMPT.md into any LLM, save output as channels.json
# Step 2b — no-AI path: auto-generate starter channels.json from metadata
python generate_no_ai.py

# Step 2c — collection path: generate one channel per Plex collection (80+ block)
python generate_from_collections.py              # preview
python generate_from_collections.py --apply      # write to channels.json
python generate_from_collections.py --condense   # skip collections matching existing channel names
python generate_from_collections.py --min-items 5  # skip tiny collections
python generate_from_collections.py --base 90    # start at channel 90 instead of 80

# Step 3 — create channels in Tunarr
python create.py --probe    # dry run first
python create.py            # apply
```

## Configuration

All config lives in `config.json` (gitignored — never hardcode credentials):

```json
{
    "tunarr_url": "http://your-tunarr:8000",
    "plex_url":   "http://your-plex:32400",
    "plex_token": "your-token",
    "tmdb_api_key": "your-tmdb-key"
}
```

`tmdb_api_key` is optional — only required for `fetch_images.py`. Get a free key at https://www.themoviedb.org/settings/api

See `config.json.example` for the template.

## Architecture

**`channelmaker.py`** (main entry point)
- Interactive CLI menu with three workflow paths: AI, No-AI, Collections
- Detects missing `config.json` on first run and walks through interactive setup
- Always runs `create.py --probe` before deploying; asks confirmation before applying
- Offers Plex sync after every successful deploy
- Collections path reads `channels.json` to compute a smart default for `--base`
- Utilities submenu: fetch images (dry run then confirm), sync Plex

**`export.py`**
- Fetches full metadata directly from Plex API (`/library/sections/{key}/all`)
- Fields: title, year, contentRating, genres, directors, season/episode counts
- Cross-references against Tunarr to flag unsynced content
- Output: `plex_library.csv`

**`generate_no_ai.py`** (Option B — no AI required)
- Reads `plex_library.csv`
- Auto-generates decade channels (year filtering) and genre channels (genre tag matching)
- Auto-generates TV marathon channels for shows with 50+ episodes
- Writes placeholder entries for franchise/themed channels (user fills manually)
- Output: `channels.json`

**`generate_from_collections.py`** (Option C — Plex collections as channels)
- Fetches all Plex collections via the Plex API
- Generates one channel per collection using `{"collection": "Name"}` syntax
- Manages the collection block (default ch 80+): keeps all channels below `--base`, fully regenerates from `--base` upward
- Collections with the same name in multiple Plex sections are deduplicated (first section wins)
- Flags: `--apply`, `--base N`, `--condense` (skip collections matching existing channel names), `--min-items N`
- Re-run any time Kometa adds/removes collections to keep the block in sync

**`create.py`**
- Reads `channels.json`
- Indexes Tunarr library (exact title matching, case-insensitive)
- Deletes all existing channels, creates new ones
- Builds Tunarr random-schedule payloads (30-day rolling window — channels loop forever, no dead air)
- Output: channels live in Tunarr

**`fetch_images.py`**
- Reads `channels.json`, finds channels with exactly one content item (solo TV show or solo movie)
- Searches TMDB for the title (TV first, then movie), picks the best English clearlogo by vote score
- Updates the Tunarr channel via `PUT /api/channels/{id}` with `icon.path` set to the TMDB image URL
- Tunarr then serves that URL in its XMLTV output, so Plex displays the real show/movie logo in the guide
- Multi-title channels (genre blocks, decade collections, themed rotations) are skipped — handle separately
- Default is dry run; use `--apply` to commit changes
- Flags: `--apply`, `--channel <number>`, `--clear` (removes all custom icons)
- Requires `tmdb_api_key` in `config.json`

**`sync_plex.py`**
- Compares Tunarr's XMLTV channel list against Plex's DVR channel mappings
- Attempts a soft update (PUT to device endpoint) to add missing channels
- Verifies the update actually took effect by re-fetching Plex state
- If auto-sync fails or no DVR is configured, prints the XMLTV URL and manual setup steps
- Never deletes the Plex DVR — read-then-update only

## Channel Numbering Scheme

| Block  | Range | Content |
|--------|-------|---------|
| TV Marathons | 10–19 | 24/7 single-show loops (50+ episodes) |
| TV Blocks    | 20–29 | Themed multi-show rotations |
| Movies       | 30–49 | Genre and decade channels |
| Franchise    | 50–69 | Ordered series (MCU, Batman, etc.) |
| Specialty    | 70–79 | Single-movie loops, holiday, niche |

## channels.json Schema

```json
{
  "channels": [
    {
      "number": 10,
      "name": "Channel Name",
      "shuffle": "ordered",
      "content": ["Exact Title From Plex"]
    }
  ],
  "orphaned": [],
  "suggested_channels": []
}
```

**shuffle values:** `ordered` | `shuffle` | `block`

Content items can be plain title strings **or** Plex collection references:

```json
"content": [
  "Breaking Bad",
  {"collection": "Criterion Collection"}
]
```

Collection references are expanded to their member titles at deploy time via the Plex API. Plain strings and collection objects can be freely mixed in the same channel. If a named collection is not found in Plex, a warning is printed and the entry is skipped.

Plain title strings must match Plex library names exactly (case-insensitive).
A title can appear on multiple channels — this is intentional and expected.

## Tunarr API Endpoints Used

- `GET /api/media-sources` — discover Plex source and library IDs
- `GET /api/media-libraries/{id}/programs` — all episodes/movies in a library
- `GET /api/transcode_configs` — fetch transcode config ID at runtime
- `GET /api/channels` — list existing channels
- `POST /api/channels` — create channel
- `DELETE /api/channels/{id}` — delete channel
- `POST /api/channels/{id}/programming` — set rolling schedule (body: `{"type":"random","programs":[...],"schedule":{...}}`; schedule requires `padStyle` and `randomDistribution` as of current Tunarr version)
- `PUT /api/channels/{id}` — update channel settings (used by `fetch_images.py` to set `icon.path`)

## TMDB API Endpoints Used

- `GET /3/search/tv?query=...` — search for TV show by title
- `GET /3/search/movie?query=...` — search for movie by title
- `GET /3/tv/{id}/images?include_image_language=en,null` — fetch logo images for a TV show
- `GET /3/movie/{id}/images?include_image_language=en,null` — fetch logo images for a movie
- Images served from `https://image.tmdb.org/t/p/original/{file_path}`

## Plex API Endpoints Used

- `GET /library/sections` — discover library section keys
- `GET /library/sections/{key}/all?type=1` — all movies with full metadata
- `GET /library/sections/{key}/all?type=2` — all TV shows with full metadata

No dependencies beyond the Python standard library.

## Known Limitations

### Plex Live TV Guide — Channel Names Not Displaying as Text
Channel names do not appear as text in Plex's Live TV guide channel column — only the channel icon image is shown. This is **not a bug in ChannelMaker**.

**Root cause:** When Plex receives a channel with any icon in the XMLTV feed, it renders only the icon in the guide's left column and suppresses the text label entirely. Tunarr injects its default `tunarr.png` for every channel, so without custom icons the guide shows a wall of identical color-bar icons with no names.

**Current state (after `fetch_images.py`):** Solo-title channels (TV marathons ch 10–19, single-movie specialty channels) now display their real TMDB clearlogo in the guide instead of the generic Tunarr icon. Multi-title channels (genre/decade/themed blocks) still show the Tunarr default until a logo strategy is implemented for them.

**What doesn't fix the text-label issue:** Refreshing the Plex guide, restarting Plex, updating `startTime`, tweaking channel settings. The text suppression is a Plex design decision when any icon is present.

**The `startTime` fix (commit c9d52d6):** Channels were being created with `startTime=0` (Unix epoch / Dec 31 1969). This was a real bug — Plex's guide rendered nothing at all in the channel slot until a guide refresh — but fixing it does not make channel names appear. The names issue is a separate Plex design limitation.

## Git Workflow

- Commit messages must be verbose and descriptive — explain what changed and why, not just "fix bug" or "update script".
- Update this file (CLAUDE.md) whenever a feature changes: new flags, API behavior changes, schema updates, new scripts, or removed functionality.
- After any feature change: update CLAUDE.md, commit with a detailed message, and push to origin.
