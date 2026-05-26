# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## What This Is

A Python 3 pipeline that exports a Plex library, feeds it to an LLM for channel curation, and creates themed virtual TV channels in [Tunarr](https://github.com/chrisbenincasa/tunarr).

Available as a **Docker web app** (primary) or a **CLI tool** (power users / advanced).

## Recommended Entry Point — Web UI (Docker)

```bash
docker compose up -d
# then open http://<host-ip>:7979
```

First run shows an onboarding wizard: create login credentials → enter Tunarr/Plex/TMDB URLs → dashboard. Config is saved to `./data/config.json` (bind-mounted volume).

## CLI Entry Point (power users)

```powershell
python programmarr.py
```

`programmarr.py` is the interactive CLI wrapper. It handles first-time config setup,
walks through the full workflow for whichever path the user picks, always runs a probe
before deploying, and offers Plex sync at the end.

## Web UI Architecture

**Stack:** FastAPI (Python) + React + Mantine v7 — served as a single Docker container on port 7979.

**Directory layout:**
```
backend/          FastAPI app + routers
  main.py         Entry point — auth middleware, SPA fallback, lifespan
  routers/
    config_router.py    GET/POST /api/config, /api/config/status
    status_router.py    GET /api/status (Plex+Tunarr ping), /api/tunarr/channels
    channels_router.py  CRUD /api/channels, /api/channels/{n}, /api/library/titles
    pipeline_router.py  SSE-streaming pipeline endpoints (export, probe, deploy, deploy-selective, collections, etc.)
    logs_router.py      GET /api/logs, /api/logs/{name}
frontend/         React + Mantine SPA (built to backend/static/)
  src/pages/
    Onboarding.tsx  First-run wizard (shown when config.json missing/unconfigured)
    Dashboard.tsx   Live Tunarr channel grid + connection status
    Run.tsx         Pipeline stepper — AI / No-AI / Collections tabs
    Channels.tsx    channels.json editor (Tier 2: click-to-edit)
    Settings.tsx    config.json editor (masked sensitive fields)
    Logs.tsx        Per-run log viewer
data/             Bind-mounted volume — config.json, channels.json, plex_library.csv, logs/
```

**Environment variables (Docker):**
- `PROGRAMMARR_DATA` — path where data files live (default: `/data`)
- `PROGRAMMARR_SCRIPTS` — path where Python scripts live (default: `/app`)

**Key design decisions:**
- Pipeline scripts (`export.py`, `create.py`, etc.) run as subprocesses with `cwd=DATA_DIR` so their relative file opens work correctly without modification
- SSE (Server-Sent Events) streams subprocess stdout line-by-line to the browser inline terminal
- Auth middleware reads `config.json` on every request — no restart needed to enable/disable auth
- Onboarding shown automatically when `config_status.configured` is false (no Tunarr/Plex/token set)
- Channels page reads from `channels.json` (local file), Dashboard reads live from Tunarr API
- `asyncio.WindowsProactorEventLoopPolicy` is set at startup in `main.py` — required on Windows for `asyncio.create_subprocess_exec` to work; no-op on Linux/Docker
- **Deferred (Tier 3):** drag-to-reorder channels, autocomplete from plex_library.csv, inline Plex validation

## Local Development (Docker)

The recommended local dev loop is Docker — it gives exact production parity and avoids Windows asyncio/subprocess issues:

```powershell
# From repo root — builds frontend, bakes into image, runs on localhost:7979
docker compose build && docker compose up
```

The `docker-compose.yml` mounts `./data` as a volume, so your `config.json`, `channels.json`, and `plex_library.csv` persist between runs. To pick up code changes, rebuild: `docker compose build && docker compose up`.

Note: `backend/static/` is **gitignored** — the Dockerfile builds the frontend from source inside the container (`npm run build` runs during `docker build`). Never commit files under `backend/static/`.

Two environments:
- **localhost:7979** — local Docker build for testing before pushing
- **TrueNAS** — production, runs `ghcr.io/alpinearchitecture/programmarr:latest` with Watchtower for automatic updates. New images land on GHCR within ~1 min of a master push; Watchtower picks them up within 5 min.

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

All config lives in `config.json` (gitignored — lives in `data/` for Docker, project root for CLI):

```json
{
    "tunarr_url":     "http://your-tunarr:8000",
    "plex_url":       "http://your-plex:32400",
    "plex_token":     "your-token",
    "tmdb_api_key":   "your-tmdb-key",
    "auth_username":  "admin",
    "auth_password":  "yourpassword"
}
```

- `tmdb_api_key` — optional, only for `fetch_images.py`. Free key at https://www.themoviedb.org/settings/api
- `auth_username` / `auth_password` — optional HTTP Basic Auth. Set via onboarding wizard or Settings page. When set, every request to the FastAPI backend requires these credentials. Leave both blank to disable auth.

See `config.json.example` for the template.

## Architecture

**`programmarr.py`** (main entry point)
- Flat main menu: `1` AI path, `2` No-AI path, `3` Collections, `i` fetch images, `s` sync Plex, `q` quit — no submenus
- Detects missing `config.json` on first run and walks through interactive setup
- Always runs `create.py --probe` before deploying; asks confirmation before applying
- **Full pipeline (options 1 & 2):** build `channels.json` → optionally append collections → check Tunarr for existing channels → user picks deploy scope → probe → deploy → optionally fetch images → sync Plex → pause for manual Plex steps
- **Pre-deploy scope check:** fetches live channel list from Tunarr before the probe; if channels exist, asks the user to choose between a full wipe-and-rebuild or preserving channels below a given number (passes `--from N` to protect manually-created or lower-block channels and their custom images)
- **Collections in pipeline:** smart base number is computed from AI/No-AI channels only (ignores existing collection-reference channels so re-running doesn't push the base higher each time); same base/min-items/condense prompts as the standalone path
- **Collections standalone (option 3):** generates collection block → probe → deploy (`--from <base>`, preserves lower channels and their images) → optionally fetch images → sync Plex
- **Image fetch standalone (`i`):** dry-run preview → confirm → apply
- **End of every workflow:** pauses after Plex sync with a tip about deleting and re-adding the Tunarr DVR in Plex if channels aren't showing; user presses Enter to return to the main menu
- **AI path prompt generation:** asks for target channel count (replaces `{TARGET}` in prompt) and optional theme/channel preferences (injected as a `## User Preferences` section before channel numbering rules); writes personalised prompt to `prompt_for_llm.md` (gitignored); `PROMPT.md` stays as the clean reusable template
- **LLM output format:** expects JSONL (one channel object per line); `validate_and_fix_channels_json()` auto-detects and converts bare JSON arrays and JSONL to the internal `{"channels": [...]}` dict format before any script reads it — old-format files continue to work

**`export.py`**
- Fetches full metadata directly from Plex API (`/library/sections/{key}/all`)
- Fields: title, year, contentRating, genres, directors, season/episode counts
- Cross-references against Tunarr to flag unsynced content
- Supports multiple sections per type: `--movie-sections KEY1,KEY2` and `--tv-sections KEY1,KEY2` (comma-separated Plex section keys). Deduplicates titles across sections. Omit flags to auto-detect (first movie + first TV section).
- Output: `plex_library.csv` + `export_summary.json` (movies/tv_shows/skipped counts for the UI stats card)

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
- Deletes all existing channels then creates new ones (use `--from N` to scope to channels >= N, preserving lower channels and their custom images)
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

## Pipeline API Endpoints (backend/routers/pipeline_router.py)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/pipeline/libraries` | List Plex library sections filtered to `movie` and `show` types (`{key, title, type}`) |
| POST | `/api/pipeline/export` | SSE-stream `export.py`; JSON body `{"no_crossref": bool, "movie_sections": ["1","2"], "tv_sections": ["3"]}` — sections are Plex section keys; `null` = auto-detect, `[]` = skip that type |
| GET | `/api/pipeline/csv` | Download `plex_library.csv` |
| GET | `/api/pipeline/csv/info` | Stats: rows, movies, tv_shows, skipped counts, preview lines |
| GET | `/api/pipeline/prompt` | Fetch `PROMPT.md` with `{TARGET}` and preferences injected |
| POST | `/api/pipeline/validate` | Parse/validate LLM output (file upload or raw text), write `channels.json` |
| POST | `/api/pipeline/no-ai` | SSE-stream `generate_no_ai.py` |
| GET | `/api/pipeline/collections` | Fetch all Plex collections (id, name, count, section, summary, has_poster) |
| GET | `/api/pipeline/collections/{id}/poster` | Proxy Plex collection poster image |
| POST | `/api/pipeline/collections/apply` | Write selected collections into `channels.json` |
| POST | `/api/pipeline/probe` | SSE-stream `create.py --probe` |
| POST | `/api/pipeline/deploy` | SSE-stream `create.py` (full deploy) |
| POST | `/api/pipeline/deploy-selective` | Filter channels by `DeploySelection[]`, write `deploy_temp.json`, SSE-stream `create.py --json deploy_temp.json` |
| POST | `/api/pipeline/images` | SSE-stream `fetch_images.py --apply` |
| POST | `/api/pipeline/sync` | SSE-stream `sync_plex.py` |

## Run.tsx — Pipeline Stepper UI

`frontend/src/pages/Run.tsx` implements a multi-step pipeline wizard with three paths (tabs): **AI**, **No-AI**, **Collections**.

**Shared patterns:**
- `streamPipeline(endpoint, params, onEvent, body?)` — SSE stream with optional JSON body for selective deploy
- `parseProbeChannels(lines)` — parses `[PROBE] #N name | shuffle=X | summary` lines from probe output into `ChannelSel[]`
- Stepper navigation is locked: only completed steps are clickable, future steps are grayed out

**AI Path (6 steps):**
1. **Export** — fetches Plex library list on mount; shows "Libraries to scan" card with checkboxes grouped by Movies / TV Shows (all checked by default, supports multi-select across libraries of the same type); runs `export.py` with selected section keys; shows compact stats card on success; manual Continue
2. **LLM Handoff** — config card (channel count NumberInput + theme Textarea); side-by-side prompt copy + CSV download; paste/upload LLM output; post-validate results card showing channel breakdown; "Add Plex Collections" or "Skip to Deploy" buttons
3. **Add Plex Collections** — fetches collections on mount; 2-column grid with poster, name, count, editable channel number, checkbox (all checked by default); applies selections to `channels.json`
4. **Deploy** — probe explainer card; runs probe; after probe completes: 2-column layout [terminal | scrollable channel review card with checkboxes + editable channel numbers]; selective deploy via `/pipeline/deploy-selective`
5. **Fetch Images** — skippable step; runs `fetch_images.py --apply`
6. **Sync Plex** — skippable step; runs `sync_plex.py`; post-deploy stats + links to Tunarr and Plex Live TV

**No-AI Path (6 steps):** Same as AI but step 2 runs `generate_no_ai.py` instead of LLM handoff. Step 1 (Export) has the same library picker.

**Collections Path (4 steps):** Collections → Deploy → Fetch Images → Sync Plex (no export or LLM).

**`deploy_temp.json`:** Written by `/pipeline/deploy-selective` when the user excludes channels from a deploy session. The original `channels.json` is not modified — only the channels the user chose are deployed.

## Plex API Endpoints Used

- `GET /library/sections` — discover library section keys
- `GET /library/sections/{key}/all?type=1` — all movies with full metadata
- `GET /library/sections/{key}/all?type=2` — all TV shows with full metadata

No dependencies beyond the Python standard library.

## Known Limitations

### Plex Live TV Guide — Channel Names Not Displaying as Text
Channel names do not appear as text in Plex's Live TV guide channel column — only the channel icon image is shown. This is **not a bug in Programmarr**.

**Root cause:** When Plex receives a channel with any icon in the XMLTV feed, it renders only the icon in the guide's left column and suppresses the text label entirely. Tunarr injects its default `tunarr.png` for every channel, so without custom icons the guide shows a wall of identical color-bar icons with no names.

**Current state (after `fetch_images.py`):** Solo-title channels (TV marathons ch 10–19, single-movie specialty channels) now display their real TMDB clearlogo in the guide instead of the generic Tunarr icon. Multi-title channels (genre/decade/themed blocks) still show the Tunarr default until a logo strategy is implemented for them.

**What doesn't fix the text-label issue:** Refreshing the Plex guide, restarting Plex, updating `startTime`, tweaking channel settings. The text suppression is a Plex design decision when any icon is present.

**The `startTime` fix (commit c9d52d6):** Channels were being created with `startTime=0` (Unix epoch / Dec 31 1969). This was a real bug — Plex's guide rendered nothing at all in the channel slot until a guide refresh — but fixing it does not make channel names appear. The names issue is a separate Plex design limitation.

## Git Workflow

- Commit messages must be verbose and descriptive — explain what changed and why, not just "fix bug" or "update script".
- Update this file (CLAUDE.md) whenever a feature changes: new flags, API behavior changes, schema updates, new scripts, or removed functionality.
- After any feature change: update CLAUDE.md, commit with a detailed message, and push to origin.
