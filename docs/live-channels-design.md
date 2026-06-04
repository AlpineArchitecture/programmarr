# Live Channels — Design & Rationale

> **What this is:** the full as-built design, reasoning, and history behind the
> Live Channels (auto-updating channels) feature. This is *reference-when-you-care*
> material — the "why," the paths considered and rejected, and the ideas captured
> but deliberately not built.
>
> For the short, operational summary an agent needs while working on the code, see
> the **Live Channels** section in [`../CLAUDE.md`](../CLAUDE.md). For user-facing
> behaviour, see [`../README.md`](../README.md).
>
> **Status:** shipped (v0.2.2+). Per-channel sync metadata, the per-channel
> "Sync now" button, and Dashboard "next run" were added in a follow-up (see
> "Per-channel sync state" below).

## Intent

Make channels self-maintaining. A user's library changes constantly — new
episodes drop weekly, a new franchise film appears once a year. Today channels
are static snapshots: resolution is frozen at deploy time, so they go stale.
A **live channel** is one whose existing `content` list is re-resolved against
the Tunarr library on a schedule and patched in place, with no user
intervention.

The user should be able to say "I want a Bad Boys channel" and never touch it
again: when Bad Boys 4 lands in the library (and Tunarr has synced it), it's in
the channel by the next cycle.

## Core Reframe — No "Recipe Types"

The original draft proposed two bespoke recipe types (`tv_loop`, `franchise`)
with their own refresh code paths. That is **not** the design. The codebase
already resolves content at deploy time (`create.py`): a show name expands to
*all episodes Tunarr currently has* (`create.py:118-130`), and
`{"collection":"Name"}` refs expand to their members. The only reason channels
go stale is that this resolution never re-runs.

So a live channel is simply `"live": true` plus the normal `content` list,
re-resolved on a schedule. The three "types" collapse into one mechanism:

- **TV loop (episode growth):** `content: ["The Simpsons"]` + `"live": true`.
  Re-resolving the show name picks up new episodes automatically. No special
  marker needed.
- **Collection growth:** `content: [{"collection":"…"}]` + `"live": true`.
  Re-expanding the collection picks up titles Kometa/Trakt added.
- **Franchise growth:** one new content-ref type (below), re-scanned each cycle.

Static title strings, collection refs, and match-refs compose freely in one
`content` list. Re-resolve grows the dynamic parts and preserves hand-picked
static entries.

## Data Source — Tunarr, Not Plex

Resolution runs against the **Tunarr library** (`build_library_index` →
`/api/media-libraries/{id}/programs`), exactly as `create.py` does today. Plex
is only queried to expand a collection *name* into titles, which are then matched
against Tunarr anyway.

Consequence — the freshness chain has a step outside our control: file appears
in Plex → **Tunarr re-syncs its own library** → our cycle can see it → channel
patched. UI copy must say "appears once Tunarr has synced," not literally "next
morning."

## Schema

A channel without `"live"` behaves exactly as today. No `recipe` object, no
`type` field, no per-channel interval.

```json
{
  "number": 55,
  "name": "Bad Boys",
  "shuffle": "ordered",
  "live": true,
  "content": [
    {"match": "title_contains", "value": "Bad Boys",
     "order": "release_date", "exclude": []}
  ]
}
```

```json
{
  "number": 12,
  "name": "The Simpsons",
  "shuffle": "ordered",
  "live": true,
  "content": ["The Simpsons"]
}
```

The match-ref (`title_contains`) is the one new content item type. `order`
applies to that ref's matched titles; `exclude` is a per-ref escape hatch for
false positives.

## Franchise Matcher Safety

