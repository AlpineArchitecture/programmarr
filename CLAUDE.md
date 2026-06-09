# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

> **Keep this lean and current.** Point at code and docs; don't restate them — paraphrased
> code is the #1 source of drift. Behavior changes update this file in the **same commit**.
> History → `CHANGELOG.md`; full designs → `docs/`; exhaustive endpoint/flag reference →
> [`docs/api.md`](docs/api.md) & each script's `--help`. If a section outgrows its job,
> relocate the detail and leave a pointer.

## What This Is

A Python 3 pipeline + web app that exports a Plex library, **composes curated themed
virtual TV channels** in a deterministic Planner (with an optional AI layer on top),
and deploys them to [Tunarr](https://github.com/chrisbenincasa/tunarr). Channels can
be marked **live** to auto-update as the library grows.

The web app's channel-creation experience is a single **Planner** (`Run.tsx`): pick
genres/decades "in play," then check exact curated candidates — per-show marathons,
genre×decade cuts, named sub-genres, and studio/director/actor channels — built
deterministically via `/pipeline/compose`. An optional "✨ Bring in AI" layer adds
*discovery* (themed channels filters miss) and *tonal curation* (split a broad pool by
vibe), merged on top.

Two entry points: a **Docker web app** (primary — FastAPI + React on port 7979) and
an interactive **CLI** (`python programmarr.py`, for power users — first-run config
setup, always probes before deploying, offers Plex sync at the end).

> **Audience:** user-facing docs (install, quick start, screenshots) live in
> [`README.md`](README.md). **This file is the developer/agent reference** —
> architecture, conventions, the rules an agent must not break. It describes **what
> exists today**; planned/unbuilt ideas go in [`docs/ideas.md`](docs/ideas.md).

## Web UI Architecture

**Stack:** FastAPI (Python) + React + Mantine v7 — served as a single Docker container on port 7979.

**Directory layout:**
```
backend/          FastAPI app + routers
  main.py         Entry point — auth middleware, SPA fallback, lifespan, scheduler start
  scheduler.py    In-process asyncio loop for live channels (see Live Channels)
  routers/        config / status / channels / pipeline / recipes / logs routers
frontend/         React + Mantine SPA (built to backend/static/)
  src/pages/      Onboarding, Dashboard, Run (the Planner stepper), Channels, Settings, Logs
data/             Bind-mounted volume — config.json, channels.json, plex_library.csv, logs/
```

**Environment variables (Docker):**
- `PROGRAMMARR_DATA` — path where data files live (default: `/data`)
- `PROGRAMMARR_SCRIPTS` — path where Python scripts live (default: `/app`)

**Key design decisions (non-obvious — don't undo these):**
- Pipeline scripts (`export.py`, `create.py`, etc.) run as subprocesses with `cwd=DATA_DIR` so their relative file opens work unmodified.
- SSE (Server-Sent Events) streams subprocess stdout line-by-line to the browser inline terminal.
- Auth middleware reads `config.json` on every request — no restart needed to enable/disable auth.
- Onboarding shows automatically when `config_status.configured` is false (no Tunarr/Plex/token set).
- **Dashboard** shows an EPG guide grid (fetched via `GET /api/guide` → Tunarr XMLTV). Clicking a channel navigates to its editor.
- **Channels page** lists channels from the live Tunarr API (`GET /api/tunarr/channels`); clicking a row fetches the full `channels.json` entry and opens the editor. Channels in Tunarr with no `channels.json` entry show as **"Not managed by Programmarr"** (read-only orphans).
- **Save and Apply** (`POST /api/channels/{number}/apply`) saves a channel edit to `channels.json` and pushes it to Tunarr in place — preserving the Tunarr id and Plex DVR mapping. This is the Channels-page equivalent of the scheduler's per-channel update, but available for any channel (not just live ones).
- `asyncio.WindowsProactorEventLoopPolicy` is set at startup in `main.py` — **required** on Windows for `asyncio.create_subprocess_exec`; no-op on Linux/Docker. (This is the one place it's stated; don't duplicate it.)
- **Deferred (Tier 3):** drag-to-reorder channels, autocomplete from plex_library.csv, inline Plex validation.

## Local Development

Two loops: the **fast loop** for iterating, the **parity loop** (Docker) for the final
check before shipping. Always run the parity loop before a release.

**Fast loop — hot reload:**
```powershell
.\dev.ps1          # opens Vite (:5173) + uvicorn --reload (:7979)
```
Open **http://localhost:5173** (not 7979). Vite serves the SPA with HMR and proxies `/api`
→ the reload backend. Both read/write the real `./data` files, so behavior matches Docker.
Requires a local Python env with backend `requirements.txt` and `npm install` in `frontend/`.

**Parity loop — Docker (run before shipping):**
```powershell
docker compose build && docker compose up    # localhost:7979
```
`docker-compose.yml` mounts `./data` as a volume so config/channels/csv persist. Rebuild to
pick up code changes. `backend/static/` is **gitignored** — the Dockerfile builds the frontend
inside the image (`npm run build` during `docker build`); **never commit files under `backend/static/`.**

**Tests:**
```powershell
pip install -r backend/requirements-dev.txt   # one-time (pytest; dev-only, not in the image)
pytest                                         # reads pytest.ini -> backend/tests
```
Each test seeds a temp `DATA_DIR` with a synthetic `plex_library.csv` (the `seed` fixture in
`conftest.py`) — nothing touches a real Plex/Tunarr. Covers `library_facets`, `compose_channels`,
`validate(append=True)`, `discover_prompt`, and `generate_no_ai`.

**Environments:** **localhost:7979** = local Docker before pushing. **TrueNAS** = production,
runs `ghcr.io/alpinearchitecture/programmarr:latest` with Watchtower (new image on GHCR ~1 min
after a master push; Watchtower picks it up within ~5 min).

**Demo dataset:** `python scripts/make_demo_data.py` (re)generates the committed `demo/` dir
(synthetic `plex_library.csv` + `channels.json` + safe `config.json`) used for deterministic doc
screenshots. See the script's header for usage and which pages render offline.

## Workflow

```
export.py  ->  LLM (Gemini/Claude/ChatGPT)  ->  create.py
               or
export.py  ->  generate_no_ai.py             ->  create.py
```

Plex collections (managed by Kometa/Trakt/Letterboxd) can become channels directly,
skipping the export/LLM step:

```
generate_from_collections.py --apply  ->  create.py
```

For direct CLI use of any script (flags, dry-run/probe, scoping), see its `--help`.

## Configuration

All config lives in `config.json` (gitignored — in `data/` for Docker, project root for CLI).
See `config.json.example` for the full shape. Keys:

- `tunarr_url`, `plex_url`, `plex_token` — required connection settings.
- `tmdb_api_key` — optional; only `fetch_images.py` uses it. Free key at https://www.themoviedb.org/settings/api
- `auth_username` / `auth_password` — optional HTTP Basic Auth. **Both blank = auth disabled.** When set, every backend request requires them.
- `recipes_enabled` (bool, default `false`), `recipe_interval_hours` (number, default `12`) — live-channel scheduler (see Live Channels).
- `tunarr_channel_group` (string, optional) — Tunarr `groupTitle` for all created channels (default `"tunarr"`).
- `tunarr_stream_mode` (string, optional) — Tunarr `streamMode`, lowercase enum: `hls`|`hls_slower`|`mpegts`|`hls_direct`|`hls_direct_v2` (default `"hls"`). Applied by `create.py` at channel creation; **not** exposed in the UI.
- `channel_order` (array, optional) — ordered list of category keys controlling channel numbering, e.g. `["marathon","tv_block","movie","franchise","specialty"]`. Omit for the canonical default order. **Editable in Settings → Channel Numbering.** See Channel Numbering Scheme. (Old `channel_blocks` size key is silently ignored.)

> `config_router.save_config` **merge-writes** `config.json`, so editing these (or the `recipes_*`) keys
> by hand survives a Settings save — the UI form only overwrites the keys it manages. (`channel_order`
> is preserved on an empty save, never wiped — see `save_config`.)

## Architecture

Each script's role and the gotcha worth knowing. Flags and exact behavior live in `--help`
and the code — don't restate them here.

- **`programmarr.py`** — CLI entry point. Flat menu (AI / No-AI / Collections / images / sync / quit). Walks first-run config setup, **always probes before deploying**, and pre-deploy asks whether to wipe-and-rebuild or preserve channels below a number (so manual/lower channels and their custom images survive). Accepts JSONL or bare-array LLM output and normalizes to the internal `{"channels":[...]}` dict.
- **`export.py`** — pulls full metadata from the Plex API. Includes **studio** + top-3 billed **actors** (both in the default `/all` response) which power the Planner's entity channels. Auto-detects all movie+TV sections (or scope with `--movie-sections`/`--tv-sections`); cross-references Tunarr to flag unsynced content. Output: `plex_library.csv` + `export_summary.json`.
- **`generate_no_ai.py`** — builds a starter `channels.json` from CSV metadata (decade + genre movie channels, 50+ episode TV marathons; placeholders for franchise/specialty). Numbers channels sequentially using `channel_blocks.assign_numbers` + `channel_blocks.resolve_order`; `--order KEY,KEY,…` overrides category order; `--start N` sets the first number.
- **`channel_blocks.py`** — shared, **pure, importable** channel-numbering logic (no `config.json`/argv). `assign_numbers(order, counts, start)` packs categories tight sequentially; `resolve_order(configured)` validates/fills the configured order against `CANONICAL_ORDER`. Single source of truth for compose, the LLM prompt, and `generate_no_ai`. **Must stay in the Dockerfile `COPY` line.**
- **`generate_from_collections.py`** — one channel per Plex collection via `{"collection":"Name"}`. Manages the collection block (default ch 80+): keeps everything below `--base`, regenerates from `--base` up. Re-run any time Kometa changes collections.
- **`channel_engine.py`** — shared, **pure, importable** resolution engine (no `config.json`/argv/`sys.exit`), so it's safe to import into the long-lived FastAPI process. Holds the resolution helpers, franchise `match_titles` (word-boundary), and the in-place live-channel updaters (`read_channel_programming`, `update_channel_in_place`). Imported by `create.py` at runtime and in-process by `recipes_router.py` — **must stay in the Dockerfile `COPY` line**.
- **`create.py`** — thin CLI wrapper around `channel_engine`. Reads `channels.json`, indexes the Tunarr library (case-insensitive exact title match), and deploys (delete-then-create; `--from N` scopes, `--protect N1,N2` preserves specific channels). Builds 30-day rolling random schedules (no dead air). The delete/recreate path is **initial-deploy only** — never for live channels.
- **`fetch_images.py`** — for solo-title channels, finds the best TMDB clearlogo and sets the Tunarr channel `icon.path` so Plex shows a real logo in the guide. Multi-title channels are skipped. Dry-run by default; `--apply` to commit. Requires `tmdb_api_key`.
- **`sync_plex.py`** — reconciles Tunarr's XMLTV channel list into Plex's DVR mapping (read-then-update; **never deletes** the DVR). Falls back to printing the XMLTV URL + manual steps.

## Channel Numbering Scheme

Channels are numbered **sequentially from 1, tight-packed in category order** — no fixed block
sizes, no gaps. 15 marathons → channels 1–15; next category starts at 16. Empty categories
consume no numbers. The only configurable knob is **the order of categories**, stored as
`channel_order` (list of category keys) in `config.json`.

Canonical category order and labels are defined in `channel_blocks.py` (`CANONICAL_ORDER`,
`BLOCK_LABELS`). The full set (in default order):

| Category key | Label | Content |
|---|---|---|
| `marathon` | TV Marathons | 24/7 single-show loops (50+ episodes) |
| `tv_block` | TV Blocks | Themed multi-show rotations |
| `tv_movie_mix` | TV & Movie Mix | Mixed-genre channels spanning shows + films |
| `movie` | Movie Channels | Genre and decade channels |
| `entity` | Studios / Directors / Actors | Curated by creator or studio |
| `network` | Networks | All shows from a single network |
| `programming_block` | Classic TV Blocks | Historical lineups (TGIF, Must See TV…) |
| `franchise` | Franchise & Series | Ordered collections (MCU, Star Wars, etc.) |
| `specialty` | Specialty | Single-movie loops, holiday, niche themes |

**`channel_order` is configurable** via Settings → Channel Numbering (drag up/down) or directly
in `config.json`. An absent or empty `channel_order` key falls back to the canonical order.
Old configs with `channel_blocks` (sizes) are silently ignored — no crash.

**Fresh deploys** start at channel 1; keeping existing channels rounds the start up above the
highest kept one. All three generators (`/pipeline/compose`, the LLM prompt, `generate_no_ai`)
call `channel_blocks.resolve_order` + `channel_blocks.assign_numbers` — single source of truth.

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

Content items can be plain title strings **or** Plex collection references
(`{"collection": "Name"}`), freely mixed. Collection refs are expanded to member titles at
deploy time via the Plex API; a not-found collection is warned and skipped. Plain titles must
match Plex names exactly (case-insensitive). A title may appear on multiple channels —
intentional. Live channels add one more content-ref type (`{"match": "title_contains", …}`),
documented under Live Channels.

**Write-only-on-deploy invariant.** `channels.json` is the record of **deployed channels**
and must stay in sync with Tunarr. Two rules:

1. **Planner-flow builders** (`compose`, `validate`, `discover-prompt`, `apply_collections`)
   read/write **`channels.draft.json`** only — never the deployed record. Abandoning a creation
   can at worst leave a stale draft.
2. **`channels.json` is written in exactly two ways:**
   - `deploy-selective` (`pipeline_router.py`: `_reconcile_channels_json`) — on a successful
     `create.py` exit, writes the deployed set (wipe mode) or merges kept + deployed (keep mode),
     then clears `channels.draft.json` and `deploy_temp.json`.
   - `POST /api/channels/{number}/apply` — saves one entry and immediately patches Tunarr in
     place; they are always written together.

Channels in Tunarr without a `channels.json` entry are "orphans" — visible on the Channels
page as read-only ("Not managed by Programmarr"). We deliberately do not reconstruct intent
(shuffle/live/franchise rules) from a deployed lineup.

**Commercials (optional).** A channel may carry
`"commercials": {"filler_list_id": "…", "filler_list_name": "…", "pad_minutes": 5}`. At deploy,
`create.py` attaches that Tunarr filler list to the channel (`fillerCollections`) and pads each
show up to the next `pad_minutes` boundary (`build_schedule(pad_ms=…)`), opening a gap that
Tunarr's FillerPicker fills with the clips **between shows** at playback. Absent = off. Applies to
**every** channel type (TV and movie) — density self-adjusts since the gap is per-program (a break
between movies vs. between episodes). The filler list itself is created/managed in Tunarr; the
picker is fed by `GET /api/tunarr/filler-lists`. The field is **per-channel by design**: the
Planner toggle is a blanket convenience that writes the same list onto every channel in a batch,
but each channel can point at a different filler list (the Channels editor already allows this) —
the basis for future era-matched pooling (90s ads → 90s channel; see `docs/ideas.md`).
**Mid-roll (ads inside a show) is deliberately not used — it doesn't stream on hardware-accelerated
(QSV) Tunarr; see [`docs/tunarr-commercials-findings.md`](docs/tunarr-commercials-findings.md).**

## API Endpoints

All endpoint tables — **Pipeline**, **Recipe**, **Tunarr**, **TMDB**, **Plex** — live in
[`docs/api.md`](docs/api.md). The router source (`backend/routers/`) is the source of truth.

## Run.tsx — Pipeline Stepper UI

`frontend/src/pages/Run.tsx` is a **single unified stepper** (no tabs). The generation
method is a question on the first screen; the step list is built from the user's choices.

**Flow:** `Setup → Export → Planner → [AI Extras] → [Collections] → Deploy`. Export/Planner
are skipped for *Collections-only*; **AI Extras** appears only when the Planner's "✨ Bring in
AI" toggle is on; Collections only if opted in.

**Durable rules (these outlive any refactor of the step components):**
- **Channel protection is decided once, on the Setup screen** (keep/wipe the existing Tunarr
  lineup). Kept = protected; protected numbers pass to `create.py` via `--protect N1,N2,...`.
  The start number auto-computes as the highest kept rounded up to the next 10. Deploy does
  **not** re-ask protection — it only flags conflicts between kept numbers and deploy numbers.
- **The Planner is deterministic:** selected candidates post as `CandidateSpec[]` to
  `POST /pipeline/compose`, which writes `channels.draft.json` (the AI and collections steps
  append to the same draft; the Deploy step's probe and `deploy-selective` both read it).
  Candidates are unchecked by default.
- **The AI layer merges on top** via `POST /pipeline/validate` with `append=true` (collisions
  renumbered, name-duplicates skipped) — it never overwrites the deterministic lineup.
- **Deploy runs a cascade that always completes:** `deploy-selective` → (if art opted in)
  `images` → `sync`, each streamed inline, ending in a per-stage summary.
- **The Planner body is a three-section accordion** (`AccordionSection` component, single-open
  at a time, `openSection` index state, Section 0 open initially):
  - **Section 0 — TV:** Marathons + Genre-blocks. Step 5 will insert Networks + Classic blocks.
  - **Section 1 — Movies:** genre×decade, sub-genres, broad genres, Studios/Directors/Actors.
  - **Section 2 — TV + Movies:** mixed-genre candidates from `tv_movie_genres` facet (genres
    present in both libraries above `TV_MOVIE_MIX_MIN`). Step 6 will insert Franchises.
  Each section header opens/closes it (collapsing the other). A "Done — continue" footer
  button collapses the current and opens the next. The genres/decades chips and toggle cards
  (AI/commercials/auto-update) sit above the sections; the build bar sits below.

The blow-by-blow of each step's components and props is the code's job — read the `.tsx`.

## Known Limitations

**Plex guide shows channel icons, not text names.** When Plex receives a channel with any icon
in the XMLTV feed, it renders only the icon and suppresses the text label — a Plex design
decision, not a Programmarr bug. Tunarr injects a default icon for every channel, so without
custom icons the guide is a wall of identical icons. `fetch_images.py` gives solo-title channels
real TMDB logos; multi-title channels still show the Tunarr default until a logo strategy exists
for them. Refreshing/restarting Plex does not change this.

## Git Workflow

`master` is **production**: every push triggers CI → GHCR → Watchtower → live redeploy within
~5 min. So master is **release-gated** — it receives only tagged, versioned releases, never raw
dev work. Two tracks keep that true:

1. **Branch track — daily work (`/ship`).** All image-affecting work (anything baked into the
   image: `backend/`, `frontend/`, root `*.py`, `Dockerfile`, `docker-compose.yml`,
   `requirements*.txt`) happens on a short-lived `feature/…`/`fix/…`/`chore/…` branch. `/ship`
   commits and pushes to that branch — **never master**. Branches don't deploy.
2. **Release track — going live (`/release`).** The single gate to master: Docker-verifies, asks
   for the new semantic version, bumps `frontend/package.json` + `CHANGELOG.md`, merges the
   branch, tags `vX.Y.Z`, and cuts the GitHub Release (firing the versioned GHCR build).

**SemVer:** patch = fixes/tweaks; minor = new features/UI/flags/endpoints; major = breaking
pipeline/schema/API changes. `/release` suggests the bump and always asks you to confirm.

**The one carve-out — docs straight to master.** Doc-/comment-/repo-meta-only changes (`*.md`,
`docs/`, `.gitignore`, `README`) build an identical image (Watchtower never redeploys them), so
they may go straight to master with no branch and no version bump.

**Always:** commit in small focused chunks with verbose *what + why* messages; **never commit
secrets or personal data** (keys, passwords, IPs, the user's library — kept gitignored:
`config*.json`, `channels*.json`, `*.csv`, `PROMPT.personal.md`); and **keep this file in sync in
the same commit** as any behavior change.

## Live Channels (Auto-Updating Channels)

A **live channel** (`"live": true` in `channels.json`) is re-resolved against the Tunarr library
on a schedule and patched **in place**, so it stays fresh as the library grows. Ships **off** by
default (`recipes_enabled: false`).

**Two rules that must never be broken:**
1. **Update in place.** Look the channel up by number and `set_programming` on the existing
   Tunarr id. **Never** delete-and-recreate a live channel — that changes the Tunarr id and
   breaks the Plex DVR mapping. (`create.py`'s delete/recreate path is for *initial* deploy
   only; the scheduler must never use it.)
2. **Tunarr is the source of truth.** Each cycle diffs freshly-resolved program ids against the
   channel's *current* Tunarr programming and patches **only on a difference**. No state file
   drives correctness — `data/recipe_state.json` is cosmetic UI-only metadata (last-synced
   badges), never read by the diff.

**Franchise content-ref** — the one new item allowed in a channel's `content` list:
```json
{"match": "title_contains", "value": "Bad Boys", "order": "release_date", "exclude": []}
```
Word-boundary match (so "It" does not match "Little Women"); `order: "release_date"` sorts by the
Tunarr program's `releaseDate`; `exclude` drops false positives. Author-time preview
(`POST /api/recipes/preview`) requires human confirmation before saving — the LLM never auto-authors these.

**Moving parts** (scheduler loop, `channel_engine` updaters, `recipes_router`, the `Channels.tsx`
authoring UI and status cards), full rationale, rejected alternatives, and history:
[`docs/live-channels-design.md`](docs/live-channels-design.md).
