# Tunarr Commercials & Filler — Findings

> **Status:** Research/findings doc, not yet a built feature — but a **working approach was found**
> (between-show channel filler; see TL;DR + §10). Captures a deep investigation (2026-06-06/07) into
> what Tunarr's filler/commercial system can *actually* do today, what's a trap, and how a
> "commercials" toggle would work in Programmarr.
> **Verified against Tunarr 1.3.5** (ffmpeg 7.1.1) using the live instance + the Tunarr
> source checkout at `C:/Users/james/Projects/Tunarr`. Behavior is version-specific — re-verify
> if Tunarr is upgraded.

---

## TL;DR — the honest verdict

**Commercials DO work in Tunarr — via the simple, intended path (filler in the gap *between*
shows). The fancy path (mid-roll *inside* a show) does NOT work in this setup.** The whole
saga was us testing the broken path first; the working path turned out to be the dead-simple one.

- **✅ WHAT WORKS (verified live on ch 159, 2026-06-07):** attach a filler list to the **channel**
  (`fillerCollections`, the "Flex tab" mechanism) + add **light padding** to the schedule so a
  gap appears after each episode. Tunarr's `FillerPickerV2` fills that gap with commercials at
  playback. Result: real commercials (Bud Light → St. Ides → Nestlé Crunch, back-to-back) played
  cleanly, then the show resumed. **No dead air, no offline screen.** This is exactly how Tunarr
  intends filler to be used.
- **❌ WHAT DOESN'T: mid-roll (splicing ads *inside* a show).** Three variants all failed —
  local clips, re-encoded-to-1080p-h264/AAC clips, and Plex-sourced clips — with *"this stream is
  facing technical issues"* (local) or full *"channel offline"* (Plex). **Crucially, the SAME
  Plex-sourced clips that fail via mid-roll work perfectly via the between-show path.** So it's not
  the clips, the audio, or the source backend — it's the **mid-roll splice operation itself**
  choking the Tunarr 1.3.5 + **QSV** transcode pipeline. Park mid-roll for a future Tunarr / a
  software-transcode config.
- **The ad load is naturally fine.** Padding each ~22-min episode up to the next 5 min yields a
  ~3-min gap (~12%), filled with a few commercials. Tune `padMs` to taste. (Padding to a 30-min
  *block* would force ~8 min of ads — don't; just pad to a small boundary.)
- **Filler selection is smart-random** (`FillerPickerV2`, weighted reservoir sampling): favors
  clips not played recently, enforces a repeat cooldown (`fillerRepeatCooldown`, ~30s), tracks
  ~2 days of history → varied real-TV rotation through the whole pool, no back-to-back repeats.
- **Two traps that cost us the night (still true, still worth knowing):**
  - The slot endpoints `schedule-slots` / `schedule-time-slots` are **preview-only and silently
    don't persist** — write schedules via `/programming` (it persists). (§2)
  - **Rewriting a channel's `/programming` kills any live stream on it** — the "channels keep
    breaking" symptom. (§5d)

**Recommendation:** build a dead-simple per-channel **"Enable Commercials" toggle** = attach the
commercial filler list to the channel + set a modest `padMs` (no mid-roll, no slot scheduler).
See §10. Skip uniform blocks, pre/mid/post, and mid-roll entirely for v1.

---

## 1. How Tunarr filler actually works (mental model)

1. **A filler list is inert inventory.** It's just a named bucket of short clips (we have
   **"Commercial Breaks," 391 clips**, id `741da083-a5ee-4f03-988a-fb50c9d739e4`). On its own it
   plays nothing.
2. **Filler only ever plays into a *gap* (flex).** No gaps in the schedule → no commercials.
   The entire game is "create the right gaps, then point them at the commercial list."
3. **There are two completely different ways to use it:**

   | | Channel-level (the "Flex tab") | Per-slot (the slot scheduler) |
   |---|---|---|
   | Field | `channel.fillerCollections: [{id, weight, cooldownSeconds}]` | `slot.filler: [{types:[...], fillerListId, fillerOrder}]` |
   | What it does | Fills **any** leftover flex on the channel, picked at **playback time** | Bakes specific filler (pre/mid/post/etc.) **into the lineup** at schedule time |
   | Needs gaps from | Padding (you must create flex some other way) | Padding (pre/post/head/tail/fallback) or mid-roll (mid) |
   | Good for | A safety net to mop up stray flex | Real pre/mid/post-roll control |

