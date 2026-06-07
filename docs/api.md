# API Reference

Exhaustive endpoint and external-API tables, relocated out of `CLAUDE.md` (which
keeps only a pointer here). The **router source** is the real source of truth — if a
table here disagrees with the code, the code wins. Keep this in sync when endpoints
change; don't restate it back into `CLAUDE.md`.

## Pipeline API Endpoints (`backend/routers/pipeline_router.py`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/pipeline/libraries` | List Plex library sections filtered to `movie` and `show` types (`{key, title, type}`) |
| POST | `/api/pipeline/export` | SSE-stream `export.py`; JSON body `{"no_crossref": bool, "movie_sections": ["1","2"], "tv_sections": ["3"]}` — sections are Plex section keys; `null` = auto-detect, `[]` = skip that type |
| GET | `/api/pipeline/csv` | Download `plex_library.csv` |
| GET | `/api/pipeline/csv/info` | Stats: rows, movies, tv_shows, skipped counts, preview lines |
| GET | `/api/pipeline/facets` | **Facets v2** — one CSV pass returning everything the Planner candidate list needs: `genres:{canonical,more}` (canonical always present; `more` ≥ `min_items`), `decades`, `genre_decade` matrix (≥6), `blends` genre-pairs (≥6), entity lists `studios`(≥4)/`directors`(≥3)/`actors`(≥4, capped 60), `tv_genres`(≥3), `marathons` (every show with ≥2 episodes, `{title,episodes,seasons}` sorted desc — drives the per-show marathon candidates), plus `movies`/`tv_shows`/`marathon_count`. Thresholds are module constants in `pipeline_router.py`. |
| POST | `/api/pipeline/compose` | **Planner v2 deterministic resolver.** Body `ComposeRequest{specs:[CandidateSpec], start}`. Each `CandidateSpec{kind, …}` (`kind` ∈ genre / genre_decade / blend / studio / director / actor / tv_genre / marathon) is resolved against `plex_library.csv` into a title list; empties skipped + reported. Writes `channels.json` with **soft-block numbering** (marathons ~10s, TV blocks ~20s, movie channels ~30s+, entities ~50s+, sequential from `start`, spilling on overflow). Returns `{count, channels:[{number,name,items}], skipped}`. |
| GET | `/api/pipeline/prompt` | **Legacy** — fetch full `PROMPT.md` (meta header included) with `{TARGET}`, preferences, and `start` (block offset) injected; query params: `target`, `preferences`, `start`. |
| POST | `/api/pipeline/prompt` | Body `PromptOptions{target, preferences, start, include_genres, exclude_genres, include_decades, exclude_decades, include_types, exclude_types}`. Strips the meta header above the first `---` and injects a `## What To Build` section (must-include / never-create lists + an explicit invite to discover additional channels) before the numbering scheme. |
| POST | `/api/pipeline/validate` | Parse/validate LLM output (file upload or raw text), write `channels.json`. With form field `append=true`, **merges** the parsed channels on top of the existing `channels.json` — colliding numbers are bumped to the next free slot, and incoming channels whose **name already exists (case-insensitive) are skipped**; returns `added` + `skipped_dupes`. |
| POST | `/api/pipeline/discover-prompt` | Build the AI-extras prompt, seeded with the current `channels.json` lineup (so the AI avoids duplicates) and numbering new suggestions from `max+1`. Body `DiscoverOptions{discover, curate_pools}`: `discover` adds a "suggest additional themed channels" section; `curate_pools` adds a "split these pools by tone" section. Returns `{content, start, existing_count}`. |
| POST | `/api/pipeline/no-ai` | SSE-stream `generate_no_ai.py`; query params `start`, `genres`, `decades`, `types`, `min_items` passed through as the matching `--` flags |
| GET | `/api/pipeline/collections` | Fetch all Plex collections (id, name, count, section, summary, has_poster) |
| GET | `/api/pipeline/collections/{id}/poster` | Proxy Plex collection poster image |
| POST | `/api/pipeline/collections/apply` | Write selected collections into `channels.json` |
| POST | `/api/pipeline/probe` | SSE-stream `create.py --probe` |
| POST | `/api/pipeline/deploy` | SSE-stream `create.py`; query params: `protected` (comma-separated channel numbers to preserve), `no_delete` (bool) |
| POST | `/api/pipeline/deploy-selective` | JSON body `DeployRequest{selections, protected_numbers, no_delete}`; filters channels.json to selected entries, writes `deploy_temp.json`, SSE-streams `create.py --json deploy_temp.json [--protect N1,N2,...] [--no-delete]` |
| POST | `/api/pipeline/images` | SSE-stream `fetch_images.py --apply` |
| POST | `/api/pipeline/sync` | SSE-stream `sync_plex.py` |

## Recipe API Endpoints (`backend/routers/recipes_router.py`)

Live-channel endpoints. Unlike the pipeline router (which spawns scripts as subprocesses), this
router imports `channel_engine` **in-process** — it adds `PROGRAMMARR_SCRIPTS` to `sys.path` so the
engine module (which lives at `/app`, not `/app/backend`) is importable. This is the same wiring the
scheduler reuses.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/recipes/preview` | JSON body `{value, exclude?, order?}`; runs `match_titles` against the live Tunarr library and returns `{value, order, count, matches:[{title, year}]}` — the author-time confirm list for a `title_contains` franchise rule (word-boundary match, release-date ordered) |
| GET | `/api/recipes/status` | Scheduler state: `{enabled, paused, running, interval_hours, next_run_seconds, live_count, last_cycle, channels}`. `next_run_seconds` = seconds to next auto cycle (null if disabled/paused); `channels` = per-channel sync metadata from `recipe_state.json` |
| POST | `/api/recipes/run` | Run one cycle on demand. `apply=true` (default) patches; `apply=false` is a dry run (detect + log, no Tunarr writes). `only=<number>` scopes the cycle to one live channel. Same code path the background loop uses |
| POST | `/api/recipes/pause` | `paused=true\|false` — runtime kill switch; halts/resumes the loop without a restart |
| POST | `/api/recipes/config` | JSON body `{enabled, interval_hours}`; **merge-writes** config.json (`recipes_enabled`, `recipe_interval_hours`) so it never clobbers connection/auth keys. Returns the new status |

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
