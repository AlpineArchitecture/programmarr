# Changelog

All notable changes to Programmarr are documented here. This project follows
[Semantic Versioning](https://semver.org/) and the spirit of
[Keep a Changelog](https://keepachangelog.com/).

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

[0.2.2]: https://github.com/AlpineArchitecture/programmarr/releases/tag/v0.2.2
[0.2.1]: https://github.com/AlpineArchitecture/programmarr/releases/tag/v0.2.1
[0.2.0]: https://github.com/AlpineArchitecture/programmarr/releases/tag/v0.2.0