**What Tunarr steers new users toward:** the Flex tab (channel `fillerCollections`) + "Pad Times."
That's the documented easy path — but "Pad Times" is exactly the block-padding that forces the
heavy ad load. So the "easy" path is also the "obnoxious" path.

---

## 2. The schedulers, and the #1 trap: preview vs. persist

Tunarr has three relevant schedule "shapes," all sharing the same slot schemas:

- **`type: random`** — slots with weights; random distribution. (What Programmarr emits today.)
- **`type: time`** — slots anchored to clock times (`startTime` ms-from-midnight); real-TV grid.
- **`type: manual`** — a pre-materialized `lineup: [...]` array, saved verbatim.

### The trap (cost us hours)

```
POST /api/channels/{id}/schedule-slots        ← COMPUTE/PREVIEW ONLY. Does NOT save.
POST /api/channels/{id}/schedule-time-slots   ← COMPUTE/PREVIEW ONLY. Does NOT save.
POST /api/channels/{id}/programming           ← THIS is what persists.
```

Confirmed in `server/src/api/channelsApi.ts`: the `schedule-slots` / `schedule-time-slots`
handlers materialize a lineup via a worker task + `MaterializeLineupCommand` and **return** it,
but **never call `updateLineup`**. The `/programming` handler **does** call
`channelDB.updateLineup(...)`. So the slot endpoints are what the *UI* uses to live-preview a
schedule before the user hits save; the save then goes through `/programming`.

**We were "applying" schedules via `schedule-slots` and they never saved.** Channels kept their
old plain lineup, the guide never changed, and no commercial ever played — while the POST
*responses* showed a perfect lineup with filler, making it look like it worked.

### The right way to persist filler/mid-roll

`/programming` accepts the same slot schemas, so put the filler + midRoll **into the
`type: random` schedule** and POST that:

```jsonc
POST /api/channels/{id}/programming
{
  "type": "random",
  "programs": ["<all episode program ids>"],
  "schedule": {
    "type": "random", "flexPreference": "end", "maxDays": 30,
    "padMs": 0, "padStyle": "episode", "randomDistribution": "uniform",
    "slots": [{
      "type": "show", "showId": "<uuid>", "order": "shuffle",
      "id": "<uuid>", "cooldownMs": 0, "weight": 100,
      "filler": [{ "types": ["mid"], "fillerListId": "<commercials>", "fillerOrder": "shuffle_prefer_short" }],
      "midRoll": { /* see §4 */ }
    }]
  }
}
```

**Always verify persistence** with `GET /api/channels/{id}/programming` and confirm the `lineup`
array actually contains `filler` items. **Never trust the POST response of the preview endpoints.**

> **Bonus for Programmarr:** `channel_engine.build_schedule` already posts `type: random` to
> `/programming`. So a "commercials" toggle is just *adding `filler` + `midRoll` to the slots it
> already builds* — no new endpoint, no separate save step.

---

## 3. Filler types — where each one inserts

Per-slot `filler[].types` (any combination), from `slotSchedulerUtil.ts` / `SlotImpl.ts`:

| Type | Where it plays | Needs |
|------|----------------|-------|
| `head` | Once at the **start of the slot block** | slot padding/flex |
| `pre` | **Before each program** (pre-roll) | slot padding/flex |
| `mid` | **Spliced inside the program** (true mid-roll) | nothing — see §4 |
| `post` | **After each program** (post-roll) | slot padding/flex |
| `tail` | Once at the **end of the slot block** | slot padding/flex |
| `fallback` | Fills any remaining flex in the slot | slot padding/flex |

**Crucial consequence:** every type *except* `mid` needs flex to exist, and flex only comes from
**padding** (rounding the show up to a block). So pre/post/head/tail are inseparable from the
block-padding ad-load problem. **`mid` is the only type that adds ads without padding.** That's
why mid-roll-only is the pragmatic choice.

---

## 4. Mid-roll config (the one good feature)

Per-slot `midRoll` object (from the OpenAPI + `slotSchedulerUtil.applyMidRollBreaks` /
`midRollBreakRules.ts`):

