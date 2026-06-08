# Guide + Channels Redesign — Implementation Handoff

**Status:** design approved, not yet built.
**Audience:** the engineer implementing this. Assumes familiarity with the repo's
[`CLAUDE.md`](../CLAUDE.md) (architecture, the live-channels invariants, the git/release flow).

> ## ⛔ Ground rules for the builder — read first, do not skip
>
> **`master` is production.** Every push to `master` triggers CI → GHCR → Watchtower and is **live on
> the user's server within ~5 minutes.** Do not let that happen by accident.
>
> 1. **Do all of this work on a feature branch.** If you are not already on one, create
>    `feature/guide-and-channels` and stay on it. Never commit or push to `master`.
> 2. **Commit with `/ship` only.** `/ship` commits + pushes to the *current branch* — it never touches
>    `master` and branches do **not** deploy. Use it freely as you go.
> 3. **Never run `/release`.** `/release` is the *only* path to production (it merges to `master`, tags
>    a version, and triggers the live redeploy). **That decision belongs to the repo owner, not the
>    builder.** Do not run it, and do not `git push origin master`, `git merge` into master, or tag a
>    release, even if a step seems to call for "shipping."
> 4. **Verify locally, never in prod.** Use the fast loop (`.\dev.ps1`) and the Docker parity loop
>    (`docker compose up`) against a local/test Tunarr. The §5 checklist's "ship via `/release`" line is
>    a note **for the owner** — leave it unchecked and hand the branch back when the code is done and
>    `pytest` is green.
>
> In short: **build on a branch, `/ship` often, stop before `/release`.** When you think it's done, say
> so and hand it back — don't deploy it.

This document specifies two user-facing changes and the architectural change that makes them
safe:

1. **Dashboard** shows a **TV guide** (EPG grid, like Tunarr's own Guide page) instead of the
   flat list of channel cards.
2. **Channels page** lists **what's actually deployed in Tunarr** (not `channels.json`), and lets
   the user edit channels **one at a time**, pushing each change to Tunarr with a **Save and
   Apply** button.
3. **The anti-drift model** (read this first) — the rule that keeps `channels.json` and Tunarr
   from disagreeing, which both features depend on.

Implement in the order below. Each section names the exact files/functions to touch and how to
verify it. Work on a `feature/…` branch and ship via `/release` — never straight to `master`
(see CLAUDE.md → Git Workflow).

---

## 0. The anti-drift model (architecture — read before writing code)

### The problem

`channels.json` is currently doing two incompatible jobs at once:

- a **scratchpad** for a channel-creation-in-progress (the Planner writes it), and
- the **record of what's deployed** (the Channels editor reads it).

That overlap produces two real bugs today:

- **Drift bug 1 — abandoned creation.** `compose_channels`
  (`backend/routers/pipeline_router.py:766`) does a **wholesale overwrite** — it builds a brand-new
  list and rewrites `channels.json` from scratch (lines 819–821), discarding the old contents. If
  the user composes a new lineup in the Planner and then *doesn't* finish the deploy, `channels.json`
  now describes the new lineup while Tunarr still has the old one.
- **Drift bug 2 — keep-mode drops kept channels.** When the user chooses "keep existing channels"
  on the Setup screen, deploy protects them in Tunarr via `--protect`. But `compose` has already
  rewritten `channels.json` to contain *only* the newly composed channels. After deploy Tunarr holds
  `new + kept`, while `channels.json` holds `new` only — the kept channels survive in Tunarr but
  vanish from the editor.

### The invariant

> **`channels.json` is written *only* as a consequence of a successful Tunarr push.
> Nothing changes the deployed record without changing Tunarr to match.**

`channels.json` is the record of **intent that cannot be derived from Tunarr** — content rules,
shuffle mode, the `live` flag, `commercials`, franchise `match` refs. Tunarr only stores the
deployed *result* (`{number, name, id}` + programming). So we keep `channels.json`, but we
constrain **who is allowed to write it**.

### How the invariant is enforced

| Writer | Today | After this change |
|--------|-------|-------------------|
| Planner-flow builders (`compose`, AI `validate`, `apply_collections`; `discover_prompt` reads) | read/write `channels.json` directly | read/write **`channels.draft.json`** only — never the deployed record (full inventory in §4) |
| Deploy (`create.py` via `deploy-selective`) | reads `channels.json` | reads the **draft**, pushes to Tunarr, and **on success** writes `channels.json` to mirror what Tunarr now holds |
| Per-channel **Save and Apply** (Channels page) | n/a | writes that **one** `channels.json` entry **and** patches that **one** Tunarr channel — together, never one without the other |

Because the only paths that write `channels.json` also write Tunarr, the two can't disagree.
Abandoning a creation can at worst leave a stale `channels.draft.json`, which is harmless.

**Out of scope (document, don't solve):** if the user edits a channel *inside Tunarr's own UI*,
`channels.json` won't know. Those channels surface on the Channels page as **read-only / "Not
managed by Programmarr"** (see §3). We do not attempt to reconcile hand-built Tunarr channels back
into `channels.json`.

### Reconciliation on deploy (the one subtle part)

Because `compose` no longer clobbers `channels.json`, the previous deployed record stays intact, so
reconciliation is simple:

- **Wipe mode** (user chose to replace the lineup): after a successful push, `channels.json` ←
  the **deployed set** (`deploy_temp.json` — the selected, number-remapped subset `create.py` actually
  pushed; *not* the raw draft, which may still hold deselected channels and pre-remap numbers).
- **Keep mode** (user kept channels below a number): after a successful push, `channels.json` ←
  the **kept (protected) entries** from the existing `channels.json` **merged with** the deployed set,
  keyed by channel number. Crucially, **non-protected old entries are dropped** — `create.py --protect`
  deletes those from Tunarr, so carrying them in `channels.json` would re-introduce drift. The composed
  channels are numbered above the kept ones, so collisions don't arise in practice — but merge by
  number anyway so the logic is correct regardless. (A protected channel that has no `channels.json`
  entry — e.g. one hand-built in Tunarr — simply stays an orphan: read-only on the Channels page.)

> **Precedent to reuse:** `deploy-selective` (`pipeline_router.py:894`) already stages a temp file
> (`deploy_temp.json`) and runs `create.py --json deploy_temp.json`. The draft is the same idea,
> promoted to a first-class, named file with a defined lifecycle. Lean on this pattern; don't invent
> a new deploy path.

---

## 1. Backend: `GET /api/guide`

The browser cannot fetch Tunarr's `/api/xmltv.xml` directly (cross-origin, and the Tunarr URL only
lives in server-side `config.json`). Add a backend endpoint that fetches and parses the feed.

**File:** `backend/routers/status_router.py` (alongside `tunarr_channels`, line 49). It already has
`load_config()` and the `urllib` import pattern to copy.

**Two pieces:** a **pure parse helper** (so the test needs no live Tunarr) and the **endpoint** that
fetches + calls it. Add both to `backend/routers/status_router.py` (it already imports
`json`, `urllib.request`, `urllib.error` and has `load_config()`).

**Confirmed facts about Tunarr's XMLTV** (verified against `sync_plex.py` and the real feed):
- The path is `{tunarr_url}/api/xmltv.xml`.
- Channel ids look like `C10.97.tunarr.com` — the **channel number is the leading digits after the
  `C`, before the first `.`**: `cid.split(".")[0][1:]` → `"10"` (this is exactly what
  `sync_plex.py:86` does).
- Programme timestamps look like `20260608100000 -0700` → parse with `"%Y%m%d%H%M%S %z"`.

**Step 1 — the pure parse helper** (no network; this is what the unit test calls):

```python
import xml.etree.ElementTree as ET
from datetime import datetime

def _parse_xmltv_time(s: str) -> str:
    # "20260608100000 -0700" -> ISO 8601 the browser's new Date() accepts
    return datetime.strptime(s.strip(), "%Y%m%d%H%M%S %z").isoformat()

def _num_from_cid(cid: str) -> int | None:
    # "C10.97.tunarr.com" -> 10   (mirrors sync_plex.get_tunarr_channels)
    try:
        return int(cid.split(".")[0][1:])
    except (ValueError, IndexError):
        return None

def parse_guide_xml(xml_text: str) -> dict:
    """Pure: XMLTV string -> {channels:[...], programmes:[...]}. No network. Unit-tested directly."""
    root = ET.fromstring(xml_text)

    channels = []
    for ch in root.findall("channel"):
        num = _num_from_cid(ch.get("id", ""))
        if num is None:
            continue
        name_el = ch.find("display-name")
        icon_el = ch.find("icon")
        channels.append({
            "number": num,
            "name": (name_el.text or "").strip() if name_el is not None else f"Channel {num}",
            "icon": icon_el.get("src") if icon_el is not None else None,
        })

    programmes = []
    for pr in root.findall("programme"):
        num = _num_from_cid(pr.get("channel", ""))
        if num is None:
            continue
        title_el = pr.find("title")
        sub_el = pr.find("sub-title")
        try:
            start = _parse_xmltv_time(pr.get("start", ""))
            stop = _parse_xmltv_time(pr.get("stop", ""))
        except ValueError:
            continue  # skip malformed timestamps rather than 500
        programmes.append({
            "number": num,
            "start": start,
            "stop": stop,
            "title": (title_el.text or "").strip() if title_el is not None else "",
            "episode": (sub_el.text or "").strip() if sub_el is not None else "",
        })

    channels.sort(key=lambda c: c["number"])
    return {"channels": channels, "programmes": programmes}
```

**Step 2 — the endpoint** (the only part that touches the network; mirrors `tunarr_channels`'s
defensive style):

```python
@router.get("/guide")
def get_guide():
    cfg = load_config()
    url = cfg.get("tunarr_url", "").rstrip("/")
    if not url:
        return {"channels": [], "programmes": [], "error": "Tunarr not configured"}
    try:
        with urllib.request.urlopen(f"{url}/api/xmltv.xml", timeout=10) as r:
            xml_text = r.read().decode("utf-8", errors="replace")
        return parse_guide_xml(xml_text)
    except Exception as e:
        return {"channels": [], "programmes": [], "error": f"Could not reach Tunarr: {e}"}
```

Notes:
- **Never raise** — always return the `{channels, programmes, error?}` shape so the frontend renders a
  "can't reach Tunarr" state instead of crashing.
- **No auth code here** — the global middleware in `main.py` already guards every `/api/*` route.
- If a `<programme>` has no matching `<channel>` (a number with no channel row), the frontend simply
  won't have a row to place it on; that's fine, ignore it.

**Frontend client.** In `frontend/src/api/client.ts`:
- Add types `GuideChannel { number; name; icon? }`, `GuideProgramme { number; start; stop; title; episode? }`,
  `Guide { channels: GuideChannel[]; programmes: GuideProgramme[]; error?: string }`.
- Add `getGuide: () => req<Guide>('/guide')`.

**Verify:** with the dev loop running (`.\dev.ps1`), hit `http://localhost:7979/api/guide` and
confirm channels + programmes come back with sane ISO times against your real Tunarr.

**Test:** add `backend/tests/test_guide.py`. Call `parse_guide_xml(...)` directly with a small static
XMLTV fixture string (a `<tv>` with two `<channel>`s and a couple of `<programme>`s — copy the shape
from a real `/api/xmltv.xml`). Assert: the `C10.97.tunarr.com`→`10` number extraction, the
`%Y%m%d%H%M%S %z`→ISO time conversion, the title, and that a malformed timestamp is skipped (not a
500). No live Tunarr needed — that's the whole point of the pure helper.

---

## 2. Dashboard: the guide grid

**File:** `frontend/src/pages/Dashboard.tsx`.

**Keep** the two existing sections at the top, unchanged:
- **Connections** (`ConnectionCard` × 2).
- **Auto-Updates** (`LiveRecipesCard`) — still gated on `recipes.enabled || recipes.live_count > 0`.

**Replace** the "Live Channels" `SimpleGrid` of `ChannelCard`s (lines ~251–279) with an EPG grid.

**Build a new `GuideGrid` component** (new file `frontend/src/components/GuideGrid.tsx`, or inline if
small). Match the look in `ScreenshotGUIDE.jpg`:

- **Left rail:** one row per channel — icon (when present) + number + name. Sort by number.
- **Time axis:** header row of time labels. Anchor the left edge at **now, rounded down to the
  current half-hour**. Show ~2–3 hours in the viewport; allow horizontal scroll forward as far as the
  feed provides.
- **Program blocks:** per channel, lay out programmes as blocks **sized by duration**
  (`stop - start` → width). Color them (cycle a small palette like the screenshot). Truncate the title
  with ellipsis; show full title + air time in a popover/tooltip on the block.
- **"Now" line:** a vertical line at the current time that **moves in real time** (recompute its `left`
  on a `setInterval`, e.g. every 30s).
- **Refresh:** call `api.getGuide()` on mount, on the existing Dashboard refresh button, and quietly
  on an interval (e.g. every 5 min) so the grid doesn't go stale.
- **Error / empty states:** if `guide.error` or no channels, render a card explaining Tunarr is
  unreachable or empty (reuse the existing empty-state card pattern, lines ~257–271). If Tunarr is
  *down*, this is the at-a-glance signal alongside the Connections card.

**Click-through (both features tie together here):**
- Clicking a **channel's name/icon** in the left rail → `nav(\`/channels/${number}\`)`. That route
  already deep-links the Channels editor open (see `Channels.tsx:572` — the deep-link effect, which
  §3a rewires to fetch the full entry first). No new routing needed. If the target is an orphan
  (no `channels.json` entry), the editor won't open — that's the §3a 404 fallback, not a bug.
- Clicking a **program block** → popover with title + time only; no navigation.

**Remove** the now-unused `ChannelCard` and the `getTunarrChannels()` call from Dashboard's `load()`
**if** nothing else uses them after this change (the guide endpoint supersedes the flat channel
list on this page). Leave `api.getTunarrChannels` in the client — §3 uses it.

**Verify:** Dashboard shows the grid with a live, moving "now" line; clicking a channel opens its
editor; refresh re-pulls.

---

## 3. Channels page: Tunarr-sourced list, per-channel Apply

**File:** `frontend/src/pages/Channels.tsx` (+ `client.ts`, + a new backend apply endpoint).

### 3a. List from Tunarr, back the editor with `channels.json`

- **List source = Tunarr.** Change the root `Channels` component's `load()` (line 559) to fetch the
  deployed list via `api.getTunarrChannels()` instead of `api.getChannels()`. Sort by number. This is
  the "what's actually deployed matters most" requirement.
- **Editor backing store = `channels.json`, matched by number.** This is the key rewire: today the
  list items *are* `Channel`s, so `edit()` (`Channels.tsx:579`) and the deep-link effect
  (`Channels.tsx:572`) pass a list item straight into `setEditing`. After this change the list items
  are `TunarrChannel` (`{number, name, id}` only) — they do **not** carry content/shuffle/live/
  commercials. So:
  - On click (and on deep-link open), **fetch the full entry first**: `const full = await
    api.getChannel(number)`, then `setEditing(full); open()`. The `ChannelModal` itself stays as-is —
    it already takes a `Channel` and edits content/shuffle/live/commercials; it just now receives a
    freshly-fetched entry instead of a list item.
  - The deep-link effect at `:572` currently does `const ch = channels.find(...); setEditing(ch)`.
    Change it to fetch via `getChannel(Number(number))` before opening, and keep the `openedFor` ref
    guard intact (it prevents a reload from re-opening a just-closed modal).
- **Orphans (Tunarr channel with no `channels.json` entry).** `GET /api/channels/{number}` returns 404.
  Render that row **read-only** with a **"Not managed by Programmarr"** badge and **no edit action**;
  if a 404 happens on click/deep-link, **don't open the modal** — show a brief "managed in Tunarr"
  note instead. Do not attempt to reconstruct content from Tunarr — we deliberately don't guess intent
  (shuffle/live/commercials/franchise rules can't be recovered from a deployed lineup).

### 3b. "Save and Apply" — push one channel in place

Replace the modal's current footer buttons (`Channels.tsx:448–462`) with a single primary
**Save and Apply** (keep a plain "Cancel"). On click:

1. **Save** the edited entry to `channels.json` via the existing `api.updateChannel(number, payload)`
   (`PUT /api/channels/{number}`, `channels_router.py:52`). This is the same `persist()` the modal
   already builds (line 226) — reuse it.
2. **Apply** that one channel to Tunarr **in place** via a new endpoint (§3c). On success, show the
   existing success notification and reload the list.

> The existing `saveAndSync` path (line 268) is the model — it already does "persist then run a
> scoped scheduler cycle." But `runRecipes(apply, only)` only applies to **live** channels. We need a
> path that applies **any** channel in place, so add a dedicated endpoint rather than overloading the
> recipes cycle.

### 3c. New backend endpoint: `POST /api/channels/{number}/apply`

**File:** `backend/routers/channels_router.py`.

This is the **single-channel** analogue of deploy, and it **must patch in place** — never
delete-and-recreate — to preserve the Tunarr channel id and the Plex DVR mapping (this is the
live-channels invariant; see CLAUDE.md → Live Channels, rule 1, and `channel_engine.py:398`).

This is **exactly the scheduler's per-channel cycle** (`backend/scheduler.py:183–230`), minus the
"is it live?" filter and the change-detection diff — copy that code. It applies **any** channel, live
or not. The skeleton below is adapted line-for-line from the scheduler; the only new logic is loading
one channel by number and acquiring the deploy lock so a manual apply can't race the scheduler.

```python
import channel_engine            # backend/ is on sys.path — same import style as recipes_router.py:26
import scheduler                 # shared deploy_lock (asyncio.Lock); NOT `from backend import scheduler`

@router.post("/channels/{number}/apply")
async def apply_channel(number: int):
    """Push ONE channel to Tunarr in place (preserves Tunarr id / Plex mapping). Edit-only:
    the channel must already exist in Tunarr — new channels are created in the Planner."""
    # 1. The entry must exist in channels.json (Save wrote it just before this call).
    ch = next((c for c in load().get("channels", []) if c.get("number") == number), None)
    if ch is None:
        raise HTTPException(404, f"Channel {number} not in channels.json")

    cfg = load_config()  # add a local config loader like status_router's, or import one
    tunarr_url = cfg.get("tunarr_url", "").rstrip("/")
    plex_url = cfg.get("plex_url", "").rstrip("/")
    plex_token = cfg.get("plex_token", "")
    if not tunarr_url:
        raise HTTPException(400, "Tunarr not configured")

    # blocking urllib work — run under the deploy lock, off the event loop
    def _do():
        movie_map, show_map = channel_engine.build_library_index(tunarr_url)

        plex_sections, collection_cache = [], {}
        if any(isinstance(it, dict) and "collection" in it for it in ch.get("content", [])):
            if plex_url and plex_token:
                plex_sections = channel_engine.get_plex_sections(plex_url, plex_token)

        resolved, _missing = channel_engine.resolve_content(
            ch.get("content", []), movie_map, show_map,
            plex_url=plex_url, plex_token=plex_token,
            plex_sections=plex_sections, collection_cache=collection_cache,
        )
        if not resolved:
            raise channel_engine.ChannelEngineError("resolved to empty — refusing to wipe the channel")

        # Edit-only: must already exist in Tunarr.
        if channel_engine.find_channel_by_number(tunarr_url, number) is None:
            raise channel_engine.ChannelEngineError(
                f"Channel #{number} not in Tunarr — create it in the Planner first")

        # Preserve the commercial gap (filler stays attached; pad must be re-applied each time).
        comm = ch.get("commercials") or {}
        pad_ms = int(comm.get("pad_minutes", 5)) * 60000 if comm.get("filler_list_id") else 0
        channel_engine.update_channel_in_place(
            tunarr_url, number, ch.get("shuffle", "shuffle"), resolved, pad_ms=pad_ms)
        return len(resolved)

    try:
        async with scheduler.deploy_lock:
            count = await asyncio.to_thread(_do)
        return {"ok": True, "number": number, "program_count": count}
    except channel_engine.ChannelEngineError as e:
        raise HTTPException(409, str(e))
```

Notes for the builder:
- **`load()`** and the config loader: `channels_router.py` already has `load()`. It does **not** have
  a config loader — add a small one (copy `load_config()` from `status_router.py:13`) or import it.
- **`asyncio.to_thread`** keeps the blocking `urllib` calls off the event loop. `import asyncio` at
  the top.
- **Name/number changes:** `update_channel_in_place` only rewrites *programming*. If the user renamed
  the channel or changed its number in the editor, those are channel *properties* — out of scope for
  v1 (the Tunarr list shows the current name; editing name/number can come later via a Tunarr channel
  PATCH). Confirm with the team before adding; for now, document that Save-and-Apply syncs *content*,
  not the name/number.
- **Do not** call `create.py` or any delete path here — that would change the Tunarr id and break the
  Plex mapping.
- Keep `channel_engine` on the Dockerfile `COPY` line (already there).

**Client.** Add `applyChannel: (n) => req(\`/channels/${n}/apply\`, { method: 'POST' })` to
`client.ts`.

**Verify:** edit a deployed channel's content, click Save and Apply, confirm in Tunarr that the
**same channel id** now has the new programming (id unchanged → Plex mapping intact), and that
`channels.json` matches.

---

## 4. Planner + deploy: draft file + reconciliation

This is where the invariant from §0 is actually enforced. **The rule, stated operationally:** every
Planner-flow step that builds the in-progress lineup reads/writes **`channels.draft.json`**; the
**deploy** step is the *only* writer of `channels.json`. Below is the complete inventory of
`channels.json` touchpoints in `pipeline_router.py` — every one must be handled, or drift leaks back
in through the gap.

| Touchpoint | Line | Role | Change |
|------------|------|------|--------|
| `compose_channels` | 820 (write) | Planner builds the lineup | → write **draft** (§4a) |
| `validate` (`append`) | 558–592 (read+write) | AI extras merge on top | → read+write **draft** (§4b) |
| `discover_prompt` | 615 (read) | seeds AI prompt + start number | → read **draft** (§4c) |
| `apply_collections` | 987–1014 (read+write) | Collections step appends channels | → read+write **draft** (§4d) |
| `run_deploy_selective` | 896–900 (read) | pushes to Tunarr | → read **draft**, then reconcile `channels.json` (§4e) |

`channels_router.py`'s CRUD (`get`/`put`/`update`/`delete`) and the live scheduler's
`_load_channels` keep reading/writing **`channels.json`** — they operate on the *deployed record*,
which is exactly right (the Channels page edits the deployed record and Save-and-Apply pushes Tunarr
to match; the scheduler patches already-deployed live channels). Do **not** point those at the draft.

### 4a. `compose` writes the draft, not `channels.json`

**File:** `backend/routers/pipeline_router.py`, `compose_channels` (line 766).

- Change the write target (lines 819–821) from `channels.json` to **`channels.draft.json`**.
- Nothing else in `compose` changes — it still builds the same list and returns the same summary.

### 4b. AI merge writes the draft too

**File:** `pipeline_router.py`, `validate` (line 520), the `append=True` branch (around lines
554–593).

- When `append` is true, read/merge/write **`channels.draft.json`** instead of `channels.json`, so
  the AI layer merges on top of the in-progress draft (not the deployed record). The non-append
  (full replace) branch also targets the draft.

### 4c. `discover_prompt` reads the draft

**File:** `pipeline_router.py`, `discover_prompt` (line 604), the `cpath` read at lines 615–619.

- Point `cpath` at **`channels.draft.json`** instead of `channels.json`. This endpoint seeds the AI
  prompt with the already-built lineup and computes `start = maxnum + 1`. During the Run flow the
  "already-built lineup" is the freshly-composed draft, not the previously-deployed record — read the
  draft so the prompt lists the right channels and the AI numbers its additions from the correct next
  free slot. Keep the `if cpath.exists()` fallback (empty list when there's no draft yet).

### 4d. `apply_collections` reads + writes the draft

**File:** `pipeline_router.py`, `apply_collections` (line 987), the `channels_path` read at 989–994
and write at 1012–1013.

- Point `channels_path` at **`channels.draft.json`** for both the read and the write. The Collections
  step appends collection-backed channels to the in-progress lineup before deploy, so it's a draft
  builder like compose — it must not touch the deployed record. Its "keep channels below `min_ch`"
  logic is unchanged; it just operates on the draft.
- **Collections-only flow (no compose):** the draft starts empty, so `apply_collections` keeps
  nothing of the old lineup — that's expected, not a bug. The user's existing channels are preserved
  the normal way: deploy runs in keep mode (`--protect`) and §4e's keep-mode reconciliation re-adds the
  protected `channels.json` entries. Don't "fix" this by making `apply_collections` read
  `channels.json` — that would reopen the drift hole.
- **Note:** the frontend Collections step calls this inline endpoint (`api.applyCollections` →
  `POST /pipeline/collections/apply`). The separate *streaming* `generate_from_collections.py` path
  (the `_stream("generate_from_collections.py", …)` endpoint) is the standalone/CLI route; if you wire
  the web flow to that instead, it writes `channels.json` directly and would need the same redirect —
  but as shipped the web flow uses the inline endpoint, so redirecting line 987–1014 is sufficient.

### 4e. Deploy reads the draft and reconciles `channels.json` on success

**File:** `pipeline_router.py`, `run_deploy_selective` (line 894).

Two changes: (a) read the lineup from **`channels.draft.json`** instead of `channels.json` (the
`open(channels_path…)` at line 900–901), and (b) reconcile `channels.json` **only after `create.py`
exits 0**. The streaming is the trap — the deploy runs as an SSE stream (`_locked_stream`), and the
returncode only arrives in the terminal `done` event. So the reconcile must be wired into the stream,
guarded on returncode, and must never break the stream if it throws.

**Step A — the reconcile helper** (pure file logic; easy to unit-test):

```python
def _reconcile_channels_json(protected_numbers: list[int]) -> None:
    """Write channels.json to mirror what create.py ACTUALLY pushed, then clear the staging files.

    The deployed set is deploy_temp.json — the selected, number-remapped subset that
    deploy-selective built and create.py read. Do NOT read channels.draft.json here: the draft
    may still contain channels the user DESELECTED and their PRE-remap numbers, neither of which
    is in Tunarr.
      wipe (no protected) -> channels.json = deployed set.
      keep (protected)    -> channels.json = existing merged with deployed set, keyed by number.
    Called ONLY after a successful create.py run.
    """
    deployed_path = DATA_DIR / "deploy_temp.json"     # what create.py actually pushed
    canon_path = DATA_DIR / "channels.json"
    draft_path = DATA_DIR / "channels.draft.json"

    with open(deployed_path, encoding="utf-8") as f:
        deployed = json.load(f)
    deployed_channels = deployed.get("channels", [])

    if protected_numbers:  # keep mode
        # create.py --protect KEEPS the protected channels and DELETES the other old ones.
        # So channels.json = (only the protected existing entries) + (the just-deployed set).
        # Do NOT carry over non-protected old entries — they were just deleted from Tunarr.
        protected = set(protected_numbers)
        try:
            with open(canon_path, encoding="utf-8") as f:
                existing = json.load(f).get("channels", [])
        except FileNotFoundError:
            existing = []
        by_num = {c["number"]: c for c in existing if c.get("number") in protected}
        for c in deployed_channels:        # just-deployed wins on any collision
            by_num[c["number"]] = c
        out = {**deployed, "channels": sorted(by_num.values(), key=lambda c: c["number"])}
    else:                                  # wipe mode → channels.json IS the deployed set
        out = deployed

    with open(canon_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    for p in (draft_path, deployed_path):
        p.unlink(missing_ok=True)          # next creation starts clean
```

**Step B — the SSE wrapper** that reconciles on success and forwards every chunk:

```python
async def _deploy_and_reconcile(args: list[str], protected_numbers: list[int]):
    """Stream create.py; when the terminal event reports returncode 0, reconcile
    channels.json from the just-deployed set BEFORE forwarding that event — so any client
    acting on 'done' already sees a consistent channels.json. A failed deploy never writes it."""
    async for chunk in _locked_stream("create.py", args, "deploy"):
        if chunk.startswith("data: "):
            try:
                payload = json.loads(chunk[6:].strip())
            except Exception:
                payload = None
            if payload and payload.get("type") == "done" and payload.get("returncode") == 0:
                try:
                    _reconcile_channels_json(protected_numbers)
                except Exception as e:
                    # Never break the stream; surface as a log line before 'done'.
                    yield f"data: {json.dumps({'type': 'line', 'text': f'WARNING: reconcile failed: {e}'})}\n\n"
        yield chunk
```

**Step C — wire it into `run_deploy_selective`.** Change the read source to the draft and return the
wrapper instead of `_locked_stream` directly:

```python
    draft_path = DATA_DIR / "channels.draft.json"          # was channels.json
    if not draft_path.exists():
        raise HTTPException(404, "channels.draft.json not found — compose a lineup first")
    with open(draft_path, encoding="utf-8") as f:
        data = json.load(f)
    # ... existing selection-remap + write deploy_temp.json is unchanged ...
    args = ["--json", "deploy_temp.json"]
    if req.no_delete:
        args.append("--no-delete")
    if req.protected_numbers:
        args += ["--protect", ",".join(str(n) for n in req.protected_numbers)]
    return _sse(_deploy_and_reconcile(args, req.protected_numbers))   # was _sse(_locked_stream(...))
```

Wipe vs keep is read straight off `req.protected_numbers` (empty ⇒ wipe, non-empty ⇒ keep) — the same
field the Run flow already sends from the Setup keep/wipe decision. **The non-selective `run_deploy`
path (line 876) and `run_probe` (868) are untouched** — only the Planner's `deploy-selective` flows
through the draft.

### 4f. Frontend: the Run flow is unchanged in shape

**File:** `frontend/src/pages/Run.tsx`. The stepper still calls `compose` → (optional AI) → deploy.
The only behavioral change is invisible: those steps now flow through the draft. **Verify** the
durable rules in CLAUDE.md → "Run.tsx — Pipeline Stepper UI" still hold (protection decided once on
Setup; deterministic compose; AI merges on top; deploy cascade completes).

**Tests:** update the compose/validate tests in `backend/tests/` that currently assert
`channels.json` contents — they should assert against `channels.draft.json` now. Add a unit test for
`_reconcile_channels_json` directly (no subprocess needed):
- **Keep mode:** seed an existing `channels.json` holding a **protected** channel *and* a
  **non-protected** one, plus a `deploy_temp.json` (the just-deployed set). Call
  `_reconcile_channels_json([<protected #>])` and assert the result contains the protected entry + the
  deployed channels, **the non-protected old entry is gone** (the key correctness check), and both
  `channels.draft.json` and `deploy_temp.json` were deleted.
- **Wipe mode:** call `_reconcile_channels_json([])` and assert `channels.json` exactly equals the
  deployed set.

---

## 5. Cross-cutting checklist

- [ ] **Docs in the same commit.** Update `CLAUDE.md`: the channels.json schema section (note the
      `channels.draft.json` draft + the write-only-on-deploy invariant), the API endpoints pointer in
      `docs/api.md` (add `GET /api/guide` and `POST /api/channels/{number}/apply`), and the Web UI
      Architecture notes (Dashboard now shows the guide; Channels lists Tunarr). This repo's rule:
      behavior changes update `CLAUDE.md` in the **same commit**.
- [ ] **`.gitignore`.** `channels.draft.json` and `deploy_temp.json` are user data — confirm they're
      ignored (the existing `channels*.json` glob already covers the draft; verify).
- [ ] **Dockerfile.** No new files to `COPY` for the backend (guide parsing lives in
      `status_router.py`; apply reuses `channel_engine.py`, already copied). Confirm anyway.
- [ ] **Parity loop.** Run `docker compose build && docker compose up` and click through Dashboard
      guide + Channels Save-and-Apply against a real Tunarr before `/release` (CLAUDE.md → Local
      Development).
- [ ] **Tests green.** `pytest` passes, including the new `test_guide` and the updated
      compose/validate/deploy tests.
- [ ] **Ship via `/release`** (minor version bump — new endpoints + UI). Never push image-affecting
      work straight to `master`.

---

## Appendix — file/function index

| Concern | Location |
|---------|----------|
| Wholesale `channels.json` overwrite (drift bug 1) | `backend/routers/pipeline_router.py:766` `compose_channels` (writes at 820) |
| AI merge/append | `pipeline_router.py:520` `validate` (read+write 558–592) |
| AI-extras prompt seed + start number | `pipeline_router.py:604` `discover_prompt` (reads 615) |
| Collections step (inline) | `pipeline_router.py:987` `apply_collections` (read+write 989–1013) |
| Selective deploy + temp-file precedent | `pipeline_router.py:894` `run_deploy_selective` (reads 900) |
| channels.json CRUD | `backend/routers/channels_router.py` (`load`/`save`, `get_channel:44`, `update_channel:52`) |
| Tunarr channel list | `backend/routers/status_router.py:49` `tunarr_channels` |
| XMLTV feed path + id→number map | `sync_plex.py:80` (feed), `sync_plex.py:79` `get_tunarr_channels` |
| In-place patch (preserve id) | `channel_engine.py:398` `update_channel_in_place`, `:366` `set_programming`, `:380` `read_channel_programming` |
| Per-channel sync precedent (live only) | `frontend/src/pages/Channels.tsx:268` `saveAndSync`, `backend/routers/recipes_router.py` |
| Dashboard (channel grid to replace) | `frontend/src/pages/Dashboard.tsx:251` |
| Channels page root + deep-link | `frontend/src/pages/Channels.tsx:550`, deep-link effect `:572` |
| API client | `frontend/src/api/client.ts` |
| Live-channels invariants (never recreate) | `CLAUDE.md` → Live Channels; `docs/live-channels-design.md` |
| Target look | `ScreenshotGUIDE.jpg` (repo root) |
