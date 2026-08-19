# spec-followups.md — post-review change list

Changes to make on `feature/planner-overhaul` after the first review pass of the
6-step planner overhaul (see `spec.md`). Build these the same way: stacked commits
on the branch, tests + frontend build green, served on :7979, never merged to master.

---

## F1 — Eager franchise scan + progress bar

**Why:** the first TMDB franchise scan takes a while (per-movie search+details over the
whole library, ~minutes on a ~1k-movie library). Today it's lazy-loaded when the
TV+Movies section first opens, behind a plain spinner — so it feels like it stalls.

**Change:**
- **Start the franchise discovery eagerly when the Planner page loads** (on `PlannerStep`
  mount), so the scan runs in the background while the user works through the TV and
  Movies sections.
- **When the user reaches the franchise spot (TV+Movies section):**
  - if the scan is still running, show a **progress bar** (e.g. "scanned X / Y movies"),
    not a blank spinner;
  - if it's finished, show the franchise results immediately.
- Plex-source franchises (fast) can be shown as soon as they're ready, with the TMDB
  ones filling in as the scan completes.

**Implications (for the builder):**
- The current `GET /pipeline/franchises` is synchronous/blocking. To show progress, make
  discovery a **background job with a pollable progress endpoint** (or SSE): kick off the
  scan, return a job/status the frontend can poll for `{done, scanned, total, franchises}`.
  Cache the final result exactly as today (`franchise_cache.json`, library-signature keyed)
  so a completed scan is still instant on later loads.
- Optional speed-up (not required, but would make the bar finish faster and stay within
  TMDB limits): run the per-movie TMDB lookups with bounded concurrency instead of serial.

---

## F2 — ✅ FIXED: surgical deploy uses draft numbers for existing channels (breaks updates + record)

> Resolved on `feature/planner-overhaul`: update target + `channels.json` write now use the
> deployed number for existing channels via `channel_engine.merge_deployed_numbers` (pure +
> unit-tested). The corrupted `channels.json` was repaired to match Tunarr (backup at
> `data/channels.json.bak`). **The user must re-run the Add/Edit deploy** to actually apply the
> content edits that silently failed. Details below for the record.

**Symptom (found in a real :7979 Add/Edit run):** after a surgical deploy, `channels.json`
recorded 17 existing channels at new high numbers (61–92) while Tunarr still had them at their
original numbers (1–49). Every channel matched by NAME across both — so nothing was created/
deleted/destroyed — but the numbers desynced AND the in-place content updates silently failed.