```jsonc
"midRoll": {
  "breakRule": { "type": "percentage", "points": [33, 66] },   // 2 breaks at 33% & 66%
  // other breakRule options:
  //   { "type": "fixed_interval", "intervalMs": 420000 }                 // every 7 min
  //   { "type": "initial_then_interval", "initialDelayMs": ..., "intervalMs": ... }
  "maxBreaks": 2,
  "minProgramDurationMs": 300000,   // don't break anything under 5 min
  "tailBufferMs": 120000,           // no break in the last 2 min (protect the ending)
  "breakDurationMinMs": 60000,      // each break 60–90s...
  "breakDurationMaxMs": 90000,      // (or use fixed "breakDurationMs")
  "programTypes": ["episode"],      // movie | episode | track | music_video | other_video
  "strategy": "eager"               // eager = fill break with real filler clips;
}                                   // lazy = leave a flex marker filled at playback
```

**How a break is built (`buildEagerBreaks`):** the episode is split at each break point; each
break is packed with commercial clips up to the break duration via
`getFillerOfType('mid', remaining)`, then any leftover (a few seconds) becomes a tiny flex sliver.

**Live result we shipped** (ch 10/11/12/159, verified persisted): a ~22-min episode → two breaks,
each ≈ two 30s spots (~1 min) + ~5s sliver = **~2 min ads/episode, ~8–10% load**, episodes
back-to-back, **zero** dead air >2 min.

---

## 5. The genuine bugs/quirks (why slot scheduling is finicky)

### 5a. `fallback` filler needs `fillerOrder: "uniform"` or it silently produces dead air
The end-of-block `fallback` filler is requested with `slotDuration: -Infinity` ("pick anything")
in `TimeSlotService.ts`. But `WeightedFillerProgramIterator.current()` (used by
`shuffle_prefer_short` / `shuffle_prefer_long`) filters `program.duration > slotDuration → break`,
which returns **null** for `-Infinity`. Result: the fallback gap falls through to **flex (dead
air)**. Switching that filler entry to `fillerOrder: "uniform"` (which uses
`ProgramShuffleIteratorImpl`, ignoring `slotDuration`) fixes it. *This is effectively a Tunarr bug.*

### 5b. `latenessMs` voids slots, and mid-roll causes overshoot
In `TimeSlotService.ts`:
- If a program starts more than `latenessMs` past its slot's `startTime`, **the whole slot is
  voided to flex** (dead air). Tunarr's own UI default is `latenessMs: 0`.
- `remainingTimeInSlot` is computed *before* `applyMidRollBreaks` adds the ad time, so a slot
  with mid-roll **overshoots** its slot by the ad duration (~3 min). With `latenessMs: 0`, that
  overshoot voids the *next* slot → **alternating dead-air slots** (one episode, one 30-min gap).
- But a large `latenessMs` also raises the per-slot fill ceiling (`slotDuration + latenessMs`),
  so it crams *multiple* episodes into one slot. There's no clean value that gives uniform blocks
  *and* mid-roll. → uniform-blocks + mid-roll is a drift tradeoff.

### 5c. `padMs` must be `1`, not `0`, in the time-slot scheduler
`padMs: 0` breaks the grid-alignment math (`timeCursor.mod(padMs)`). The UI uses `padMs: 1`.

### 5e. Scheduled ≠ playable — local commercial clips fail to transcode at stream time (THE blocker)
This is the one that actually defeats the goal right now. The mid-roll is scheduled correctly
(verified: `filler` items in the live lineup), but when playback reaches a commercial, **Plex
shows "this stream is facing technical issues, please try again later"** and the clip never plays.

What we found inspecting the clips (`GET /api/programs/{id}/stream_details`):
- The "Commercial Breaks" list is a **`local` media source** (`name: Commercials`,
  path `/media/Commercials-2`, `mediaType: other_videos`), i.e. direct `.mkv` files — **not** Plex.
- A sample clip: video **h264, 640×480, 4:3, 29.97fps, yuv420p** (standard-def); audio **Opus**.
- The clip **probes fine** (`ffprobe` succeeds, `state: ok`) — so it's not a missing/corrupt file
  or a bad path. The failure is at **transcode/stream** time.

