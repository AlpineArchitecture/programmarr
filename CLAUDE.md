# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## What This Is

A Python 3 pipeline + web app that exports a Plex library, curates themed virtual
TV channels (via an LLM, auto-generation, or Plex collections), and deploys them to
[Tunarr](https://github.com/chrisbenincasa/tunarr). Channels can be marked **live**
to auto-update as the library grows.

Two entry points: a **Docker web app** (primary — FastAPI + React on port 7979) and
an interactive **CLI** (`python programmarr.py`, for power users — first-run config
setup, always probes before deploying, offers Plex sync at the end).

> **Audience note:** user-facing docs (install, quick start, screenshots) live in
> [`README.md`](README.md). **This file is the developer/agent reference** —
> architecture, scripts, endpoints, schema, conventions. Keep it describing **what
> exists today**; planned/unbuilt ideas go in [`docs/ideas.md`](docs/ideas.md).

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
- `--start N` — offsets all block ranges by `N - 10` (default: 10). E.g. `--start 30` shifts TV Marathons to 30–39, TV Blocks to 40–49, etc., leaving lower numbers free for pre-existing channels. Passed automatically by the web UI.
- Output: `channels.json`

**`generate_from_collections.py`** (Option C — Plex collections as channels)
- Fetches all Plex collections via the Plex API
- Generates one channel per collection using `{"collection": "Name"}` syntax
- Manages the collection block (default ch 80+): keeps all channels below `--base`, fully regenerates from `--base` upward
- Collections with the same name in multiple Plex sections are deduplicated (first section wins)
- Flags: `--apply`, `--base N`, `--condense` (skip collections matching existing channel names), `--min-items N`
- Re-run any time Kometa adds/removes collections to keep the block in sync

**`channel_engine.py`** (shared resolution engine)
- Pure, importable building blocks shared by `create.py` (CLI deploy), the `/api/recipes/preview` endpoint, and — going forward — the live-channel scheduler
- Resolution: `api`/`plex_get` HTTP helpers, `build_library_index`, `resolve_title`, `get_plex_sections`, `resolve_collection`, `resolve_content`, `build_schedule`, `set_programming`, `SHUFFLE_MAP`, `ChannelEngineError`
- `resolve_content(content_list, movie_map, show_map, …)` → `(resolved, missing)`. Handles plain title strings, `{"collection": "Name"}` refs (Plex expansion), and `{"match": "title_contains", "value", "order", "exclude"}` franchise refs
- Franchise matching (live recipes): `match_titles(value, movie_map, show_map, order, exclude)` → `(resolved_items, preview)`. **Word-boundary** match (not raw substring — "It" matches "It Follows", not "Little Women"); `order="release_date"` sorts movies by the Tunarr program's `releaseDate` (epoch ms), unknown dates last; `exclude` is a case-insensitive title drop-list. `preview` is `[{title, year}]` for the author-time confirm UI
- In-place updates (live recipes, never delete/recreate): `find_channel_by_number`, `read_channel_programming` (returns the set of currently-scheduled program IDs from `GET /api/channels/{id}/programming` — the `programs` dict keys, same id-space as the library index; the "current" side of the change-detection diff), and `update_channel_in_place(tunarr_url, number, shuffle, resolved)` (looks up the channel by number, rebuilds the schedule, POSTs programming — preserves the Tunarr id + Plex DVR mapping)
- Every function is parameterized by `tunarr_url`/`plex_url`/`token` — nothing reads `config.json`, touches argv, or calls `sys.exit`, so it is safe to import into the long-lived FastAPI process
- Must be listed in the Dockerfile `COPY` line alongside the other pipeline scripts (imported by `create.py` at runtime inside the image, and imported in-process by `recipes_router.py`)

**`create.py`**
- Thin CLI wrapper around `channel_engine.py`; keeps CLI-only concerns (`load_config`, `delete_channels`, `create_channel`, argparse `main()`)
- Reads `channels.json`
- Indexes Tunarr library (exact title matching, case-insensitive)
- Deletes all existing channels then creates new ones (use `--from N` to scope to channels >= N, preserving lower channels and their custom images)
- `--protect N1,N2,...` — comma-separated channel numbers to skip during deletion; these channels remain in Tunarr untouched regardless of scope. Printed as "Preserving #N name (protected)" during the run.
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
| GET | `/api/pipeline/prompt` | Fetch `PROMPT.md` with `{TARGET}`, preferences, and `start` (block offset) injected; query params: `target`, `preferences`, `start` |
| POST | `/api/pipeline/validate` | Parse/validate LLM output (file upload or raw text), write `channels.json` |
| POST | `/api/pipeline/no-ai` | SSE-stream `generate_no_ai.py`; query param `start=N` passed as `--start N` |
| GET | `/api/pipeline/collections` | Fetch all Plex collections (id, name, count, section, summary, has_poster) |
| GET | `/api/pipeline/collections/{id}/poster` | Proxy Plex collection poster image |
| POST | `/api/pipeline/collections/apply` | Write selected collections into `channels.json` |
| POST | `/api/pipeline/probe` | SSE-stream `create.py --probe` |
| POST | `/api/pipeline/deploy` | SSE-stream `create.py`; query params: `protected` (comma-separated channel numbers to preserve), `no_delete` (bool) |
| POST | `/api/pipeline/deploy-selective` | JSON body `DeployRequest{selections, protected_numbers, no_delete}`; filters channels.json to selected entries, writes `deploy_temp.json`, SSE-streams `create.py --json deploy_temp.json [--protect N1,N2,...] [--no-delete]` |
| POST | `/api/pipeline/images` | SSE-stream `fetch_images.py --apply` |
| POST | `/api/pipeline/sync` | SSE-stream `sync_plex.py` |

## Recipe API Endpoints (backend/routers/recipes_router.py)

Live-channel endpoints. Unlike the pipeline router (which spawns scripts as subprocesses), this
router imports `channel_engine` **in-process** — it adds `PROGRAMMARR_SCRIPTS` to `sys.path` so the
engine module (which lives at `/app`, not `/app/backend`) is importable. This is the same wiring the
future scheduler will reuse.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/recipes/preview` | JSON body `{value, exclude?, order?}`; runs `match_titles` against the live Tunarr library and returns `{value, order, count, matches:[{title, year}]}` — the author-time confirm list for a `title_contains` franchise rule (word-boundary match, release-date ordered) |
| GET | `/api/recipes/status` | Scheduler state: `{enabled, paused, running, interval_hours, next_run_seconds, live_count, last_cycle, channels}`. `next_run_seconds` = seconds to next auto cycle (null if disabled/paused); `channels` = per-channel sync metadata from `recipe_state.json` |
| POST | `/api/recipes/run` | Run one cycle on demand. `apply=true` (default) patches; `apply=false` is a dry run (detect + log, no Tunarr writes). `only=<number>` scopes the cycle to one live channel (the per-channel "Sync now"). Same code path the background loop uses |
| POST | `/api/recipes/pause` | `paused=true\|false` — runtime kill switch; halts/resumes the loop without a restart |
| POST | `/api/recipes/config` | JSON body `{enabled, interval_hours}`; **merge-writes** config.json (`recipes_enabled`, `recipe_interval_hours`) so it never clobbers connection/auth keys — unlike the strict `/config` `ConfigModel`. Returns the new status |

The UI surfaces (live-channel authoring in `Channels.tsx`, the Settings "Live
Channels" card, the Dashboard "Auto-Updates" card) and the scheduler
(`backend/scheduler.py`) are summarized in the **Live Channels** section below and
documented in full in [`docs/live-channels-design.md`](docs/live-channels-design.md).

## Run.tsx — Pipeline Stepper UI

`frontend/src/pages/Run.tsx` implements a multi-step pipeline wizard with three paths (tabs): **AI**, **No-AI**, **Collections**.

**Shared patterns:**
- `streamPipeline(endpoint, params, onEvent, body?)` — SSE stream with optional JSON body for selective deploy
- `parseProbeChannels(lines)` — parses `[PROBE] #N name | shuffle=X | summary` lines from probe output into `ChannelSel[]`
- Stepper navigation is locked: only completed steps are clickable, future steps are grayed out

**AI Path (6 steps):**
1. **Export** — fetches Plex library list on mount; shows "Libraries to scan" card with checkboxes grouped by Movies / TV Shows (all checked by default, supports multi-select across libraries of the same type); runs `export.py` with selected section keys; shows compact stats card on success; manual Continue
2. **Channel Planner** — shows current Tunarr lineup as a scrollable checkable list (all checked by default = keep; uncheck = delete and replace with new station); auto-calculates "Channels start at" from the highest checked channel number, rounded up to the nearest 10 (e.g. highest checked is #24 → start at 30); summary line turns yellow and uses explicit "cleared / rebuilt" language when channels will be deleted; config card (target channel count NumberInput + "Channels start at" NumberInput + theme Textarea); side-by-side prompt copy + CSV download; paste/upload LLM output; post-validate results card showing channel breakdown; "Add Plex Collections" or "Skip to Deploy" buttons. Checked channel numbers are passed to Deploy step as `inheritedProtectedNums`.
3. **Add Plex Collections** — fetches collections on mount; list with poster, name, count, editable channel number, checkbox (all checked by default); applies selections to `channels.json`
4. **Deploy** — probe explainer card; shows note about how many channels will be kept (from Channel Planner); runs probe; after probe completes: 2-column layout [terminal | scrollable channel review card with checkboxes + editable channel numbers]; conflict detection highlights red when a deploy number collides with a protected number; selective deploy via `/pipeline/deploy-selective` with `protected_numbers` from Channel Planner
5. **Fetch Images** — skippable step; runs `fetch_images.py --apply`
6. **Sync Plex** — skippable step; runs `sync_plex.py`; post-deploy stats + links to Tunarr and Plex Live TV

**No-AI Path (6 steps):**
1. **Export** — same as AI path
2. **Generate** — "Channels start at" NumberInput (default 1); runs `generate_no_ai.py --start N`; shows channel count on success
3. **Collections** — same as AI path
4. **Deploy** — same as AI Deploy step but with its own protection panel (no inherited protection): shows all existing Tunarr channels after probe, with channels NOT being redeployed checked (protected) by default; user adjusts before deploying
5. **Fetch Images** — same as AI path
6. **Sync Plex** — same as AI path

**Collections Path (4 steps):** Collections → Deploy (with own protection panel) → Fetch Images → Sync Plex (no export or LLM).

**Channel protection model:**
- AI path: user decides which existing channels to keep in the **Channel Planner** step, before even generating the LLM prompt. Checked = protected (passed to deploy as `inheritedProtectedNums`). Deploy step shows a summary and skips the per-deploy panel.
- No-AI / Collections path: user decides in the **Deploy** step's own protection panel after the probe. Channels not in the current deploy are protected by default; channels being redeployed are unprotected by default.
- In both cases, protected channel numbers are passed to `create.py` via `--protect N1,N2,...`.
- Conflict detection: if a protected number equals a deploy channel's `deployNumber`, the row highlights red and the deploy button is disabled until resolved (renumber or unprotect).

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

## Live Channels (Auto-Updating Channels)

A **live channel** (`"live": true` in `channels.json`) is re-resolved against the
Tunarr library on a schedule and patched **in place**, so it stays fresh as the
library grows — new episodes, new franchise films, and new collection members appear
on their own. Ships **off** by default (`recipes_enabled: false`).

**Two rules that must never be broken:**
1. **Update in place.** Look the channel up by number and `set_programming` on the
   existing Tunarr id. **Never** delete-and-recreate a live channel — that changes the
   Tunarr id and breaks the Plex DVR mapping. (`create.py`'s delete/recreate path is
   for *initial* deploy only; the scheduler must never use it.)
2. **Tunarr is the source of truth.** Each cycle diffs freshly-resolved program ids
   against the channel's *current* Tunarr programming and patches **only on a
   difference**. No state file drives correctness — `data/recipe_state.json` is
   cosmetic UI-only metadata (last-synced badges), never read by the diff.

**Moving parts:**
- `backend/scheduler.py` — one in-process asyncio loop started from `main.py`'s
  lifespan; wakes every 60s and runs a cycle when enabled, not paused, and
  `recipe_interval_hours` has elapsed. Shares `deploy_lock` with the pipeline
  endpoints so a manual deploy and a cycle never touch Tunarr concurrently. Skips
  (logs, never fatal) on 404 / unreadable programming / resolve-to-empty.
- `channel_engine.py` — `match_titles` (word-boundary franchise match),
  `read_channel_programming`, `update_channel_in_place`, plus the shared resolution
  helpers. Imported in-process by `recipes_router.py`.
- `recipes_router.py` — the `/api/recipes/*` endpoints (table above).
- Authoring lives in `Channels.tsx` (per-channel Live toggle + franchise builder);
  status shows on the Dashboard "Auto-Updates" card and the Settings "Live Channels" card.

**New content-ref type** — a franchise auto-match, the one new item allowed in a
channel's `content` list:
```json
{"match": "title_contains", "value": "Bad Boys", "order": "release_date", "exclude": []}
```
Word-boundary match (so "It" does not match "Little Women"); `order: "release_date"`
sorts by the Tunarr program's `releaseDate`; `exclude` drops false positives.
Author-time preview (`POST /api/recipes/preview`) requires human confirmation before
saving — the LLM never auto-authors these.

**Config keys** (`config.json`): `recipes_enabled` (bool, default false),
`recipe_interval_hours` (number, default 12).

> **Full design, rationale, rejected alternatives, and history** —
> [`docs/live-channels-design.md`](docs/live-channels-design.md).
