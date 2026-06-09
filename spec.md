# spec.md — Planner Overhaul

> **Architect:** Opus (orchestrator + reviewer). **Builder:** Sonnet (subagent per step).
> This document is the single source of truth. Build it **one step at a time, in order.**
> After each step: build the frontend, run tests, serve on `localhost:7979`, report what
> changed. Control returns to the architect for review before the next step is spawned.

---

## Workflow & ground rules

- **Branch strategy.** One integration branch off `master`: `feature/planner-overhaul`.
  Each step stacks as one or more commits on that branch. **Never commit to `master`.**
  **Never merge to `master`** — the human does the final review and runs `/release`.
- **Per-step exit criteria.** `pytest` green, `cd frontend && npm run build` clean, app
  runs on `:7979`, and the step's **Acceptance** checklist passes. Report a short summary
  + the files touched.
- **Keep `CLAUDE.md` in sync in the same commit** as any behavior change (this is a hard
  project rule — see CLAUDE.md "Git Workflow").
- **Don't restate code in CLAUDE.md** — point at it. Update the relevant sections
  (Channel Numbering Scheme, Run.tsx, channels.json Schema, API Endpoints) as you change them.
- **Conventions:** match the surrounding Mantine v7 + React idiom in `frontend/src/pages/`.
  Backend pure modules (`channel_blocks.py`, `channel_engine.py`) stay pure/importable and
  **must remain in the Dockerfile `COPY` line.**
- **Tests live in `backend/tests/`** (`pytest.ini`). Add/extend tests where noted.

---

## Decisions already made (do not relitigate)

1. **Numbering = sequential from 1, category-grouped, tight-packed.** No fixed sizes, no
   caps, no gaps. 15 marathons → channels 1–15, next category starts at 16. The only
   configurable knob is the **order of the categories**. (Add/edit mode continues numbering
   above the highest kept channel instead of from 1.)
2. **Planner = three collapsing sections: TV / Movies / TV+Movies.** One open at a time;
   finishing one collapses it and opens the next; all stay re-openable.
3. **TV+Movies channels = mixed-genre**: one candidate per genre present in *both* libraries,
   episodes + films shuffled into one channel.
4. **Section mapping:** TV → marathons, genre blocks, networks, classic programming blocks.
   Movies → genre×decade, sub-genres, broad genres, studios/directors/actors.
   TV+Movies → mixed-genre channels + franchises.
5. **Franchise membership = Plex collections + TMDB hybrid**, on-demand + cached. Per-member
   checkboxes. AI ✨ discovery stays as the optional layer.
6. **Networks = reuse the existing `Studio` column filtered to `Type==TV`.** No export schema change.
7. **Classic programming blocks = a static catalog seeded from Wikipedia**, shipped in-repo
   (`programming_blocks.json`), matched against the library. No runtime AI, no scraping.
8. **Planner state persists** to `data/planner_state.json` (saved intent, not reconstructed
   from Tunarr).
9. **Top-of-Run binary "Nuke vs Add/Edit" is the deploy-mode selector:**
   - **Nuke** → wipe-and-rebuild, numbering from 1.
   - **Add/Edit** → surgical diff (create new / delete unchecked / update-changed in place /
     leave unchanged), numbering above the existing set. **Never** delete-recreates a live
     channel; **never** touches orphan channels.

---

## STEP 1 — Dashboard UI fixes  *(isolated; no backend, no deps)*

**Goal:** two small visual cleanups on the Dashboard.

**Files:** `frontend/src/pages/Dashboard.tsx`, and the guide-grid component it renders
(`GuideGrid` — find where channel number + name are rendered; check `Dashboard.tsx` and any
`frontend/src/components/` guide file).

**Changes:**
1. **Auto-Updates card — remove the recently-updated channel list.** In `Dashboard.tsx`
   (~lines 119–136), delete the `last.changes.slice(0, 4).map(...)` block that lists each
   updated channel. **Keep** the "Auto-Updates · On/Paused" status row and the
   "Last check {relTime} · {N} updated / no changes / error" line (including the count).
2. **Guide grid — stop repeating the channel number.** The grid currently shows the channel
   number on top and `#N Name` below it. Render the **number on top, the name below WITHOUT
   the leading `#N`** (just the name). Find the duplicated number in the guide channel
   header/cell and remove it from the name line only.