**ROOT CAUSE CONFIRMED (2026-06-07): the source Opus audio is malformed.** Re-encoding the clips
with ffmpeg logged **`[opus] Error parsing Opus packet header` on every single file**. The Opus
audio streams in these `.mkv` commercials are corrupt — ffmpeg can limp through with error
recovery, but Tunarr's transcoder can't decode them in the live concat → the clip dies → offline
screen. (The video h264 is fine.) Contributing factors that make it worse:
1. **Opus → AAC in MPEG-TS.** Opus isn't valid in MPEG-TS; even if it weren't corrupt it'd need
   transcoding to AAC, and the codec switch in `hls_concat` is a fragile point.
2. **SD→HD + aspect change via QSV.** Splicing a 640×480/720×480 4:3 clip into a 1920×1080 stream
   forces a scale/pad, and re-initializing **QSV hardware accel** (`hardwareAccelerationMode: qsv`)
   across the content→filler boundary is fragile. Hardware encoders are far pickier than libx264.
3. **Mixed source pipelines** — Plex-sourced content and local-file filler take different decode
   paths; concatenating them mid-stream is where it breaks.

**FIX ATTEMPTED — AND IT FAILED.** We re-encoded 20 sample clips → `Commercials-Reencoded/` as
**1920×1080 h264/yuv420p, 30fps, AAC 48k stereo** (ffmpeg `libx264 -crf 20`, scale+pillarbox pad
to 1080p) — exactly the transcode target, clean AAC, no Opus, no SD→HD scale needed. Added them as
a `local` media source ("reencoded commercials"), scanned (needed a Tunarr **restart** for the new
folder to become visible to the container — NFS/mount caching), built a filler list, and pointed
channel 159's mid-roll at it. **Result: still the exact same "this stream is facing technical
issues" offline screen.** So normalizing the clips did NOT fix it. **Conclusion: the failure is in
Tunarr's pipeline for streaming `local`-source filler concatenated into a `plex`-source program
(hls_concat + QSV), not in the clip encoding.** Possible deeper culprits we did *not* chase:
QSV hardware-decode of local files, mixed Plex+local concat in one session, or a transcode-config
issue — all Tunarr-side. The encode recipe (kept for reference, in case software transcode or a
different config is tried later):
`ffmpeg -i in.mkv -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1" -r 30 -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -profile:v high -level 4.0 -c:a aac -b:a 192k -ar 48000 -ac 2 out.mkv`

**Also tried (2026-06-07) and FAILED: Plex-sourced filler.** Added the commercials to a Plex
"Other Videos" library (Plex reports it as `type: movie` w/ Personal Media agent; Tunarr sees it as
`mediaType: other_videos`, disabled by default — enable + scan to import; needed a Tunarr Plex
"libraries/refresh" to even see it). Now both show and filler are Plex-sourced (no mixed concat).
Result was **worse** — the whole channel went "channel offline" when it hit a commercial. So source
backend isn't the issue either.

Only remaining untested idea: set the channel/transcode config to **software** (`hardwareAccelerationMode: none`)
instead of `qsv` and retry — i.e., QSV hardware encode may simply not handle the filler→content
transition. Also could check `/api/system/debug/logs` for the actual ffmpeg error during a break.
Neither pursued; commercials abandoned.

**Implication:** filler/commercial clips must be **normalized to match the transcode target**
(at minimum AAC audio; ideally pre-encoded to the same h264/AAC/resolution family), *or* the
channel must use software transcode for tolerance. A filler list that merely *scans* clean is
**not** sufficient — they have to *stream* clean in concat. This is a content-prep problem outside
Programmarr's current scope, and it's the practical reason commercials don't work end-to-end today.

### 5d. Rewriting `/programming` kills any live stream on that channel ← "channels keep breaking"
Observed live: rewriting channel 12's programming while it was streaming left it with **no
session** ("No session found for channel ID") and a **playback error in Plex**, while untouched
channels kept playing. The viewer's in-flight HLS stream is built on the old lineup; replacing
the lineup underneath it drops the stream. **Re-tuning (reselecting the channel) recovers it.**
This is the same class of problem as `create.py`'s delete-recreate breaking the Plex DVR mapping.

---

## 6. Uniform blocks & padding — possible, but heavy

