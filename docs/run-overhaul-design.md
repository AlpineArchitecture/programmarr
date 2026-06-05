# Run Pipeline Overhaul — Design & Rationale

> **What this is:** the agreed design for reworking the **Run** pipeline UI
> (`frontend/src/pages/Run.tsx`) and its supporting backend. Captured from a
> design interview so it survives across sessions. This is the *intended* design —
> **not yet built**. As phases ship, fold the operational summary into
> [`../CLAUDE.md`](../CLAUDE.md) and move "why we chose X" notes here.
>
> **Status:** planned. Phased build (see *Build Sequencing* below). Nothing in
> this doc has shipped yet.

## Intent

The current Run flow grew by accretion: three top-level tabs (AI / No-AI /
Collections), each its own 4–6 step stepper, with decisions scattered across
steps ("questions, click, questions, click…"). Protection/start-number logic is
duplicated between the Channel Planner and Deploy. A GitHub user was confused by
the AI prompt hand-off (what to paste, where, attach vs paste).

The goal: **a series of simple questions up front, then click → click → click →
done.** Easy to run, but powerful enough that users feel in control of *what*
channels get made — not locked into the author's hardcoded set.

## Flow Shape — One Unified Stepper

The three tabs are removed. Method becomes a *question*, not a tab.

```
Setup screen → Export → Planner → [AI Prompt | No-AI gen] → [Collections?] → Deploy → (auto art → auto sync) → Done
```

- **Collections-only** skips Export and Planner entirely.
- Export only runs for methods that need it (AI, No-AI).

### Why a unified flow (not "keep tabs, simplify each")

The tabs forced the user to commit to a method before seeing anything, and
duplicated the entire pipeline three times. Making method a setup question lets
one stepper adapt, removes duplication, and front-loads every decision so the
back half is just clicks.

## Screen 0 — Setup (all upfront decisions)

A short "let's set up your channels" question card. Everything the user must
decide lives here, *before* any work runs:

- **Method:** `AI` · `No-AI` · `Collections-only`
- **Include Plex collections?** (y/n). If yes, a dedicated **Choose Collections**
  step (the existing poster/checkbox/number picker) appears later in the stepper.
  If no, that step is hidden.
- **Fetch TMDB art?** (y/n). The toggle is **disabled** with an "add a TMDB key in
  Settings" hint when `config.tmdb_api_key` is absent.
- **Existing Tunarr lineup — keep vs wipe.** The protection checkboxes (and the
  auto-calculated start number) move here from the old Planner. This is a genuine
  upfront decision and it sets the channel start number before anything else runs.

### Why setup-first (not Export-first)

Export is wasted work for a Collections-only user, and the method choice changes
whether Export even matters. Asking method first lets Collections-only skip
straight past Export.

### Consequence — Deploy's duplicate protection panel is removed

Keep/wipe is decided once, on setup. Deploy no longer re-asks; it just honors the
protected set (passed to `create.py` via `--protect`).

## Planner — the "design" screen

Where the user shapes *what* channels get made. Pure design decisions; no
keep/wipe here anymore.

### Toggles: grouped with hierarchy

Three labeled groups:

```
CONTENT TYPES
 [✓]TV Marathons  [✓]TV Blocks  [✓]Movies  [✓]Franchise  [✓]Specialty
MOVIE GENRES   (enabled only when Movies = on)
 [✓]Comedy(88) [✓]Action(61) [✓]Horror(42) [✓]Sci-Fi(30) [✓]Drama(95) [✓]Animation(22)
 ▾ More genres (Western 12, Noir 9, Romance 40 …)
DECADES
 [✓]70s [✓]80s [✓]90s(54) [✓]2000s(71) …
```