**Acceptance:**
- Auto-Updates card shows status + last-check line (with count) and **no per-channel list**.
- Guide channel cells show the number once (top) and the bare name below.
- `npm run build` clean.

---

## STEP 2 — Numbering overhaul  *(foundational — everything downstream writes into this)*

**Goal:** replace fixed-size blocks with sequential-from-1, category-grouped, tight packing,
with a user-configurable **category order**.

### 2a. `channel_blocks.py` (repo root)
Rewrite the model. A "block" no longer has a *size*; it's just an **ordered category**.
- Keep `CANONICAL_ORDER` as the **default** order and `BLOCK_LABELS`. Add the new categories
  that later steps need so the order list is complete now:
  `["marathon", "tv_block", "tv_movie_mix", "movie", "entity", "network", "programming_block",
  "franchise", "specialty"]`. (Use these exact keys; later steps map candidates onto them.)
  Provide labels for all of them in `BLOCK_LABELS`.
- **Remove** `DEFAULT_SIZES`, `normalize_sizes`, and the size-accumulation in `resolve_layout`.
- Replace with a pure function that, given **an ordered list of categories** + the **count of
  channels in each category** + a **start number**, returns sequential number assignments,
  packed tight in category order:
  ```python
  def assign_numbers(order: list[str], counts: dict[str, int], start: int = 1) -> dict[str, list[int]]:
      """Return {category: [channel numbers]} packed sequentially from `start`,
      in the given category order. Empty categories consume no numbers."""
  ```
  Example: order `[marathon, movie, franchise]`, counts `{marathon:15, movie:8, franchise:3}`,
  start 1 → marathon 1–15, movie 16–23, franchise 24–26.
- Add a helper to read the configured order from config, falling back to `CANONICAL_ORDER`,
  ignoring unknown keys and appending any missing canonical keys at the end:
  ```python
  def resolve_order(configured: list[str] | None) -> list[str]: ...
  ```