`title_contains` is matched on **word boundaries**, not raw substring (so
`"It"` does not match *L**it**tle Women*). Even so, title strings cannot always
disambiguate franchises (`"It"` legitimately matches *It Chapter Two*,
*It Follows*, *It's Complicated*). Safeguards:

- **Author-time preview/confirm:** when a user sets up a match-ref, the UI shows
  exactly which current Tunarr titles match and requires confirmation before
  saving (`POST /api/recipes/preview`).
- **`exclude` list:** per-ref list of titles to drop, surfaced one click away
  from the change log when a bad title is auto-added.
- Future, principled option: `tmdb_franchise` (TMDB collection ID) — authoritative,
  no title guessing. Deferred.

The **LLM does not auto-author** live recipes — a human opts a channel in. This
keeps the false-positive guard (human confirm) intact.

## Ordering (release_date)

For `order: "release_date"`, order matched titles by the Tunarr program's `date`
field **if it carries one** (confirm against one live `/programs` response at
build time), else fall back to the `Year` column in `plex_library.csv`, else
append unknown-year titles last.

## Update Trigger — Diff vs Live Tunarr, No State File

Each cycle, for each live channel: GET its **current** programming from Tunarr,
freshly resolve its `content`, and compare the two program-ID sets. Patch **only
if they differ**. Tunarr is the source of truth — there is no `recipe_state.json`,
no episode counters. This is idempotent and survives container restarts for free
(important: Watchtower restarts the container on every image update).

Re-POSTing programming regenerates the channel's 30-day schedule and makes Plex
re-pull that channel's guide, so the diff gate matters: unchanged channels are a
cheap no-op (one GET + a set comparison), not a guide-churning re-post.

## In-Place Update Requirement

**Critical.** Updates always reuse `resolve` + `build_schedule` +
`set_programming` (`POST /api/channels/{id}/programming`) against the *existing
channel id*, looked up by channel number. **Never** call
`delete_channels`/`create_channel` for an update.

Deleting and recreating changes the Tunarr channel ID and breaks the Plex
HDHomeRun DVR mapping — the user has to manually re-add the channel. In-place
updates preserve the ID and number; Plex sees a guide refresh, not a device
change. `create.py`'s delete-and-recreate path is correct for *initial* deploy
only; the scheduler must never use it.

## Scheduler Architecture

A single global background loop inside the FastAPI app, started from the
`main.py` lifespan (alongside the existing `WindowsProactorEventLoopPolicy`
setup), guarded by `recipes_enabled`. One loop, one cadence
(`recipe_interval_hours`, default 12) — no per-channel intervals.

```
while recipes_enabled and not paused:
    async with deploy_lock:                 # shared with pipeline endpoints
        index = build_library_index()       # one build per cycle
        for ch in channels where ch.live:
            fresh = resolve(ch.content, index)        # program-id set
            try:
                cur = GET /api/channels/{id}/programming   # by ch.number
            except 404:
                continue                     # channel gone (manual deploy); skip
            if set(fresh) != set(cur):
                set_programming(id, build_schedule(ch.shuffle, fresh))
                log_diff(ch, added, removed) # -> data/logs/, Dashboard, badge
    sleep(recipe_interval_hours)
```

## Concurrency

Manual deploys run as subprocesses (`create.py`) that delete/recreate channels
and rewrite `channels.json`; the scheduler is in-process. A single in-process
`asyncio.Lock` (`deploy_lock`) is held by **both** the scheduler cycle and every
pipeline endpoint that spawns `create.py`/validate, serializing them. The cycle
also tolerates a 404 (channel mid-delete) and a mid-write `channels.json` (skip,
retry next cycle).

The CLI path (`programmarr.py` running `create.py` directly) is a separate
process the in-process lock cannot cover — running CLI deploys while the web
scheduler is active is a documented "don't."

## Observability

Each cycle writes a rolling diff log to `data/logs/` (per-channel adds/removes,
e.g. `#55 Bad Boys +Bad Boys: Ride or Die`). The Channels page shows a **Live**
badge + last-updated time per live channel; the Dashboard shows last cycle time
and recent changes. A wrong auto-add is visible and one click from the `exclude`
list.

## Authoring & First Activation

Live channels are authored in the Channels page (`Channels.tsx`): a per-channel
**Live** toggle, and for franchises a small builder (enter match value → live
preview of matched titles via `POST /api/recipes/preview` → confirm → edit
`exclude`). Toggling Live and confirming patches the channel **once immediately**
(in-place) so the user sees it work rather than waiting up to a full interval.

## Rollout & Kill Switch

Ships **off** by default behind `recipes_enabled: false` in `config.json`. The
user enables it in Settings once trusted. Even when enabled, only channels
marked `"live"` are touched. A visible "pause auto-updates" control on the
Dashboard halts the loop without a restart.

```json
{
  "recipes_enabled": false,
  "recipe_interval_hours": 12
}
```

## Build Surface (as built)

- Refactored resolution into `channel_engine.py`, exposing `build_library_index`,
  `resolve_title`, `build_schedule`, `set_programming` as importable functions,
  plus an `update_channel_in_place(number)` path that skips delete/create.
- New `backend/scheduler.py` started from `main.py` lifespan, guarded by
  `recipes_enabled`; reuses `deploy_lock`.
- `deploy_lock` retrofitted into the `create.py`/validate-spawning endpoints in
  `pipeline_router.py`.
- `POST /api/recipes/preview` (word-boundary match over the live Tunarr index),
  Channels.tsx builder UI, and the Dashboard/badge surfaces.

## Open Items — RESOLVED during build

1. Tunarr program objects **do** carry `releaseDate` (epoch ms), `releaseDateString`,
   and `year` — so `release_date` ordering reads straight from the Tunarr index; no
   `plex_library.csv` fallback was needed.
2. UI copy reflects the Tunarr-resync dependency (channels page + README note).
3. CLI-runs-`create.py`-while-web-scheduler-active remains unsupported (documented).

## Per-channel sync state (`data/recipe_state.json`)

Cosmetic, UI-only per-channel metadata — **not** used by the diff (correctness
still reads live Tunarr). Kept in its own file so it never races with
`channels.json` edits or deploys, and never reintroduces the state-file-as-truth
problem the diff design rejects.

- Shape: `{ "<number>": { "checked_at", "changed_at?", "change_summary?" } }`.
- Written by the scheduler (atomic temp-swap) at the end of **apply** cycles only
  (a dry run isn't a real "sync"); `checked_at` set for every live channel in the
  cycle, `changed_at`/`change_summary` only when that channel was actually patched.
  Full cycles prune entries for channels no longer live.
- Surfaced via `GET /api/recipes/status` → `channels` map. The Channels page shows
  a "synced Xago" note per live row; the Dashboard card shows "next ~in Xh" from
  `next_run_seconds` (`last_auto_run` is wall-clock so the sync status handler can
  compute it).

`POST /api/recipes/run` accepts `only=<number>` to scope a cycle to one channel —
the per-channel **"Save & Sync now"** button in the editor saves the channel then
runs `only=N&apply=true`, applying the recipe in place without leaving the modal.

## Future / not built — Source & Target Agnosticism

Deferred (a *future goal*, not on the current roadmap). Captured here so the intent
isn't lost. Today everything hard-codes **Plex** (source) and **Tunarr** (target);
`channel_engine.py` already concentrates the touchpoints, which is where an adapter
seam would go:

- **Source** (library queries): `build_library_index`, `resolve_collection`,
  episode/title resolution. A future Jellyfin/local source would implement these.
- **Target** (the "in-place update contract"): `find_channel_by_number`,
  `read_channel_programming`, `update_channel_in_place` (+ initial create). A future
  **ErsatzTV** target would implement the same contract — patch in place, preserve
  the channel's id/number, never delete-and-recreate.

Do **not** build a speculative adapter layer until there's a second source/target to
validate the abstraction against — with one implementation it will be the wrong shape.

## What This Is Not

- **Not Tunarr Smart Collections.** Those are Tunarr's own internal saved-search
  filters; they don't track your library over time or respond to external sources.
  Live channels live in Programmarr and drive Tunarr via its API.
- **Not a fork of Tunarr.** Programmarr stays a target-agnostic layer (see above).
- **Not a replacement for the AI / No-AI / Collections generation paths.** Those
  remain how channels are initially created. Live channels are an opt-in freshness
  layer on top.

## Superseded plan

`new_goals.md` (a late-night draft) proposed two bespoke recipe *types* and writing
the resolved content back into `channels.json` each cycle. Both were **deliberately
superseded**: the unified re-resolve model (no `recipe.type`) and the
no-writeback/diff-vs-Tunarr design above are the permanent approach. That file has
been retired; its still-relevant ideas (agnosticism, "What This Is Not") are folded
in above.