- Turning the **Movies** content type off disables the Genres + Decades groups
  (they're subdivisions of the movie block) — prevents the "Movies off but Horror
  on" conflict.

### Toggles are shared — they drive BOTH methods

One control panel. This is the key unifying move:

- **AI:** toggles inject include/exclude rules into the prompt.
- **No-AI:** toggles decide which generator blocks run (skip the Horror block,
  skip 90s, etc.).

### Toggle source — derived from the exported library, with counts

Because Export runs before the Planner, we know the user's actual genres/decades
and their item counts.

- Show real counts (`Horror (42)`); default-off any toggle with too few items.
- **Genres can sprawl** (40+ Plex tags), so: show the **7 canonical buckets**
  (Comedy/Action/Horror/Sci-Fi/Drama/Animation/Documentary) up front, with a
  **"More genres"** expander revealing other library genres above a threshold,
  sorted by count. Decades are naturally bounded (~6 buckets), no cap needed.

### Content-type applicability per method

`generate_no_ai.py` only truly auto-generates **TV Marathons** (50+ episode
shows) and **Movie** genre/decade channels. **TV Blocks / Franchise / Specialty**
are AI-only. So:

- All five content types are shown.
- For **No-AI**, TV Blocks / Franchise / Specialty are **grayed out** with a
  "requires AI" hint.
- For **AI**, all five are live.

### Per-method config

- **Toggles:** always shown.
- **Target channel count + free-text theme box:** **AI-only** (No-AI can't use a
  target — it builds a fixed set — and can't interpret free text). No dead/disabled
  controls on the No-AI Planner.
- **No-AI** Planner's primary button is **Generate Channels** → runs the script
  with the toggle flags → advances straight to Deploy. No separate Generate step.

## AI Behavior — Hints + Hard Exclusions

The AI path's value is the LLM *discovering* clusters the user didn't think of
(8 Pixar films → a Pixar channel; franchises; oddball themes). Rigid "make ONLY
these" rules would make AI behave like No-AI but slower.

So the toggles map to:

- **Checked genre/decade/type** → "must include if the library supports it."
- **Unchecked** → hard "never create this" rule.
- **Plus** an explicit invitation to create *additional* themed channels the LLM
  discovers.

The free-text theme box and the toggles coexist (the theme box is the existing
high-priority "User Preferences" injection).

## AI Prompt Screen — Numbered Walkthrough

The fix for the GitHub user's confusion. Explicit numbered steps:

```
1. Copy the prompt                         [Copy]
2. Open your AI chat        [ChatGPT] [Claude] [Gemini]
3. Paste it, then attach this file   [⬇ plex_library.csv]
4. Copy the AI's full response
5. Paste it back here                [_____________]
```

### PROMPT.md split (implemented as a runtime strip)

`PROMPT.md`'s meta header (the "how to use this" block above the first `---`:
model recommendation, "set {TARGET}", Option A file-attach vs Option B paste) is
a **UI concern** — it moves into the walkthrough copy. Only the **LLM-facing
prompt** (everything below `---`) stays copyable.

**Built as a runtime strip, not a file edit:** `PROMPT.md` is left intact (the
CLI `programmarr.py` still reads the full file directly). The new
`POST /pipeline/prompt` calls `_strip_meta()` to drop everything above the first
`---` before returning. The legacy `GET /pipeline/prompt` returns the full file
unchanged, so the current live UI isn't degraded before PR2 ships.

The copyable prompt is **rebuilt server-side** (`POST /pipeline/prompt`) with:

- the toggle-derived include/exclude rules + "you may also discover" language,
- the target count,
- the channel-numbering scheme offset by the keep/wipe start number from setup.

## Deploy + Cascade

- **Auto-probe** runs when the user lands on Deploy (no separate "Run Probe"
  button). They see the verified channel list + any missing-title warnings.
- **One Deploy click.** The channel review/exclude + renumber UI stays (from the
  current Deploy step).
- After deploy, **art + sync cascade automatically** (art only if opted in and a
  TMDB key exists).

### Cascade failure handling — always completes, summary shows status

Sync frequently *can't* auto-complete (`sync_plex.py` falls back to printing
manual "add the DVR in Plex" instructions); art can partially fail. The cascade
**never blocks** — it runs every stage and the final Done screen reports per-stage
status:

```
Done!
 ✓ 14 channels deployed
 ✓ Art: 12 logos fetched
 ⚠ Plex sync needs one manual step ▾
     [XMLTV URL + 3 steps]
```

## Build Sequencing — Phased PRs

Each phase ships to local Docker → verify against the user's own Plex/Tunarr →
ship. The old flow stays usable until PR2 flips it.

- **PR1 — backend** (`feature/run-overhaul-backend`):
  - new **library-facets** endpoint: genre-tag counts + year→decade bucketing over
    `plex_library.csv` (natural extension of `csv_info`),
  - `generate_no_ai.py` **toggle flags** — accept a selected genre/decade/type
    list and number the movie block dynamically, including non-canonical genres a
    user toggled on via "More" (today `GENRE_CHANNELS`/`DECADE_RANGES` are
    hardcoded with fixed numbers),
  - `POST /pipeline/prompt` with toggle injection + runtime meta-strip (legacy GET
    kept intact for the current UI).
  - All testable via API before any UI exists.
- **PR2 — frontend:** new unified `Run.tsx` replacing the tabs, wired to PR1.
- **PR3 — polish:** cascade + per-stage status summary.

## Implementation Notes (consequences, not new decisions)

- `generate_no_ai.py` must move from hardcoded `GENRE_CHANNELS` /
  `DECADE_RANGES` to a parameterized generator: a passed-in list of
  genres/decades/types, with dynamic numbering within each block, and support for
  arbitrary (non-canonical) genre tags.
- The facets endpoint needs a genre-tag count pass over the CSV `Genres` column
  and a `Year`→decade bucketing.
- Channel protection still flows to `create.py` via `--protect N1,N2,…`; only the
  *place the user decides it* moves (setup screen, not Deploy).