- Config key changes from `channel_blocks` (sizes object) to **`channel_order`** (list of
  category keys). Keep reading the old key as a no-op/ignore (don't crash on old configs).

### 2b. Compose (`backend/routers/pipeline_router.py`)
- `compose_channels`: replace the `resolve_layout` soft-block + spill logic with
  `assign_numbers(resolve_order(cfg.get("channel_order")), counts, req.start)`. Counts come
  from how many channels each category bucket produced. Preserve input order within a category.
- Update `_CATEGORY` / `_CATEGORY_ORDER` / `_CATEGORY_BLOCK` to the new category keys (drop the
  hardcoded `10/20/30/50` number hints — there are no fixed lanes now).
- `_regen_numbering_scheme` / PROMPT.md numbering: regenerate the prompt's numbering guidance
  from the configured order + a representative packing (no fixed ranges). Keep it honest with
  what compose produces.

### 2c. `generate_no_ai.py`
- Replace `--block-sizes K=N` handling and the `channel_blocks` size layout with the new
  sequential `assign_numbers` + `resolve_order`. Accept `--order m,tv_block,movie,...` (CSV of
  category keys) instead of `--block-sizes`. `--start N` still sets the first number.
- Update `run_no_ai` in `pipeline_router.py` to pass `--order` from `channel_order` config
  instead of `--block-sizes`.

### 2d. Settings UI (`frontend/src/pages/Settings.tsx`)
- Replace the "Channel Numbering" size inputs (~lines 182–205, the `blockSizes` state) with a
  **drag-to-reorder list** of the categories (use a simple, dependency-free reorder — Mantine
  has no built-in DnD; implement up/down arrow buttons per row **or** native HTML5 drag; arrows
  are acceptable and simpler — prefer arrows for reliability). Persist as `channel_order`
  (array of category keys) via `api.saveConfig`. Show each category's human label.
- Remove `BLOCK_DEFAULTS`/`blockSizes`; load `channel_order` from config (fallback to default
  order). Show a one-line explainer: "Channels are numbered 1, 2, 3… in this category order."

### 2e. Onboarding (`frontend/src/pages/Onboarding.tsx`)
- Add a step (after server URL / token / auth) that lets the user set the **category order**
  once, reusing the same reorder component. Save into `channel_order`. Keep it skippable
  (defaults to `CANONICAL_ORDER`).

### 2f. Config merge-write (`config_router.save_config`)
- Ensure `channel_order` is preserved on partial saves the same way `channel_blocks` was
  (see CLAUDE.md "Configuration" note about merge-write). Don't wipe it on an empty save.

**Tests:** update `backend/tests/test_compose.py`, `test_generate_no_ai.py`, and any
`channel_blocks` test to the new sequential model. Add a test that category order changes the
resulting numbers.

**Acceptance:**
- Fresh compose with 15 marathons + 8 movies → 1–15 then 16–23.
- Reordering categories in Settings changes the produced numbers on the next build.
- Onboarding lets a new user set order; Settings lets them change it.
- Old configs with `channel_blocks` don't crash.
- `pytest` green, `npm run build` clean. Update CLAUDE.md "Channel Numbering Scheme".

---

## STEP 3 — Planner three-section restructure + TV+Movies mixed channels

**Goal:** reorganize the Planner (`frontend/src/pages/Run.tsx`, `PlannerStep`) into three
collapsing sections and add mixed-genre TV+Movies candidates.

### 3a. Backend — new facet for cross-library genres
In `library_facets` (`pipeline_router.py`), add a `tv_movie_genres` facet: genres present in
**both** movies and TV above a threshold (reuse `TV_GENRE_MIN`-style floor on each side). Shape:
`[{"genre": "Comedy", "tv_count": N, "movie_count": M}]`. Add to the returned dict and to
`LibraryFacets` in `frontend/src/api/client.ts`.

### 3b. Backend — new compose kind `tv_movie_mix`
- Add `tv_movie_mix` to `CandidateSpec.kind` handling and `_CATEGORY` (category key
  `tv_movie_mix`, shuffle default `shuffle`).
- `_resolve_spec`: for `tv_movie_mix` with `spec.genre`, return titles of **both** movies and
  shows that have that genre (de-duped, sorted). The channel's `content` is the mixed title
  list — the resolution engine already matches titles regardless of type, so no engine change.
- `_auto_name`: `f"{genre}"` (or `f"{genre} TV & Movies"` — pick the cleaner; default `genre`).

### 3c. Frontend — three accordion sections
Restructure `PlannerStep`'s body into three `CollapsibleSection`-style groups with
**single-open accordion behavior**:
- **Section 1 — TV:** the existing Marathons + Genre-blocks groups. (Networks + classic blocks
  are added in Step 5 — leave clear insertion points.)
- **Section 2 — Movies:** genre×decade, sub-genres, broad genres, then Studios/Directors/Actors.
- **Section 3 — TV + Movies:** new mixed-genre candidates from `tv_movie_genres` (label e.g.
  "Comedy — 42 episodes + 88 films"). (Franchises added in Step 6 — leave an insertion point.)

Accordion mechanics: track an `openSection` index. Section 1 starts open. Each section has a
**"Done — continue" affordance** in its header/footer that collapses it and opens the next.
Clicking a collapsed section's header re-opens it (and collapses the current). The
genres/decades "in play" chips stay at the top, above the sections (they drive both Movies and
TV+Movies candidates). The build bar stays at the bottom and reflects all sections' selections.

Keep the existing `selected`/`curate` maps and `cid` id scheme; add `cid.tvmix = (g) => \`tvm:${g}\``.

**Tests:** extend `test_facets.py` for `tv_movie_genres`; `test_compose.py` for `tv_movie_mix`.

**Acceptance:**
- Planner shows three accordion sections behaving as described.
- A `tv_movie_mix` pick builds one channel whose content holds both show and movie titles.
- `pytest` green, `npm run build` clean. Update CLAUDE.md "Run.tsx" section.

---

## STEP 4 — Add/Edit flow + planner state + surgical deploy

**Goal:** top-of-Run Nuke/Add-Edit binary, persistent planner state, and a surgical diff deploy.

### 4a. Planner state file
- New endpoints in `pipeline_router.py`:
  `GET /pipeline/planner-state` → returns `data/planner_state.json` (or `{}` if absent);
  `PUT /pipeline/planner-state` → writes the posted JSON.
- Persist the full `PlannerState`-equivalent (activeGenres, activeDecades, selected, curate,
  and the batch toggles: aiExtras, commercials, autoUpdate). Add `getPlannerState` /
  `savePlannerState` to `client.ts`.
- **Save** on every successful Build (compose). **Load** when the planner mounts in **Add/Edit**
  mode. **Clear** (delete the file) when the user chooses **Nuke**.

### 4b. Top-of-Run binary (`SetupStep` in `Run.tsx`)
- Replace the per-channel keep/wipe checklist as the *primary* control with a prominent binary:
  - **🧨 Nuke and start over** — wipe all managed channels, planner starts blank, numbering from 1.
  - **✏️ Add / edit what you've got** — keep existing managed channels, restore previous planner
    clicks from `planner_state.json`, numbering continues above the existing set.
- Keep the existing per-channel checklist available under an **"Advanced"** disclosure in
  Add/Edit mode (so a power user can still force-wipe specific channels). The computed `start`
  in Add/Edit = highest existing managed channel + 1 (no longer "round up to next 10").
- `SetupState` gains `mode: 'nuke' | 'edit'`.

### 4c. Surgical diff deploy
- New deploy path used in **Add/Edit** mode. Compute desired state = planner draft; current
  state = deployed `channels.json` (managed channels only). Diff by channel **identity**
  (match on name — or carry a stable key in planner_state; name is acceptable since planner
  names are deterministic). For each:
  - **new** (in desired, not deployed) → create
  - **removed** (deployed, not in desired) → delete from Tunarr
  - **changed** (same identity, different content/shuffle/flags) → **update in place** via the
    existing in-place machinery (`channel_engine.update_channel_in_place` / the
    `POST /channels/{n}/apply` path) — preserves Tunarr id + Plex DVR mapping
  - **unchanged** → leave untouched
- **Invariants (enforce + test):** never delete-recreate a `live` channel; never touch orphan
  channels (channels in Tunarr with no `channels.json` entry). Hold `scheduler.deploy_lock`
  for the operation (same as other create.py runs).
- **Nuke** mode keeps using the existing wipe-and-rebuild deploy-selective path, numbering from 1.
- Wire the Run Deploy step to pick the path from `setup.mode`.

**Tests:** add `backend/tests/test_surgical_deploy.py` — cover create/delete/update/unchanged
classification, the live-channel safety rule, and orphan safety (use the `seed` fixture pattern;
mock the Tunarr-facing calls).

**Acceptance:**
- Choosing Add/Edit restores prior checkboxes; unchecking a channel and deploying deletes just
  that channel; editing one updates it in place (id unchanged); others untouched.
- Choosing Nuke wipes and rebuilds from 1 and clears `planner_state.json`.
- Live + orphan channels are never delete-recreated.
- `pytest` green, `npm run build` clean. Update CLAUDE.md (Run.tsx durable rules + a note on
  the surgical path under channels.json invariants).

---

## STEP 5 — Networks + classic programming blocks  *(TV section)*

**Goal:** offer network channels and historical programming-block channels in the TV section.

### 5a. Networks (reuse Studio for TV)
- In `library_facets`, add a `networks` facet: counts of `Studio` values **for `Type==TV`
  rows** above a floor (e.g. `NETWORK_MIN = 3`), capped like other entity lists. Shape
  `[{"value": "HBO", "count": N}]`. Add to `LibraryFacets` in `client.ts`.
- Add compose kind `network` (category key `network`, shuffle `shuffle`): `_resolve_spec`
  returns TV show titles whose `Studio` matches the value (case-insensitive). `_auto_name` →
  the network value (e.g. "HBO").
- Frontend: add a "Networks" group to **Section 1 (TV)**, same `EntitySection` pattern as
  studios. `cid.network = (v) => \`net:${v}\``.

### 5b. Classic programming blocks (static catalog)
- Create `programming_blocks.json` at repo root (and add to Dockerfile `COPY`). Seed it from
  Wikipedia's documented lineups. Schema:
  ```json
  [
    {"name": "TGIF", "era": "1989–2000", "network": "ABC",
     "shows": ["Full House", "Family Matters", "Step by Step", "Boy Meets World", "Perfect Strangers"]},
    {"name": "Must See TV", "era": "1990s", "network": "NBC",
     "shows": ["Seinfeld", "Friends", "Frasier", "ER", "Will & Grace"]},
    {"name": "Saturday Morning Cartoons", "era": "classic", "network": "various",
     "shows": ["Animaniacs", "X-Men", "Batman: The Animated Series", "DuckTales", "Tiny Toon Adventures"]}
  ]
  ```
  Include a solid starter set (TGIF, Must See TV, Saturday Morning Cartoons, Animation
  Domination, SNICK, Nick at Nite). Titles must be reasonable Plex matches.
- New endpoint `GET /pipeline/programming-blocks`: load the catalog, and for each block return
  it **with the subset of `shows` present in the library** + a present-count; only return blocks
  with ≥ `BLOCK_MIN` (e.g. 3) members present.
- Add compose kind `programming_block` (category key `programming_block`, shuffle `ordered` or
  `block`): the spec carries the resolved member titles; `_resolve_spec` intersects them with
  library show titles. `_auto_name` → the block name.
- Frontend: add a "Classic TV Blocks" group to **Section 1 (TV)** listing matched blocks
  (label "TGIF — 4 of 5 shows"). Each is a single checkable candidate. `cid.progblock = (n) => \`pb:${n}\``.

**Tests:** `test_facets.py` for `networks`; a test that `programming-blocks` filters to library
members; `test_compose.py` for both new kinds.

**Acceptance:**
- TV section shows Networks (from TV Studio values) and matched Classic TV Blocks.
- Building either produces a channel with the right titles.
- `pytest` green, `npm run build` clean. Update CLAUDE.md.

---

## STEP 6 — Franchise detection  *(TV+Movies section — biggest)*

**Goal:** franchise channels with per-member selection, sourced from Plex collections + TMDB.

### 6a. Backend — franchise discovery (on-demand, cached)
- New endpoint `GET /pipeline/franchises` that returns franchise candidates, each with its
  member titles **present in the library**:
  ```json
  [{"name": "The Matrix Collection", "source": "plex",
    "members": [{"title": "The Matrix", "year": 1999, "type": "Movie"}, ...]}]
  ```
- **Source 1 — Plex collections:** reuse the existing `list_collections` logic. For each
  collection, fetch its member titles (Plex collection children) and keep those present in the
  library. Collections can include TV → franchises span TV+Movies.
- **Source 2 — TMDB enrichment (only if `tmdb_api_key` set):** for movies in the library, look
  up `belongs_to_collection` (search by title+year → movie → collection), group by collection,
  keep collections with ≥2 library members that aren't already covered by a Plex collection.
  **This is the slow part:** run it on-demand when the endpoint is hit and **cache** the result
  to `data/franchise_cache.json` keyed by a library hash/mtime; serve cache on subsequent hits.
  Add a `?refresh=1` to force re-fetch. Never block export on this.
- Merge sources; de-dupe by normalized name; sort by member count desc.

### 6b. Backend — compose
- Add compose kind `franchise` (category key `franchise`, shuffle `ordered` — franchises play
  best in release order). The spec carries the **selected member titles** (the per-member
  checkbox result), so `_resolve_spec` just intersects them with the library (movies + shows).
  `_auto_name` → the franchise name.
- For ordered playback, sort the content by year when available.

### 6c. Frontend — franchise picker (Section 3, TV+Movies)
- Add a "Franchises" group. Fetch `GET /pipeline/franchises` (show a loader — it may be slow on
  first hit; show "Scanning TMDB…" when applicable). Each franchise renders as an expandable
  card with **per-member checkboxes** (default all checked). The card is selected when ≥1 member
  is checked; the built channel uses exactly the checked members.
- Store the per-member selection in the planner `selected` map under `cid.franchise = (name) => \`fr:${name}\``
  with the spec carrying the chosen titles. Persist in planner_state (Step 4) like everything else.
- AI ✨ discovery (existing) stays as the optional layer — no change needed beyond making sure
  franchise channels are listed in the discover prompt's "already built" section.

**Tests:** `test_franchises` (mock Plex collection members + TMDB; assert library-filtering,
cache behavior, source merge/de-dupe); `test_compose.py` for the `franchise` kind with a member
subset.

**Acceptance:**
- TV+Movies section lists franchises from Plex collections (+ TMDB when keyed), each with
  per-member checkboxes; checking a subset builds a channel with exactly those titles in year
  order.
- First call may be slow (TMDB) but is cached; `?refresh=1` re-scans.
- No TMDB key → Plex-only franchises still work.
- `pytest` green, `npm run build` clean. Update CLAUDE.md (Run.tsx + a franchise data-source note).

---

## Final (human) review
After Step 6: full app on `:7979`, walk the whole flow (Nuke + Add/Edit), confirm numbering,
all three sections, networks, classic blocks, franchises. Then the human runs `/release`.