To make a 22-min show occupy a clean 30-min block: time-slot schedule, 48 slots/day at
`startTime: i*1800000`, `padMs: 1`, `flexPreference: "end"`, `fillerOrder: "uniform"` for the
`fallback`. The episode plays, then a `fallback` block of commercials fills to the next :30. In
the preview lineup this produced exactly `30:00` blocks with no dead air.

**Why we abandoned it:** filling 22→30 means **~8 minutes of commercials** (27% load) — way past
"not obnoxious." 28→30 is fine (~2 min) but most sitcoms are ~22. The block model only makes
sense for shows that are already close to the block size.

> Note: this recipe was validated in the *preview* lineup (`schedule-time-slots` response). The
> materialization is identical to what `/programming type:time` would persist, but we never ran
> it live (we pivoted to mid-roll-only). If revisited, persist via `/programming` `type: "time"`.

---

## 7. What the guide (Plex EPG) shows

- The EPG comes from `GET /api/xmltv.xml` (per-channel id like `C159.159.tunarr.com`).
- **Commercials don't appear as guide entries.** The guide-builder (`TvGuideService.getChannelPrograms`
  → `push()`, + `tvGuideUtil.findMidRollAnchorIndex`) **melds** any "offline" item — which includes
  filler (`isProgramOffline` counts content-with-`fillerListId`) and flex — of duration ≤
  `TVGUIDE_MAXIMUM_PADDING_LENGTH_MS` (**30 min**) into the **preceding show**, and re-groups
  mid-roll segments back to their anchor episode.
- **Net effect:**
  - *Mid-roll only, no padding:* the guide shows episodes at ~their natural length. Because ads
    add real time the guide doesn't fully account for, **"now playing" drifts** over a long
    session (minor at ~8% load).
  - *Padded blocks:* the show + its ≤30-min filler melds into one ~30-min programme → uniform,
    accurate guide blocks.
- **Caveat on our instance:** `POST /api/xmltv/refresh` is slow and frequently **times out**;
  the XMLTV stays cached/stale for a while after a change. Verify schedules via `/programming`,
  not a quick xmltv read.

---

## 8. Capability matrix — what's actually achievable today

| Goal | Achievable? | Cost / caveat |
|------|-------------|---------------|
| **Commercials between shows (channel filler + padding)** | **✅ WORKS** | **The viable path. Verified live on 159. This is what to build.** |
| Mid-roll ads (ads *inside* a show) | ❌ Fails (QSV) | Schedules fine, but won't stream — "technical issues"/"channel offline" (§5e). Park for newer Tunarr. |
| Controlled light ad load (~3 min/episode) | ✅ Yes | `padMs` ~5-min boundary via the working path. |
| Pre-roll / post-roll (between shows) | ⚠️ Only with padding | Forces block size → heavy ad load. |
| Uniform 30-min guide blocks | ⚠️ Yes, but | ~8 min ads for a 22-min show. Needs `fillerOrder:uniform`. |
| Commercials shown in the guide | ❌ No | Melded into the show; guide is approximate. |
| Per-show "right amount" of ads | ✅ Naturally | Block size caps total ads; longer shows get fewer. |
| Apply without breaking live viewers | ❌ Not currently | Rewriting `/programming` drops the active stream. |
| Reliable "apply schedule" via slot API | ❌ Trap | `schedule-slots`/`-time-slots` are preview-only. |

---

## 9. Current state of the sandbox channels & how to revert

As of 2026-06-06, **channels 10, 11, 12, 159** carry persisted mid-roll commercials (the §4
config), pulled from the "Commercial Breaks" filler list. None are Programmarr "live" channels,
so the recipe scheduler won't touch them. **This lives only in Tunarr** — `channels.json` and the
Programmarr engine don't know about it. **The shows play; the commercials throw the offline error
(§5e), so these channels currently have a broken viewing experience until either the clips are
normalized or the mid-roll is removed.**

Tunarr/Plex state observed 2026-06-07: Tunarr healthy (all health checks green), all four
channels resolve their current Plex episode `state: ok`. Plex's "My Guide" DVR is connected and
shows **95 channels, matching Tunarr's 95** — so the channel lineup is in sync; the problem is
purely the filler clips' playability.

- **To revert a channel:** re-POST a plain schedule via `/programming` `type: random` with the
  same slots minus `filler`/`midRoll` (i.e., what `build_schedule` emits today), or redeploy via
  `create.py` (which rebuilds plain schedules and would wipe the commercials anyway).
