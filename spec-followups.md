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

<!-- Append further review follow-ups below (one ## section each). -->