**Root cause:** In Add/Edit mode, `compose` renumbers the whole selection from `start =
highest existing + 1`, so already-deployed channels get NEW high numbers in the draft.
`classify_channels` matches them by name into `update`/`unchanged`, but:
1. The update target uses the DRAFT number:
   `num = desired_ch.get("number") or item["deployed"].get("number")` → picks the draft's #61,
   so `update_channel_in_place(tunarr_url, 61, …)` → `find_channel_by_number(61)` returns None →
   `ChannelEngineError("Channel #61 not found")`. The real channel (#1) is never updated.
2. The `channels.json` write does `new_managed = list(desired)` — recording draft numbers for
   `update` AND `unchanged` channels, which don't match Tunarr.

**Fix:**
- For `update` channels, target the **deployed** number/id, not the draft:
  `num = item["deployed"].get("number")` (the real Tunarr channel). 
- When writing `channels.json`, any channel matched to a deployed channel (update OR unchanged)
  must keep its **deployed** number; only genuine `create` channels use their draft number.
  Build `deployed_num_by_name` from `deployed` and remap each desired channel:
  `num = deployed_num_by_name.get(name, ch["number"])`.
- Consider sourcing actual numbers/ids from **Tunarr** (the documented source of truth) at execute
  time rather than trusting channels.json numbers, so a stale record can't mis-target an update.
- Add a test: an existing (re-selected) channel keeps its deployed number after a surgical
  deploy, and update-in-place targets the deployed number, not the draft number.

**One-time recovery for the current corrupted state:** repair `data/channels.json` by remapping
each channel's number to its actual Tunarr number (match by name), so the record realigns with
reality. The user's content edits to the 17 channels did NOT apply and must be re-deployed after
the code fix.

## F3 — ✅ FIXED: dev loop: `uvicorn --reload` breaks export on Windows

> Resolved: `dev.ps1` now reloads the backend at the PROCESS level via `watchfiles`
> (`python -m watchfiles "python -m uvicorn main:app …" backend`) instead of `uvicorn --reload`.
> Each restart is a fresh process where main.py's WindowsProactorEventLoopPolicy stands, so
> `create_subprocess_exec` works AND you still get ~1s reload-on-save. Validated booting on a
> throwaway port. Verified the fix premise: a Proactor loop spawns subprocesses fine; uvicorn's
> `--reload` was forcing the Selector loop. **Restart your dev loop once with the updated dev.ps1.**

**Symptom (was recurring):** Export (and every pipeline subprocess step) failed in the local dev
loop with `NotImplementedError` from `asyncio.create_subprocess_exec`.

**Root cause:** `create_subprocess_exec` needs the Windows **ProactorEventLoop**. `main.py`
sets `WindowsProactorEventLoopPolicy`, but **uvicorn overrides it in subprocess mode**
(`--reload`/`--workers`) by forcing `WindowsSelectorEventLoopPolicy`. The Selector loop can't
spawn subprocesses. No-op on Docker/Linux.

**`dev.ps1` uses `--reload`**, so the documented fast loop hits this every time.

**Action options (pick one):**
- Drop `--reload` from `dev.ps1`'s backend command (simplest; manual restart on backend edits).
- Or document the gotcha prominently in CLAUDE.md "Local Development" + a one-line note in
  `dev.ps1` so it doesn't keep surprising us.
- Or add a small reload-worker wrapper that re-asserts the Proactor policy (more work).

(Also captured in memory: `reference_dev_reload_breaks_export`.)

---

# Round 2 — revision batch (F4–F13)  ✅ ALL DONE (awaiting human review)

> All ten steps built, self-reviewed (pytest + build + diff), and committed on
> `feature/planner-overhaul` (commits ddcff4a → 3f773de). 219 tests pass; frontend builds clean.
> Architect caught + fixed during review: F7 early-return save guard; F10 stale-closure that
> would clobber sticky picks; F13 SPARQL double-bind that would have made every Wikidata batch
> fail. Pending: human review on dev.ps1 loop, then `/release`.

Same workflow as the original 6-step build: each step is a stacked commit on
`feature/planner-overhaul`, `pytest` + `cd frontend && npm run build` green, CLAUDE.md kept in
sync, NO background dev servers left running (verify with tests/build only; the human reviews on
their own dev.ps1 loop). Build in order; the architect reviews after each before the next.

**Decisions (locked with the user):** add 4 data sources (TVmaze networks, TMDB keywords, Plex
Mood/Style/Country, Wikidata franchises); franchises = TMDB+Wikidata DETECTED only (Plex
collections stay in the separate Collections feature); planner picks = ALWAYS sticky; planner
categories all-open with per-category Done-collapse (Top-10/Add-all never collapse); deploy shows
a diff preview + Confirm; Settings reorder via @hello-pangea/dnd; themed channels from a curated
TMDB-keyword catalog. (F1's eager-scan+progress is rolled into F9.)

---

## F4 — Dashboard: open-in-new-window for Tunarr & Plex

**Files:** `frontend/src/pages/Dashboard.tsx` (`ConnectionCard`), maybe `config_router`/`status`
for the URLs (the dashboard already knows tunarr_url/plex_url via config status — reuse).
**Change:** on the Tunarr and Plex connection cards, add a small external-link icon button
(`IconExternalLink`) that opens the configured `tunarr_url` / `plex_url` in a new tab
(`window.open(url, '_blank', 'noopener')` or an `<a target="_blank" rel="noreferrer">`). Only show
it when the URL is configured. **Acceptance:** clicking opens the right service in a new tab.

## F5 — Planner categories: all-open + per-category Done-collapse; Top-10 no longer collapses

**Files:** `frontend/src/pages/Run.tsx` (`CollapsibleSection`, `BulkButtons`, `PlannerStep`).
**Changes:**
- When a section (TV/Movies/TV+Movies) is open, its category groups (`CollapsibleSection`s) all
  start **expanded**. Each shows a **Done** control (button) that collapses it to its header
  summary (the existing "N picked" badge). Re-openable by clicking the header.
- **`BulkButtons` (Top 10 / Add all) must NOT collapse** the category — remove the `onAfter` /
  `setOpen(false)` behavior so bulk-add only adds items.
- Manage each category's open/closed state (a per-category map keyed by category id, defaulting to
  open) so Done collapses just that one.
**Acceptance:** opening TV shows Marathons/Genre-blocks/etc. expanded; Top-10 adds without
collapsing; Done collapses that category to its summary; others unaffected.

## F6 — Settings: drag-and-drop category reorder (@hello-pangea/dnd)

**Files:** `frontend/package.json` (add `@hello-pangea/dnd`), `frontend/src/pages/Settings.tsx`
(`CategoryOrderEditor`).
**Change:** replace the up/down arrow reorder with a `@hello-pangea/dnd` vertical sortable list
(DragDropContext/Droppable/Draggable) with a drag handle per row. On drop, persist the new
`channel_order` via `api.saveConfig` (same as today). Keep the human labels + explainer.
**Acceptance:** `npm install` adds the dep, drag-reorder works smoothly, order persists. Build clean.

## F7 — Planner picks ALWAYS sticky (fixes #11 + #12)

**Files:** `frontend/src/pages/Run.tsx` (planner load effect ~781, `build()` save ~936, `patch`,
`handleNuke` ~1868, SetupStep). Backend planner-state endpoints already exist.
**Changes:**
- **Save on every change:** persist the full planner intent (activeGenres, activeDecades,
  selected, curate, aiExtras, commEnabled, commListId, commPad, autoUpdate) to
  `planner_state.json` whenever it changes — add a debounced (~500ms) effect in `PlannerStep`
  that PUTs on change, instead of only saving inside `build()`. (Keep a save on build too.)
- **Restore always:** remove the `isEdit` gate in the load effect — load `planner_state.json` and
  restore picks on Planner mount in BOTH modes. (Mode only affects deploy behavior, not picks.)
- **Nuke keeps picks:** `handleNuke` must NOT delete `planner_state.json` and must NOT blank the
  planner — Nuke only means "wipe Tunarr + renumber from 1" at deploy. Remove the
  `deletePlannerState`/`blankPlanner` calls from the nuke path.
- **Add an explicit "Clear all" button** in the Planner build bar that clears `selected`/`curate`
  (and active toggles) AND calls `deletePlannerState`. This is the only reset.
- Ensure the backend `managed_names` writes still merge (`{**planner_state, ...}`) and never
  clobber the picks.
**Acceptance:** open Planner → last picks already checked (any mode); remove 2 + Top-10 again →
the 2 come back and deploy re-creates them; Nuke → picks remain; Clear all → blank + file removed.
Add a frontend-logic note to CLAUDE.md's Run.tsx durable rules.

## F8 — Deploy: diff preview + Confirm (both modes)

**Files:** `backend/routers/pipeline_router.py` (new preview endpoint using
`channel_engine.classify_channels`), `frontend/src/pages/Run.tsx` (DeployStep),
`frontend/src/api/client.ts`.
**Changes:**
- New `POST /pipeline/deploy-preview` (no Tunarr writes): reads `channels.draft.json` (desired),
  `channels.json` (deployed), `planner_state.managed_names` (prior_managed), runs
  `classify_channels`, and returns the buckets as named lists: `create`, `update`, `delete`,
  `unchanged`, `foreign`. For **nuke** mode, return a wipe-preview (all draft = create; all current
  managed = will be removed/recreated) — keep it honest about what nuke does.
- DeployStep: before running, fetch the preview and render it — `+ N new`, `~ N changed (in place)`,
  `− N removed`, `= N unchanged (left alone)`, `· N not managed (untouched)` with the channel
  names. A **Confirm deploy** button then runs the existing surgical-deploy (edit) or
  deploy-selective (nuke) cascade. A Cancel backs out.
**Acceptance:** deploying shows the named diff first; Confirm runs it; the numbers match what
actually happens. Cover the preview endpoint with a test.

## F9 — Franchise rework: detected-only + parallel + eager scan + progress (rolls in F1)

**Files:** `backend/routers/pipeline_router.py` (`get_franchises` → background scan),
`frontend/src/pages/Run.tsx` (franchise section), `client.ts`.
**Changes:**
- **Remove the Plex-collections source** from franchise discovery (decision: franchises are
  detected, collections are separate). Source is **TMDB** now (Wikidata added in F13).
- **Shared TMDB enrichment cache:** fetch each library movie's TMDB details with
  `append_to_response=keywords` in ONE call per movie (gets `belongs_to_collection` AND `keywords`
  together) → cache to `data/tmdb_enrichment.json` keyed by library signature. F11 reads keywords
  from this same cache (don't scan TMDB twice). Run the per-movie calls with **bounded concurrency**
  (ThreadPoolExecutor, ~10–15 workers) — this is the speed fix.
- **Background scan + progress:** `POST /pipeline/tmdb-scan` starts/refreshes the enrichment scan
  (returns immediately); `GET /pipeline/tmdb-scan/status` returns `{running, scanned, total,
  done}`. `GET /pipeline/franchises` returns franchises from the cache (fast). Frontend: kick the
  scan on **Planner mount** (eager, not on section-open), and in the TV+Movies → Franchises group
  show a **progress bar** ("scanned X / Y") while running, franchises filling in when done. No
  tmdb_api_key → franchises empty (until F13 Wikidata), no scan.
**Acceptance:** franchise scan starts on Planner load, runs in parallel, shows progress; franchises
exclude Plex collections; cache reused; no double TMDB scan with themes.

## F10 — Networks via TVmaze (replace Studio; drop the search)

**Files:** `backend/routers/pipeline_router.py` (networks facet + TVmaze scan), `export.py` or a
new scan endpoint, `frontend/src/pages/Run.tsx`, `client.ts`.
**Changes:**
- Source the network per TV show from **TVmaze** (free, no key): `GET https://api.tvmaze.com/singlesearch/shows?q=<title>`
  → `network.name` or `webChannel.name`. Per-show lookup with bounded concurrency, cached to
  `data/tvmaze_cache.json` keyed by library signature (same background-scan + progress pattern as
  F9; can share the scan infra). Be defensive (failures skip the show).
- **Replace** the Studio-based `networks` facet with the TVmaze network → count grouping.
- Frontend Networks group: render as a plain `CollapsibleSection` list (NOT `EntitySection`) so
  **the search box is gone**. compose `network` kind resolves TV shows whose TVmaze network matches.
**Acceptance:** Networks shows real networks (HBO/NBC/Apple TV+ etc.) from TVmaze, no search box;
building a network channel includes the right shows.

## F11 — TMDB-keyword themed channels (curated catalog; reuses F9 cache)

**Files:** new `themed_keywords.json` (repo root + Dockerfile COPY), `backend/routers/pipeline_router.py`
(themes facet from the F9 enrichment cache), `frontend/src/pages/Run.tsx` (Movies or TV+Movies
section), `client.ts`.
**Changes:**
- Ship `themed_keywords.json`: ~25–40 curated themes → TMDB keyword id(s)
  (Heist, Time Travel, Zombie, Christmas, Dystopian, Road Trip, Whodunit, Coming-of-Age, Vampire,
  Post-Apocalyptic, Superhero, Spy, …). Verify the keyword ids against TMDB.
- Compute a `themes` facet from the **F9 `tmdb_enrichment.json` keywords** (no new scan): per theme,
  count library movies whose keywords include the theme's id(s); offer themes clearing a threshold.
- compose kind `theme`: resolve the library titles tagged with the theme's keyword id(s) (carry the
  resolved titles in the spec like `programming_block`/`franchise`). Add to a "Themed" group.
**Acceptance:** Themed channels appear (Heist Films, Time Travel, …) from the shared cache; building
one yields the right titles; no extra TMDB scan beyond F9.

## F12 — Plex Mood/Style/Country facets

**Files:** `export.py` (new columns), `backend/routers/pipeline_router.py` (facets + compose),
`frontend/src/pages/Run.tsx`, `client.ts`, `backend/tests/conftest.py` (seed columns).
**Changes:**
- `export.py`: pull `Mood`, `Style`, `Country` tags from the Plex item metadata (already in the
  `/all` detail or via the item's `Genre`/`Mood`/`Style`/`Country` arrays) and add CSV columns.
- `library_facets`: add `countries`, `moods`, `styles` counts (above a floor, capped). Add compose
  kinds (`country`, `mood`, `style`) resolving movies by the matching tag. Surface as groups in the
  Movies section ("Countries", "Moods/Vibes").
**Acceptance:** new facets appear when the data exists; building a Country/Mood channel yields the
right titles; export adds the columns; old CSVs without the columns don't crash (treat as empty).

## F13 — Wikidata franchise enrichment

**Files:** `backend/routers/pipeline_router.py` (add Wikidata source to franchise discovery),
tests.
**Changes:**
- Add **Wikidata** as a second franchise source (merged with TMDB from F9). Use the SPARQL endpoint
  to find "part of the series" / franchise membership that spans TV+film for titles in the library
  (match cautiously by label+year). Merge + de-dupe by normalized name into the franchise list;
  cache with the enrichment. Defensive: Wikidata failures never 500 — TMDB-only results still
  return. Lower certainty — keep matching conservative to avoid false members.
**Acceptance:** cross-media franchises (e.g. Star Trek series + films) can appear; TMDB-only still
works if Wikidata is unreachable; no false-positive members from loose matches.

<!-- Append further review follow-ups below (one ## section each). -->