- **159** is a throwaway experiment channel; safe to delete.

---

## 10. Implications for a Programmarr "commercials" feature

**The working design — "Enable Commercials" toggle (between-show filler, NO mid-roll):**

1. **Per-channel toggle** — `"commercials": true` in `channels.json`; a switch on the Channels
   page. Mid-roll is explicitly NOT used (it doesn't stream — §5/§5e).
2. **Two things the engine does when the toggle is on** (both verified working live on ch 159):
   - **Attach the filler list to the channel.** Set `channel.fillerCollections = [{ id:
     <commercial-list-id>, weight: 100, cooldownSeconds: 30 }]` (via the create/PUT path).
   - **Add light padding to the schedule** so a gap appears between episodes. In
     `channel_engine.build_schedule`, when opted in, set `padMs` (~`300000` = round up to the next
     5 min → ~3-min gap) and `padStyle: "episode"`, `flexPreference: "end"`. Everything else stays
     the same plain `type: random` schedule it already posts to `/programming`. **No slot filler,
     no `midRoll`.** Tunarr's `FillerPickerV2` fills the gaps at playback.
3. **Config — which filler list is "commercials":** add a `commercial_filler_list` setting to
   `config.json`, or auto-detect by name via `GET /api/filler-lists`. The list should be
   **Plex-sourced** (a Plex "Other Videos" library imported into Tunarr) — that's what we verified;
   it's also the cleaner backend. (Note: the working test used the *original* clips with malformed
   Opus, Plex-sourced — they played fine via this path, so re-encoding is NOT required. The clips'
   format was never the problem; the mid-roll splice was.)
4. **`padMs` controls the ad load** — `300000` (5-min boundary) ≈ ~3-min gap (~12%); smaller for
   lighter, larger for heavier. Avoid 30-min blocks (forces ~8 min of ads).
5. **Respect the live-stream-break constraint (§5d):** rewriting a channel's `/programming` drops
   any active viewer's stream. Toggling commercials on/off rewrites the schedule, so warn / prefer
   doing it when the channel isn't being watched.
6. **Image-affecting work** → `feature/commercials` branch per the git workflow, not straight to
   master.

> Prereq outside Programmarr (one-time, manual in Tunarr/Plex): a commercials filler list must
> exist. Easiest: a Plex "Other Videos" library of clips → enable+scan it in Tunarr → make a filler
> list from it. Programmarr could later automate "create filler list," but v1 can assume it exists.

---

## 11. Reference — endpoints, schemas, source files

**Endpoints (Tunarr 1.3.5):**
- `GET /api/filler-lists`, `GET /api/filler-lists/{id}`, `.../programs` — filler inventory
- `GET/POST /api/channels`, `GET/PUT /api/channels/{id}` — channel CRUD (PUT for `fillerCollections`)
- `POST /api/channels/{id}/programming` — **persists** a schedule (random/time/manual)
- `POST /api/channels/{id}/schedule-slots`, `.../schedule-time-slots` — **preview only**
- `GET /api/channels/{id}/now_playing`, `.../sessions`, `/api/sessions` — playback state
- `GET /api/xmltv.xml`, `POST /api/xmltv/refresh` — Plex guide (refresh is slow)
- `GET /openapi.json` — full (partial) API spec on the instance

**Channel filler field:** `fillerCollections: [{ id, weight, cooldownSeconds }]`

**Tunarr source pointers** (`C:/Users/james/Projects/Tunarr/server/src/`):
- `api/channelsApi.ts` — the preview-vs-persist proof (§2)
- `services/scheduling/TimeSlotService.ts` — slot loop, `latenessMs` voiding, mid-roll overshoot (§5b)
- `services/scheduling/slotSchedulerUtil.ts` — filler types, `applyMidRollBreaks`, `createPaddedProgram`
- `services/scheduling/SlotImpl.ts` — `getFillerOfType`
- `services/scheduling/WeightedFillerProgramIterator.ts` — the `-Infinity` fallback bug (§5a)
- `services/TvGuideService.ts` + `services/tvGuideUtil.ts` — guide melding (§7)
- `shared/src/util/constants.ts` — `SLACK: 9999`, `TVGUIDE_MAXIMUM_PADDING_LENGTH_MS: 1800000`
```
