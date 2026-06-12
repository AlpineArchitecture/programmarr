# Playback Structure (Phase 2b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cross-media channels (franchise channels especially) get a controllable playback *structure*: **interleaved blocks** (movies in watch order, ~N episodes between consecutive movies — the new default for live franchise channels) and **timeline** (strict release order: a show's full run airs at its premiere position), selectable per channel in the Channels editor via a new optional `"playback"` field.

**Architecture:** `build_schedule` gains a `playback` parameter. Interleaved maps onto Tunarr's existing **random-slot weights** (movie slot order `chronological` weight `n_shows`; each show slot order `next` weight `episodes_per_block` → on average N episodes per movie). Timeline posts a Tunarr **manual lineup** (`{"type": "manual", "lineup": [{"type": "content", "id", "duration"}], "append": false}`) built by sorting items by premiere and flattening shows' episodes in season/episode order. The field plumbs through every schedule-building caller exactly like `commercials`/`pad_ms` does, and joins the surgical-deploy change signature.

**Tech Stack:** Python stdlib (channel_engine stays pure), FastAPI, React + Mantine v7.

**Decisions already settled:**
- Default (absent `playback`) is byte-identical to today's behavior for every channel.
- `"playback": {"structure": "interleaved", "episodes_per_block": 4}` becomes the compose default for **live franchise** channels only.
- Timeline mode ignores commercials padding in v1 (manual lineups don't auto-pad; documented).
- Per-channel and editable in the Channels editor for ANY channel; the Planner adds no new toggle in 2b.

## Verified Tunarr facts (from the Tunarr source — trust these)

- `POST /api/channels/{id}/programming` accepts a discriminated union: the existing `{"type": "random", "programs", "schedule"}` AND `{"type": "manual", "lineup": CondensedChannelProgram[], "append": bool}`.
- A manual-lineup content item: `{"type": "content", "id": "<program id>", "duration": <ms ≥ 0>}` (duration required; `icon`/`startOffsetMs` optional).
- Random-slot picks are weighted by the slot's `weight` — ratio of picks ≈ ratio of weights.
- `read_channel_programming` (ours) extracts content ids from either shape, so the scheduler's diff cycle works unchanged for manual lineups.

## Verified library-item facts

`resolved_items` (from `resolve_content`): movie item = `{"type": "Movie", "title", "programs": [p]}`; show item = `{"type": "TV", "title", "showId", "programs": [p, ...]}`. Each `p` = `{"id", "program": {...}}` where `p["program"]` carries `title`, `duration`, `releaseDate` (ms, movies), `year`, and (for episodes) season/episode numbers — **the exact episode-number field names must be verified against live Tunarr in Task 2** (`seasonNumber` and `episode` are the expected candidates).

---

### Task 1: `build_schedule` — interleaved structure

**Files:**
- Modify: `channel_engine.py` (`build_schedule`)
- Create: `backend/tests/test_playback.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_playback.py`:

```python
"""Playback structure — interleaved random-slot weighting + timeline manual lineups."""

import channel_engine


def _movie_item(title, pid, release_ms=None, duration=5400000):
    return {"type": "Movie", "title": title, "programs": [
        {"id": pid, "program": {"title": title, "releaseDate": release_ms,
                                "duration": duration, "year": 1990}}]}


def _show_item(title, show_id, episodes):
    """episodes: list of (pid, season, ep, release_ms)"""
    return {"type": "TV", "title": title, "showId": show_id, "programs": [
        {"id": pid, "program": {"title": f"{title} s{s}e{e}", "duration": 1800000,
                                "seasonNumber": s, "episode": e, "releaseDate": rms}}
        for pid, s, e, rms in episodes]}


def _slots(schedule):
    return schedule["schedule"]["slots"]


# ── interleaved ───────────────────────────────────────────────────────────────

def test_interleaved_weights_movies_vs_episode_blocks():
    items = [
        _movie_item("Movie A", "m1", 100),
        _movie_item("Movie B", "m2", 200),
        _show_item("Show X", "sx", [("e1", 1, 1, 50), ("e2", 1, 2, 60)]),
        _show_item("Show Y", "sy", [("e3", 1, 1, 70)]),
    ]
    sched = channel_engine.build_schedule(
        "ordered", items, playback={"structure": "interleaved", "episodes_per_block": 4})
    assert sched["type"] == "random"
    movie_slots = [s for s in _slots(sched) if s["type"] == "movie"]
    show_slots = [s for s in _slots(sched) if s["type"] == "show"]
    assert len(movie_slots) == 1 and len(show_slots) == 2
    assert movie_slots[0]["order"] == "chronological"
    assert movie_slots[0]["weight"] == 2          # = number of shows
    assert all(s["order"] == "next" for s in show_slots)
    assert all(s["weight"] == 4 for s in show_slots)  # = episodes_per_block


def test_interleaved_default_block_size_is_4():
    items = [_movie_item("Movie A", "m1", 100),
             _show_item("Show X", "sx", [("e1", 1, 1, 50)])]
    sched = channel_engine.build_schedule("ordered", items,
                                          playback={"structure": "interleaved"})
    show_slots = [s for s in _slots(sched) if s["type"] == "show"]
    assert show_slots[0]["weight"] == 4
    movie_slots = [s for s in _slots(sched) if s["type"] == "movie"]
    assert movie_slots[0]["weight"] == 1          # one show


def test_interleaved_movies_only_degrades_gracefully():
    items = [_movie_item("Movie A", "m1", 100)]
    sched = channel_engine.build_schedule("ordered", items,
                                          playback={"structure": "interleaved"})
    movie_slots = [s for s in _slots(sched) if s["type"] == "movie"]
    assert movie_slots[0]["order"] == "chronological"
    assert movie_slots[0]["weight"] == 1


def test_no_playback_is_byte_identical_to_today():
    items = [_movie_item("Movie A", "m1", 100),
             _show_item("Show X", "sx", [("e1", 1, 1, 50)])]
    a = channel_engine.build_schedule("ordered", items)
    b = channel_engine.build_schedule("ordered", items, playback=None)
    # uuids differ per call; compare everything except slot ids
    def strip(s):
        return {**s, "schedule": {**s["schedule"],
                "slots": [{k: v for k, v in sl.items() if k != "id"}
                          for sl in s["schedule"]["slots"]]}}
    assert strip(a) == strip(b)
    sl = strip(a)["schedule"]["slots"]
    assert all(x["weight"] == 1 for x in sl)      # today's weights untouched
```

- [ ] **Step 2: Run to verify they fail**

`.venv/bin/pytest backend/tests/test_playback.py -v` — TypeError (unexpected `playback` kwarg).

- [ ] **Step 3: Implement**

In `channel_engine.build_schedule`:
1. Signature: `def build_schedule(shuffle_type, resolved_items, pad_ms=0, playback=None):`
2. Extend the docstring: `playback` is the optional per-channel structure dict — `{"structure": "interleaved", "episodes_per_block": N}` reweights the random slots (movies chronological weight=n_shows; shows order=next weight=N, default 4) so roughly N episodes air between consecutive movies; `{"structure": "timeline"}` is handled in Task 2; `None` = unchanged legacy behavior.
3. After the existing slot-building loop (and before the return), add:

```python
    structure = (playback or {}).get("structure")
    if structure == "interleaved":
        episodes_per_block = max(1, int((playback or {}).get("episodes_per_block") or 4))
        show_slots = [s for s in slots if s["type"] == "show"]
        for s in show_slots:
            s["order"] = "next"
            s["weight"] = episodes_per_block
        for s in slots:
            if s["type"] == "movie":
                s["order"] = "chronological"
                s["weight"] = max(1, len(show_slots))
```

- [ ] **Step 4: Tests pass + full suite green**

`.venv/bin/pytest backend/tests/test_playback.py -v && .venv/bin/pytest`

- [ ] **Step 5: Commit**

```bash
git add channel_engine.py backend/tests/test_playback.py
git commit -m "feat(playback): interleaved structure — movies in watch order, episode blocks between

playback={'structure': 'interleaved', 'episodes_per_block': N} reweights the
random slots: movie slot chronological at weight n_shows, show slots 'next'
at weight N — on average N episodes between consecutive movies. Absent
playback is byte-identical to today."
```

(All commits in this plan end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.)

---

### Task 2: `build_schedule` — timeline structure (manual lineup)

**Files:**
- Modify: `channel_engine.py`
- Modify: `backend/tests/test_playback.py` (append)

- [ ] **Step 0: Verify episode field names against live Tunarr (read-only)**

The data dir has a real config: `data/config.json` → `tunarr_url`. Run a quick read-only probe:

```bash
.venv/bin/python - <<'EOF'
import json, sys
sys.path.insert(0, '.')
import channel_engine
cfg = json.load(open('data/config.json'))
_, show_map = channel_engine.build_library_index(cfg['tunarr_url'].rstrip('/'))
key = next(iter(show_map))
prog = show_map[key]['programs'][0]['program']
print(sorted(prog.keys()))
EOF
```

Look for the season/episode number field names (expected: `seasonNumber` and `episode`; report what you actually find). If they differ from the implementation below, adapt `_episode_sort_key` AND the test fixture field names to the real ones, and state the substitution in your report. If Tunarr is unreachable, proceed with `seasonNumber`/`episode` and flag it as a concern.

- [ ] **Step 1: Append failing tests**

```python
# ── timeline ──────────────────────────────────────────────────────────────────

def test_timeline_builds_manual_lineup_in_premiere_order():
    items = [
        _movie_item("Late Movie", "m2", 900),
        _show_item("Mid Show", "sx", [("e2", 1, 2, 510), ("e1", 1, 1, 500)]),
        _movie_item("Early Movie", "m1", 100),
    ]
    sched = channel_engine.build_schedule("ordered", items,
                                          playback={"structure": "timeline"})
    assert sched["type"] == "manual"
    assert sched["append"] is False
    ids = [li["id"] for li in sched["lineup"]]
    # Early Movie (100) → Mid Show premiere (500; episodes in s/e order) → Late Movie (900)
    assert ids == ["m1", "e1", "e2", "m2"]
    assert all(li["type"] == "content" for li in sched["lineup"])
    assert all(isinstance(li["duration"], int) and li["duration"] > 0
               for li in sched["lineup"])


def test_timeline_show_without_releasedate_sorts_by_year_then_end():
    items = [
        _movie_item("Movie 1990", "m1", 700000000000),  # ~1992 in ms — fine, just ordered
        {"type": "TV", "title": "Undated Show", "showId": "sz", "programs": [
            {"id": "z1", "program": {"title": "Undated s1e1", "duration": 1800000,
                                     "seasonNumber": 1, "episode": 1,
                                     "releaseDate": None, "year": None}}]},
    ]
    sched = channel_engine.build_schedule("ordered", items,
                                          playback={"structure": "timeline"})
    ids = [li["id"] for li in sched["lineup"]]
    assert ids == ["m1", "z1"]  # undated content sorts to the end, never crashes


def test_timeline_empty_items_returns_none():
    assert channel_engine.build_schedule(
        "ordered", [], playback={"structure": "timeline"}) is None
```

- [ ] **Step 2: Verify they fail, then implement**

In `channel_engine.py`, add two helpers above `build_schedule` and a branch at the TOP of `build_schedule` (after the `all_programs` empty check):

```python
def _episode_sort_key(p):
    prog = p.get("program", {})
    return (prog.get("seasonNumber") or 0, prog.get("episode") or 0)


def _item_premiere_ms(item):
    """Premiere timestamp for timeline ordering: a movie's releaseDate; a show's
    earliest episode releaseDate (fallback: Jan 1 of its year). Unknown → +inf
    (sorts to the end, deterministically by title)."""
    progs = item.get("programs") or []
    dates = [p.get("program", {}).get("releaseDate") for p in progs]
    dates = [d for d in dates if d is not None]
    if dates:
        return min(dates)
    years = [p.get("program", {}).get("year") for p in progs]
    years = [y for y in years if y]
    if years:
        from datetime import datetime, timezone
        return datetime(min(years), 1, 1, tzinfo=timezone.utc).timestamp() * 1000
    return float("inf")
```

(Put the `datetime` import at module top if channel_engine already imports it — check; otherwise the local import is fine, match file style.)

In `build_schedule`, right after the `if not all_programs: return None` guard:

```python
    if (playback or {}).get("structure") == "timeline":
        # Strict release order as ONE looping manual lineup: each item at its
        # premiere position; a show's full run plays there in season/episode order.
        # Manual lineups don't auto-pad, so commercials padding is ignored here (v1).
        lineup = []
        for item in sorted(resolved_items,
                           key=lambda it: (_item_premiere_ms(it),
                                           (it.get("title") or "").lower())):
            programs = item["programs"]
            if item["type"] == "TV":
                programs = sorted(programs, key=_episode_sort_key)
            for p in programs:
                lineup.append({"type": "content", "id": p["id"],
                               "duration": int(p.get("program", {}).get("duration") or 0) or 1})
        return {"type": "manual", "lineup": lineup, "append": False}
```

(Note the `or 1` floor: Tunarr's base schema requires positive duration; a missing duration must not produce 0.)

- [ ] **Step 3: Tests pass + full suite green; commit**

```bash
git add channel_engine.py backend/tests/test_playback.py
git commit -m "feat(playback): timeline structure — strict release order as a manual lineup

{'structure': 'timeline'} posts a Tunarr manual lineup: items sorted by
premiere (movie releaseDate; show's earliest episode date, year fallback),
shows flattened in season/episode order at their premiere position. The
scheduler diff is unaffected — read_channel_programming already extracts
content ids from manual lineups. Commercials padding is a no-op here (v1)."
```

---

### Task 3: Plumb `playback` through every schedule-building caller

**Files:**
- Modify: `channel_engine.py` (`update_channel_in_place`, `classify_channels`'s `_content_sig`)
- Modify: `create.py`, `backend/scheduler.py`, `backend/routers/channels_router.py`, `backend/routers/pipeline_router.py`
- Modify: `backend/tests/test_playback.py` (append) and `backend/tests/test_surgical_deploy.py` (append)

- [ ] **Step 1: Append failing tests**

To `backend/tests/test_playback.py`:

```python
# ── plumbing ──────────────────────────────────────────────────────────────────

def test_update_channel_in_place_passes_playback(monkeypatch):
    captured = {}
    monkeypatch.setattr(channel_engine, "find_channel_by_number",
                        lambda url, n: {"id": "tid", "name": "X"})
    monkeypatch.setattr(channel_engine, "set_programming",
                        lambda url, cid, payload: captured.update(payload=payload) or {})
    items = [_movie_item("Movie A", "m1", 100),
             _show_item("Show X", "sx", [("e1", 1, 1, 50)])]
    channel_engine.update_channel_in_place(
        "http://t", 5, "ordered", items,
        playback={"structure": "timeline"}, expected_name="X")
    assert captured["payload"]["type"] == "manual"
```

To `backend/tests/test_surgical_deploy.py` (read its existing classify tests and mirror their style — these are the behavioral requirements):

```python
def test_playback_change_lands_in_update_bucket():
    deployed = [{"number": 1, "name": "Saga", "shuffle": "ordered",
                 "content": ["A"], "live": True}]
    desired = [{"number": 1, "name": "Saga", "shuffle": "ordered",
                "content": ["A"], "live": True,
                "playback": {"structure": "timeline"}}]
    out = channel_engine.classify_channels(desired, deployed, {"saga"})
    assert [c["name"] for c in out["update"]] == ["Saga"]
    assert out["unchanged"] == []
```

(Adapt the call convention — `classify_channels` may take lists of dicts exactly like this; check the existing tests. The requirement: a playback-only difference is a change, not unchanged.)

- [ ] **Step 2: Verify failures, then implement**

1. `update_channel_in_place(tunarr_url, number, shuffle, resolved, pad_ms=0, expected_name=None, playback=None)` → pass `playback=playback` to its `build_schedule` call. Extend its docstring's pad_ms paragraph with one sentence: `playback` (the per-channel structure dict) must be re-applied on live updates for the same reason as pad_ms.
2. `classify_channels`'s `_content_sig`: add a fourth element `json.dumps(ch.get("playback") or {}, sort_keys=True)`.
3. `create.py`: at its `build_schedule(...)` call, add `playback=ch.get("playback")` (find how `ch` is named in that loop — it reads `commercials` nearby; mirror it).
4. `backend/scheduler.py` `_run_cycle_blocking`: the `update_channel_in_place(...)` call adds `playback=ch.get("playback")` (next to `pad_ms`).
5. `backend/routers/channels_router.py` `apply_channel._do()`: same addition to its `update_channel_in_place(...)` call.
6. `backend/routers/pipeline_router.py` surgical `_do_update`: same addition (the channel dict there is the desired entry — find its name).

- [ ] **Step 3: All green; commit**

```bash
git add channel_engine.py create.py backend/scheduler.py backend/routers/channels_router.py backend/routers/pipeline_router.py backend/tests/test_playback.py backend/tests/test_surgical_deploy.py
git commit -m "feat(playback): plumb the per-channel playback field through every deploy path

update_channel_in_place, create.py, the scheduler cycle, apply, and surgical
deploy all forward channels.json's optional playback dict (mirroring the
commercials/pad_ms pattern), and a playback-only edit now registers as a
change in the surgical diff."
```

---

### Task 4: Compose defaults live franchise channels to interleaved

**Files:**
- Modify: `backend/routers/pipeline_router.py` (the live-franchise branch added in Phase 2a)
- Modify: `backend/tests/test_compose.py` (extend the live-franchise test)

- [ ] **Step 1: Extend the existing test**

In `test_compose_live_franchise_emits_franchise_ref` (added in Phase 2a), append an assertion:

```python
    assert ch["playback"] == {"structure": "interleaved", "episodes_per_block": 4}
```

(`ch` = the draft channel the test already asserts on; adapt the variable name.) Run — it must fail.

- [ ] **Step 2: Implement**

In the live-franchise branch in `compose_channels` (the one setting `per_channel_extras["live"] = True`), add:

```python
                per_channel_extras["playback"] = {"structure": "interleaved",
                                                  "episodes_per_block": 4}
```

Static fallback and non-live paths get NO playback key.

- [ ] **Step 3: All green; commit**

```bash
git add backend/routers/pipeline_router.py backend/tests/test_compose.py
git commit -m "feat(planner): live franchise channels default to interleaved playback

Movies in watch order with ~4-episode blocks between — the cross-media
franchise experience decided in the design session. Editable per channel
in the Channels editor; static channels unchanged."
```

---

### Task 5: Channels-editor Playback section

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/Channels.tsx` (`ChannelModal`)

READ both regions first. Verify with `cd frontend && npx tsc --noEmit && npm run build`.

- [ ] **Step 1: client.ts**

```ts
export interface PlaybackSetting { structure: 'interleaved' | 'timeline'; episodes_per_block?: number }
```

and `playback?: PlaybackSetting;` on the `Channel` interface.

- [ ] **Step 2: ChannelModal**

State (next to the commercials/icon state):

```tsx
// Playback structure
const [pbStructure, setPbStructure] = useState<string>('default');
const [pbEpisodes, setPbEpisodes] = useState<string | number>(4);
```

Load-effect (where `channel.commercials` / `channel.icon` are read):

```tsx
setPbStructure(channel.playback?.structure ?? 'default');
setPbEpisodes(channel.playback?.episodes_per_block ?? 4);
```

(And the fresh-channel reset branch, if one exists: back to `'default'` / `4`.)

In `persist()`, where the payload is assembled (after commercials):

```tsx
if (pbStructure === 'interleaved') {
  payload.playback = { structure: 'interleaved', episodes_per_block: Number(pbEpisodes) || 4 };
} else if (pbStructure === 'timeline') {
  payload.playback = { structure: 'timeline' };
}
// 'default' → no playback key at all
```

JSX after the Commercials block (before the icon section added in the icon overhaul):

```tsx
<Divider label="Playback structure" labelPosition="left" />
<Select
  size="xs"
  value={pbStructure}
  onChange={(v) => setPbStructure(v ?? 'default')}
  data={[
    { value: 'default', label: 'Standard (use shuffle setting)' },
    { value: 'interleaved', label: 'Interleaved — movies in order, episode blocks between' },
    { value: 'timeline', label: 'Timeline — strict release order' },
  ]}
/>
{pbStructure === 'interleaved' && (
  <NumberInput size="xs" label="Episodes per block" min={1} max={12}
               value={pbEpisodes} onChange={setPbEpisodes} />
)}
{pbStructure === 'timeline' && (
  <Text size="xs" c="dimmed">Commercial padding is not applied in timeline mode.</Text>
)}
```

`Select` is already imported in Channels.tsx; `NumberInput` may need adding to the Mantine import. Adapt placement/props to the surrounding code.

- [ ] **Step 3: Verify + commit**

```bash
cd frontend && npx tsc --noEmit && npm run build && cd ..
git add frontend/src/api/client.ts frontend/src/pages/Channels.tsx
git commit -m "feat(channels): per-channel playback structure control in the editor

Standard / interleaved (with episodes-per-block) / timeline, persisted as
the optional playback field and pushed via Save and Apply."
```

---

### Task 6: Docs

**Files:**
- Modify: `CLAUDE.md` (channels.json schema section + Live Channels)
- Modify: `docs/live-channels-design.md` (append to the Phase 2a section)

- [ ] **Step 1: CLAUDE.md — channels.json schema section**

After the **Icon pin (optional).** paragraph, add:

```markdown
**Playback structure (optional).** `"playback": {"structure": "interleaved"|"timeline",
"episodes_per_block": 4}` controls cross-media scheduling: *interleaved* keeps movies in
watch order with ~N-episode blocks between (random-slot weights); *timeline* posts a manual
Tunarr lineup in strict release order (show runs air at their premiere position; commercials
padding is a no-op there). Absent = today's shuffle behavior. Live franchise channels compose
with interleaved/4 by default; editable per channel in the Channels editor.
```

- [ ] **Step 2: CLAUDE.md — Live Channels franchise block**

Append one sentence to the franchise content-ref paragraph: "Live franchise channels carry `playback: interleaved` by default (see channels.json schema)."

- [ ] **Step 3: docs/live-channels-design.md** — append to the "Franchise refs (Phase 2a…)" section:

```markdown
### Playback structure (Phase 2b)

Interleaved = random-slot weighting (movie slot chronological at weight n_shows, show slots
"next" at weight N) — an average-N approximation, accepted over exact alternation because it
reuses Tunarr's scheduler verbatim. Timeline = manual lineup (the only Tunarr type that can
express strict cross-media release order); the live diff is unaffected because
read_channel_programming extracts content ids from either lineup shape. Rejected: exact
movie/episode alternation via generated manual lineups for interleaved too (loses Tunarr's
rolling-window randomization and 30-day horizon for no user-visible gain).
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/live-channels-design.md
git commit -m "docs: playback structure — interleaved + timeline, channels.json field"
```

---

### Task 7: Final verification (orchestrator)

- [ ] Full `pytest`; frontend tsc + build.
- [ ] Live smoke (read-only): build a timeline + an interleaved schedule from real resolved items and inspect the payloads.
- [ ] Windows-side docker build + user review/merge.

## Self-review notes

- Absent-`playback` byte-identity is tested (Task 1) — the no-regression guarantee.
- Naming: `playback`, `structure`, `episodes_per_block`, `_episode_sort_key`, `_item_premiere_ms` consistent across tasks.
- The surgical `_content_sig` addition (Task 3) is what makes editor playback edits actually deploy on the next surgical pass.
- Timeline + commercials interaction documented as a v1 no-op in three places (code comment, editor hint, CLAUDE.md).
