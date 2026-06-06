# Changelog

All notable changes to Programmarr are documented here. This project follows
[Semantic Versioning](https://semver.org/) and the spirit of
[Keep a Changelog](https://keepachangelog.com/).

## [0.3.1] — 2026-06-05

### Fixed

- **Multi-library exports no longer silently drop content.** Two related bugs in
  `export.py` where content vanished from `plex_library.csv` without any error:
  - **Tunarr cross-reference checked only the first library of each type.** With more
    than one enabled Tunarr movie (or TV) library — e.g. a main "Movies HD" plus a
    "Crossovers HD" — only the first was loaded, so everything in the rest failed the
    cross-ref check and was skipped. It now unions **all** enabled libraries of each
    type, and prints per-library counts plus a combined total.
  - **CLI auto-detect picked only the first Plex section of each type.** Running
    `export.py` without `--movie-sections`/`--tv-sections` and with multiple Plex
    libraries (e.g. "TV Shows" + "Cartoons") silently ignored the extras. Auto-detect
    now collects **every** matching section. The explicit `--*-sections` flags and the
    UI (which always passes keys) were unaffected.

  No CSV schema or downstream changes — a single-library export is byte-identical.

## [0.3.0] — 2026-06-05

### The Planner — a ground-up rebuild of how you create channels

The biggest release since the web app shipped. The old three-tab Run pipeline
(AI / No-AI / Collections) is **gone**, replaced by a single unified **Planner**
that composes curated, hand-programmed-feeling channels from your library —
**deterministically** — with AI demoted from "the engine" to an optional layer on
top. The result feels like a TV lineup a person with taste assembled, not a wall
of `Comedy Movies (140)` blocks.

### Added

- **The Planner: ingredients → curated candidates.** Pick which genres and decades
  are "in play," then check the exact channels you want from a live, **counted**
  candidate list. Everything is built by precise filters — no AI required, no
  guesswork:
  - **Per-show TV Marathons** — one 24/7 channel per show; every show in your
    library is offered, sorted by episode count.
  - **TV genre Blocks** — themed multi-show channels (Comedy TV, Crime TV…).
  - **Genre × Decade** — tight era cuts like "90s Comedy" and "80s Horror," nested
    under each decade.
  - **Named Sub-genres** — a curated, recognizable set (Rom-Coms, Dark Comedies,
    Horror Comedies, Crime Thrillers…) instead of arbitrary genre pairs.
  - **Studio / Director / Actor channels** — A24, "Directed by Tarantino," "Adam
    Sandler Movies" — the most curated-TV channels there are.
  - **Bulk picking** — "Top 10" and "Add all" on every section, and sections that
    fold away once handled so the list never becomes a wall of checkboxes.
- **Optional AI layer (✨ Bring in AI).** Two things filters can't do, both seeded
  with your built lineup and **merged on top** via a copy-prompt / paste-back
  hand-off:
  - **Discovery** — the AI suggests themed channels your filters miss (Heist Films,
    Courtroom Dramas, Time Travel, Sports Underdogs…), and is told what you already
    have so it never duplicates it.
  - **Tonal curation** — flag a broad pool (a ✨ on any genre or decade pick) and
    the AI splits it by *tone* (Feel-Good vs Raunchy vs Dark Comedies) — the "one
    comedy doesn't blend into the next" fix that genre tags alone can't make.
- **New library metadata for entity channels.** `export.py` now captures **Studio**
  and the top-3 billed **actors** per title (both already present in Plex's
  response), so studio/director/actor channels work out of the box.
- **Facets API.** One pass over your library powers the entire candidate list with
  live counts — genres, decades, the genre×decade matrix, sub-genre blends, and
  the studio/director/actor/marathon lists.

### Changed

- **One unified flow:** Setup → Export → Planner → [AI Extras] → [Collections] →
  Deploy. The generation "method" is no longer three separate tabs; it's a single
  Planner, with **Collections-only** kept as a quick path.
- **Every decision is up front.** Keep-vs-wipe of existing channels, whether to add
  collections, and whether to fetch art are all answered on the first screen — the
  rest of the flow is review-and-go.
- **Deploy is one cascade.** It auto-probes on entry, you review/renumber, hit
  **Deploy** once, and channel art + Plex sync run automatically — with an
  always-completes status summary.
- **Soft-block channel numbering.** Marathons ~10s, TV blocks ~20s, movie channels
  ~30s+, entity channels ~50s+ — assigned sequentially and spilling gracefully
  instead of overflowing fixed 20-slot blocks.
- **Clearer AI hand-off.** The walkthrough now spells out "paste the JSON only,"
  and the prompt is generated from your exact picks.

### Fixed

- **Merge dedup.** Pasting AI suggestions skips any channel whose name already
  exists, so re-running the AI step can no longer stack duplicate channels.
- **Collections numbering.** Collections now append *above* your composed lineup
  rather than at a fixed ~80 block, so they never overwrite the channels you just
  built.
- **Prominent Plex-sync fallback.** When Plex can't auto-add the DVR (common in
  many setups), the end-of-run summary now shows exactly what to do — with a
  one-click-copy XMLTV URL — instead of a quiet status line.

### Notes

- The deterministic Planner is a strict superset of the old No-AI path. The
  standalone scripts (`generate_no_ai.py`, `generate_from_collections.py`) and the
  `programmarr.py` CLI remain for power users.
- Live Channels (v0.2.x) is unchanged and fully compatible — channels built in the
  Planner can still be marked "live" to auto-update as your library grows.

## [0.2.3] — 2026-06-04

Follow-up to the Live Channels release: per-channel visibility and control that the
original plan called for but v0.2.2 only partly delivered.

### Added

- **Per-channel "last synced" badge.** Each live channel row on the Channels page
  shows when it was last checked ("synced 2h ago" / "never"). Backed by a new
  cosmetic `data/recipe_state.json` — written by the scheduler, read by the UI. It
  is **not** correctness state (the change-detection diff still reads live Tunarr);
  it lives in its own file so it never races with `channels.json` edits or deploys.
- **Per-channel "Save & Sync now".** The channel editor (for live channels) gains a
  button that saves the channel and immediately runs a scheduler cycle scoped to
  just that channel (`/api/recipes/run?only=N`), applying the recipe to Tunarr in
  place without leaving the editor.
- **"Next run" on the Dashboard.** The Auto-Updates card now shows when the next
  automatic check will run (e.g. "next ~in 11h"), alongside the last check.

### Changed

- `/api/recipes/status` now returns `next_run_seconds` and a per-channel `channels`
  map. The scheduler's last-run timestamp moved to wall-clock time so the status
  endpoint can compute the next run without touching the event loop.

### Notes

- Documentation reconciled against the full original plan: source/target
  agnosticism (Jellyfin source, ErsatzTV target) is captured as an explicit
  **future** goal with the in-place-update contract noted, but intentionally not
  built yet — there's no second source/target to validate an adapter layer against.

## [0.2.2] — 2026-06-04

### Added — Live Channels (auto-updating channels)

The headline feature of this release. Channels can now be **self-maintaining**:
mark one "live" and Programmarr re-checks it against your library on a schedule
and patches it **in place** as the library grows — no redeploy, no manual edits.

- **Live toggle per channel.** In the channel editor, an "Auto-update on a
  schedule" switch marks a channel live. Live channels show an orange badge in
  the list. A channel without the flag behaves exactly as before.
- **Franchise auto-match.** A new content rule, `title_contains`, pulls in every
  library title matching a phrase (e.g. `Bad Boys` → all four films, in release
  order) and auto-adds new sequels as they appear. Matching is **word-boundary**,
  not raw substring, so `It` matches "It Follows" but never "Little Women". The
  editor shows a **live preview** of exactly what matches before you save, with
  per-title checkboxes to exclude false positives.
- **In-place updates — the critical guarantee.** Updates reuse the existing
  Tunarr channel via its id (same channel number, same internal id), so Plex's
  Live TV / HDHomeRun DVR mapping is never disturbed. Channels are **never**
  deleted and recreated for an update. Verified end-to-end: a live Batman channel
  grew from 162 to 254 programs with its channel id byte-for-byte unchanged.
- **Change-detection, not blind re-posting.** Each cycle diffs the freshly
  resolved program set against the channel's *current* Tunarr programming and
  patches only on a real difference. An unchanged channel is a cheap no-op —
  idempotent, with no needless Plex guide churn. There is no state file; Tunarr
  is the source of truth, so the scheduler survives container restarts for free.
- **Background scheduler.** A lightweight asyncio loop runs inside the existing
  FastAPI app (no extra process). It re-reads config every minute, so enabling,
  pausing, or changing the interval takes effect without a restart. Ships **off**.
- **Controls & visibility.**
  - *Settings → Live Channels*: master enable switch + check interval (hours).
  - *Dashboard → Auto-Updates* card: on/paused state, live count, last-cycle
    summary with per-channel changes, a **Pause/Resume** toggle, and a
    **"Check now"** button that runs a cycle on demand.
  - A rolling diff log is written to `data/logs/recipes.log`.
- **New API endpoints** (`/api/recipes/*`): `preview` (author-time match preview),
  `status`, `run` (`apply=false` for a safe dry run), `pause`, and `config`
  (merge-writes the enable flag + interval without clobbering connection settings).

### Changed

- **`create.py` refactor.** The Tunarr resolution logic (library indexing, title/
  collection/franchise resolution, schedule building, in-place programming
  updates) was extracted into a new, dependency-free, importable
  `channel_engine.py`. `create.py` is now a thin CLI wrapper around it, and the
  scheduler and preview endpoint share the exact same resolver. No behavior change
  to existing deploys.
- **Deploy/scheduler safety.** Manual deploys and the scheduler now share a lock
  so a deploy and an auto-update can never touch Tunarr at the same time.

### Fixed

- **Channel editor "bounce" on Save.** Saving a channel could re-open the modal
  instead of closing it (and fire the "saved" notification twice) because the
  list reload re-triggered the deep-link open. The deep-link logic is now guarded
  so a reload never re-opens a modal you just closed.

### Misc

- Added a favicon (orange broadcast icon matching the navbar logo).

## [0.2.1] — 2025

### Added

- **Channel protection** — choose which existing Tunarr channels to keep before a
  deploy; protected channels (and their custom logos) are preserved while the rest
  are rebuilt.
- **Channel offset** — set a starting channel number so new channels don't collide
  with ones you keep; auto-calculated from the highest protected channel.

## [0.2.0] — 2025

### Added

- **Library picker** on the Export step — choose which Plex libraries to scan, and
  mix multiple libraries of the same type.
- **Run pipeline UI rewrite** — a premium stepper with export stats, probe review,
  and selective deploy across the AI / No-AI / Collections paths.
- UI screenshots in the README.

## [0.1.x] — 2025

### Added

- Initial **web app**: FastAPI + React + Mantine, served as a single Docker
  container on port 7979, with a first-run onboarding wizard.
- AI / No-AI / Collections pipeline paths with live streamed terminal output.
- TMDB channel-logo fetching, Plex DVR sync, optional HTTP basic auth.
- Dark / light / auto theme switching.
- GitHub Actions CI publishing to GHCR; Watchtower auto-update support
  (including the `DOCKER_API_VERSION` fix for newer Docker engines).

[0.2.3]: https://github.com/AlpineArchitecture/programmarr/releases/tag/v0.2.3
[0.2.2]: https://github.com/AlpineArchitecture/programmarr/releases/tag/v0.2.2
[0.2.1]: https://github.com/AlpineArchitecture/programmarr/releases/tag/v0.2.1
[0.2.0]: https://github.com/AlpineArchitecture/programmarr/releases/tag/v0.2.0
