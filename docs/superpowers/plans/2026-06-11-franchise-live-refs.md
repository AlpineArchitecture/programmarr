# Franchise Live Content-Refs (Phase 2a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A franchise channel can be marked "Keep updated" in the Planner: it deploys as a **live** channel whose content is a new identity-based content-ref — `{"match": "franchise", "name": "…"}` — re-resolved each scheduler cycle from the TMDB/Wikidata franchise caches, so a newly added sequel lands on the channel automatically (by membership, not name matching — MCU works even though no member is named "MCU").

**Architecture:** Two new pure functions in `channel_engine.py` (`load_franchise_index`, `match_franchise`) mirror the existing `match_titles` machinery; `resolve_content` gains a third ref type and an optional `franchise_index` parameter. Every consumer (scheduler cycle, `create.py`, apply endpoint, surgical deploy, recipes preview) passes the index in. `POST /pipeline/compose` emits the live ref when the Planner card's new "Keep updated" switch is on, computing `exclude` from unchecked members. Cross-media comes free: Wikidata cache members already span movies and TV, and `match_franchise` resolves against both maps.

**Tech Stack:** Python 3 stdlib only (channel_engine stays pure), FastAPI/pydantic, React + Mantine v7.

**Decisions already settled (do not relitigate):**
- Ref schema: `{"match": "franchise", "name": "<franchise display name>", "order": "release_date"|null, "exclude": ["title", …]}`. Name-keyed (normalized) against the franchise index — the caches are the identity source; no TMDB/Wikidata IDs in the ref.
- All live-channel invariants hold: update-in-place only, Tunarr is the source of truth, name-match guard. The franchise ref changes only *resolution*, which is upstream of all that.
- The Planner card (members listed with checkboxes) IS the author-time preview + human confirmation for this ref type — equivalent to the `title_contains` preview rule.
- Cache freshness stays with the existing scan triggers (Planner mount / `?refresh=1`). The scheduler does NOT trigger scans in 2a — a sequel appears after the next scan refresh; documented behavior.
- If the cache has no entry for a franchise at compose time, compose falls back to a static (non-live) channel with the checked titles — never a live channel that would resolve to empty.
- Playback structure (interleaved blocks / timeline) is **Phase 2b** — not in this plan.

---

## Verified shapes (from the live codebase — trust these)

`data/tmdb_enrichment.json`:
```json
{"sig": "…", "enrichment": {"<title>": {"title": "…", "year": 1987, "collection": {"id": 123, "name": "Die Hard Collection"} , "keywords": [...]}}}
```
(`collection` may be `null`.)

`data/wikidata_cache.json`:
```json
{"sig": "…", "franchises": [{"name": "…", "source": "wikidata", "members": [{"title": "…", "year": 1999, "type": "Movie"|"TV"}]}]}
```

Library index items (what resolution must return — see `match_titles` in `channel_engine.py`):
- `movie_map[key]` = raw Tunarr program `p`; resolved item = `{"type": "Movie", "title": title, "programs": [p]}` with `p["program"]["releaseDate"]` (ms) and `p["program"]["year"]`.
- `show_map[key]` = `{"title", "showId", "programs"}`; resolved item = `{"type": "TV", "title", "showId", "programs"}`.

`backend/tests/conftest.py` puts repo root + backend/ on sys.path; run tests with `.venv/bin/pytest` from the repo root.

---

### Task 1: `channel_engine` — franchise index + matcher

**Files:**
- Modify: `channel_engine.py` (insert after the `match_titles` function, in the "Franchise matching (live recipes)" section)
- Create: `backend/tests/test_franchise_refs.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_franchise_refs.py`:

```python
"""Franchise content-ref machinery — load_franchise_index + match_franchise.

Pure logic against seeded temp caches and fabricated library maps. No network."""

import json

import channel_engine


# ── fixtures ──────────────────────────────────────────────────────────────────

def _seed_caches(tmp_path, tmdb_collections=None, wikidata_franchises=None):
    """Write minimal cache files in the shapes the Planner scans produce."""
    enrichment = {}
    for coll_id, coll_name, titles in (tmdb_collections or []):
        for t in titles:
            enrichment[t] = {"title": t, "year": 2000,
                             "collection": {"id": coll_id, "name": coll_name},
                             "keywords": []}
    (tmp_path / "tmdb_enrichment.json").write_text(
        json.dumps({"sig": "x", "enrichment": enrichment}))
    (tmp_path / "wikidata_cache.json").write_text(
        json.dumps({"sig": "x", "franchises": wikidata_franchises or []}))
    return tmp_path


def _movie(title, release_ms=None, year=None):
    return {"program": {"title": title, "releaseDate": release_ms, "year": year}}


def _maps():
    movie_map = {
        "die hard": _movie("Die Hard", 600000000000, 1988),
        "die hard 2": _movie("Die Hard 2", 650000000000, 1990),
        "unrelated": _movie("Unrelated", 1, 1970),
    }
    show_map = {
        "star trek": {"title": "Star Trek", "showId": "st-1",
                      "programs": [{"program": {"year": 1966}}]},
    }
    return movie_map, show_map


# ── load_franchise_index ──────────────────────────────────────────────────────

def test_index_groups_tmdb_collections(tmp_path):
    _seed_caches(tmp_path, tmdb_collections=[
        (1, "Die Hard Collection", ["Die Hard", "Die Hard 2"]),
    ])
    idx = channel_engine.load_franchise_index(tmp_path)
    assert idx["die hard collection"]["name"] == "Die Hard Collection"
    assert sorted(idx["die hard collection"]["titles"]) == ["Die Hard", "Die Hard 2"]


def test_index_includes_wikidata_and_tmdb_wins_collisions(tmp_path):
    _seed_caches(
        tmp_path,
        tmdb_collections=[(1, "Star Trek", ["Star Trek: First Contact"])],
        wikidata_franchises=[
            {"name": "Star Trek", "source": "wikidata",
             "members": [{"title": "Star Trek", "year": 1966, "type": "TV"}]},
            {"name": "Tremors", "source": "wikidata",
             "members": [{"title": "Tremors", "year": 1990, "type": "Movie"}]},
        ])
    idx = channel_engine.load_franchise_index(tmp_path)
    assert idx["star trek"]["titles"] == ["Star Trek: First Contact"]  # TMDB wins
    assert idx["tremors"]["titles"] == ["Tremors"]                     # wikidata-only kept


def test_index_empty_when_caches_absent(tmp_path):
    assert channel_engine.load_franchise_index(tmp_path) == {}


# ── match_franchise ───────────────────────────────────────────────────────────

def test_match_franchise_resolves_members_by_identity(tmp_path):
    idx = channel_engine.load_franchise_index(_seed_caches(tmp_path, tmdb_collections=[
        (1, "Die Hard Collection", ["Die Hard", "Die Hard 2", "Not In Library"]),
    ]))
    movie_map, show_map = _maps()
    resolved, preview = channel_engine.match_franchise(
        "Die Hard Collection", idx, movie_map, show_map, order="release_date")
    assert [r["title"] for r in resolved] == ["Die Hard", "Die Hard 2"]
    assert preview == [{"title": "Die Hard", "year": 1988},
                       {"title": "Die Hard 2", "year": 1990}]


def test_match_franchise_is_cross_media(tmp_path):
    idx = channel_engine.load_franchise_index(_seed_caches(
        tmp_path,
        wikidata_franchises=[{"name": "Star Trek", "source": "wikidata", "members": [
            {"title": "Star Trek", "year": 1966, "type": "TV"},
            {"title": "Die Hard", "year": 1988, "type": "Movie"},  # contrived: proves both maps
        ]}]))
    movie_map, show_map = _maps()
    resolved, _ = channel_engine.match_franchise("Star Trek", idx, movie_map, show_map,
                                                 order="release_date")
    types = {r["type"] for r in resolved}
    assert types == {"Movie", "TV"}
    assert resolved[-1]["type"] == "TV"  # shows sort to the end in release order


def test_match_franchise_exclude_and_unknown(tmp_path):
    idx = channel_engine.load_franchise_index(_seed_caches(tmp_path, tmdb_collections=[
        (1, "Die Hard Collection", ["Die Hard", "Die Hard 2"]),
    ]))
    movie_map, show_map = _maps()
    resolved, _ = channel_engine.match_franchise(
        "Die Hard Collection", idx, movie_map, show_map, exclude=["die hard 2"])
    assert [r["title"] for r in resolved] == ["Die Hard"]
    assert channel_engine.match_franchise("Nope", idx, movie_map, show_map) == ([], [])
    assert channel_engine.match_franchise("Nope", None, movie_map, show_map) == ([], [])
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest backend/tests/test_franchise_refs.py -v`
Expected: `AttributeError: ... 'load_franchise_index'`.

- [ ] **Step 3: Implement in `channel_engine.py`**

Insert after `match_titles` (keep the section banner comment context):

```python
def _norm_franchise_name(name):
    return " ".join((name or "").lower().split())


def load_franchise_index(data_dir):
    """Franchise membership from the Planner's caches, keyed by normalized name.

    {norm_name: {"name": display_name, "titles": [member title, ...]}}
    Sources: data_dir/wikidata_cache.json (series/franchise members, spans movies
    and TV) and data_dir/tmdb_enrichment.json (belongs_to_collection groups).
    TMDB wins name collisions (its collection data is more precise — same rule as
    the Planner's _merge_franchises). Best-effort: a missing/corrupt cache simply
    contributes nothing; worst case is {}.
    """
    index = {}

    try:
        with open(os.path.join(str(data_dir), "wikidata_cache.json"), encoding="utf-8") as f:
            for fr in (json.load(f).get("franchises") or []):
                name = (fr.get("name") or "").strip()
                titles = [m.get("title") for m in fr.get("members") or [] if m.get("title")]
                if name and titles:
                    index[_norm_franchise_name(name)] = {"name": name, "titles": titles}
    except (OSError, ValueError):
        pass

    try:
        with open(os.path.join(str(data_dir), "tmdb_enrichment.json"), encoding="utf-8") as f:
            enrichment = json.load(f).get("enrichment") or {}
        buckets = {}
        for title, rec in enrichment.items():
            coll = rec.get("collection") or {}
            coll_id, coll_name = coll.get("id"), (coll.get("name") or "").strip()
            if coll_id and coll_name:
                buckets.setdefault(coll_id, {"name": coll_name, "titles": []})["titles"].append(title)
        for b in buckets.values():
            index[_norm_franchise_name(b["name"])] = b  # TMDB overwrites → wins
    except (OSError, ValueError):
        pass

    return index


def match_franchise(name, franchise_index, movie_map, show_map, order=None, exclude=None):
    """Resolver for {"match": "franchise"} content refs.

    Identity-based: members come from the cached TMDB/Wikidata franchise data
    (load_franchise_index), NOT from name matching — so a franchise channel works
    even when members share no words with the franchise name (MCU → "Iron Man").
    Returns (resolved_items, preview) exactly like match_titles. Unknown
    franchise or missing index → ([], []) — callers treat that as "matched
    nothing" and refuse to wipe live channels downstream.
    """
    entry = (franchise_index or {}).get(_norm_franchise_name(name))
    if not entry:
        return [], []

    exclude_set = {e.lower().strip() for e in (exclude or [])}
    matched = []  # (sort_release_ms, year, title, item) — same shape as match_titles

    for member_title in entry["titles"]:
        key = (member_title or "").lower().strip()
        if not key or key in exclude_set:
            continue
        p = movie_map.get(key)
        if p is not None:
            prog = p.get("program", {})
            release_ms = prog.get("releaseDate")
            title = prog.get("title", member_title)
            matched.append((
                release_ms if release_ms is not None else float("inf"),
                prog.get("year"), title,
                {"type": "Movie", "title": title, "programs": [p]},
            ))
            continue
        s = show_map.get(key)
        if s is not None:
            first_prog = s["programs"][0].get("program", {}) if s.get("programs") else {}
            matched.append((
                float("inf"),  # shows have no single release date — sort to the end
                first_prog.get("year"), s["title"],
                {"type": "TV", "title": s["title"], "showId": s["showId"], "programs": s["programs"]},
            ))

    if order == "release_date":
        matched.sort(key=lambda t: (t[0], t[2].lower()))
    else:
        matched.sort(key=lambda t: t[2].lower())

    return [t[3] for t in matched], [{"title": t[2], "year": t[1]} for t in matched]
```

Check `channel_engine.py`'s imports: `json` and `os` must be imported at the top (add whichever is missing, matching import style).

- [ ] **Step 4: Run tests — all pass**

Run: `.venv/bin/pytest backend/tests/test_franchise_refs.py -v && .venv/bin/pytest`
Expected: new file green; full suite green.

- [ ] **Step 5: Commit**

```bash
git add channel_engine.py backend/tests/test_franchise_refs.py
git commit -m "feat(live): franchise index + identity-based matcher in channel_engine

load_franchise_index reads the Planner's TMDB/Wikidata caches into a
name-keyed membership map; match_franchise resolves a franchise's members
against the Tunarr library (movies AND shows — cross-media comes free from
Wikidata membership). Mirrors match_titles' contract so downstream code
treats both ref types identically."
```

(Append the `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` line to every commit in this plan.)

---

### Task 2: `resolve_content` learns the franchise ref + `create.py` passes the index

**Files:**
- Modify: `channel_engine.py` (`resolve_content`)
- Modify: `create.py` (its `resolve_content` call site)
- Modify: `backend/tests/test_franchise_refs.py` (append)

- [ ] **Step 1: Append failing tests**

```python
# ── resolve_content franchise refs ────────────────────────────────────────────

def test_resolve_content_franchise_ref(tmp_path):
    idx = channel_engine.load_franchise_index(_seed_caches(tmp_path, tmdb_collections=[
        (1, "Die Hard Collection", ["Die Hard", "Die Hard 2"]),
    ]))
    movie_map, show_map = _maps()
    content = [{"match": "franchise", "name": "Die Hard Collection",
                "order": "release_date", "exclude": []}]
    resolved, missing = channel_engine.resolve_content(
        content, movie_map, show_map, franchise_index=idx)
    assert [r["title"] for r in resolved] == ["Die Hard", "Die Hard 2"]
    assert missing == []


def test_resolve_content_franchise_ref_unknown_is_missing(tmp_path):
    movie_map, show_map = _maps()
    content = [{"match": "franchise", "name": "Nope"}]
    resolved, missing = channel_engine.resolve_content(
        content, movie_map, show_map, franchise_index={})
    assert resolved == []
    assert missing == ["[franchise:Nope]"]


def test_resolve_content_franchise_ref_without_index_is_missing():
    movie_map, show_map = _maps()
    content = [{"match": "franchise", "name": "Die Hard Collection"}]
    resolved, missing = channel_engine.resolve_content(content, movie_map, show_map)
    assert resolved == []
    assert missing == ["[franchise:Die Hard Collection]"]


def test_resolve_content_mixes_franchise_ref_with_plain_titles(tmp_path):
    idx = channel_engine.load_franchise_index(_seed_caches(tmp_path, tmdb_collections=[
        (1, "Die Hard Collection", ["Die Hard"]),
    ]))
    movie_map, show_map = _maps()
    content = ["Unrelated", {"match": "franchise", "name": "Die Hard Collection"}]
    resolved, missing = channel_engine.resolve_content(
        content, movie_map, show_map, franchise_index=idx)
    assert sorted(r["title"] for r in resolved) == ["Die Hard", "Unrelated"]
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `.venv/bin/pytest backend/tests/test_franchise_refs.py -v`

- [ ] **Step 3: Implement**

In `channel_engine.resolve_content`:
1. Signature: add keyword param `franchise_index=None` (after `collection_cache=None`).
2. In the `elif isinstance(entry, dict) and "match" in entry:` branch, BEFORE the existing `title_contains` handling, add:

```python
            if entry["match"] == "franchise" and entry.get("name"):
                fr_name = entry["name"]
                items, _ = match_franchise(fr_name, franchise_index, movie_map, show_map,
                                           order=entry.get("order"), exclude=entry.get("exclude"))
                if items:
                    matched_items.extend(items)
                    print(f"    Franchise '{fr_name}': {len(items)} titles")
                else:
                    print(f"    WARNING: franchise '{fr_name}' matched nothing (cache missing or no library members)")
                    missing.append(f"[franchise:{fr_name}]")
                continue
```

(Adjust to the branch's actual structure — the existing code uses if/else on `entry["match"] == "title_contains"`; restructure minimally so franchise is checked first and the existing title_contains and unsupported-ref paths are untouched. Update the function's docstring to mention all three ref types.)

In `create.py`: find its `resolve_content(...)` call. Before the channel loop, add `franchise_index = channel_engine.load_franchise_index(".")` (create.py runs with cwd = data dir) and pass `franchise_index=franchise_index` at the call site. If create.py has more than one resolve_content call, update all of them.

- [ ] **Step 4: Run tests — all pass; full suite green**

Run: `.venv/bin/pytest backend/tests/test_franchise_refs.py -v && .venv/bin/pytest`

- [ ] **Step 5: Commit**

```bash
git add channel_engine.py create.py backend/tests/test_franchise_refs.py
git commit -m "feat(live): resolve_content learns {\"match\": \"franchise\"} refs

Third content-ref type, resolved identity-based via the franchise index.
Missing index or unknown franchise degrades to a missing-entry warning —
downstream refuse-to-wipe guards keep live channels safe. create.py loads
and passes the index (cwd is the data dir)."
```

---

### Task 3: Backend callers pass the index (scheduler, apply, surgical deploy)

**Files:**
- Modify: `backend/scheduler.py` (`_run_cycle_blocking`)
- Modify: `backend/routers/channels_router.py` (`apply_channel`)
- Modify: `backend/routers/pipeline_router.py` (the surgical-deploy update path's `resolve_content` call)
- Modify: `backend/tests/test_franchise_refs.py` (append)

- [ ] **Step 1: Find every `resolve_content(` call site in backend/**

Run: `grep -rn "resolve_content(" backend/ create.py | grep -v test`
Every backend call site must pass `franchise_index=...`.

- [ ] **Step 2: Append a failing test (scheduler-style resolution)**

```python
# ── callers build and pass the index ──────────────────────────────────────────

def test_scheduler_cycle_resolves_franchise_refs(tmp_path, monkeypatch):
    """The scheduler's resolve path must hand the franchise index to
    resolve_content — proven by resolving a live franchise channel end-to-end
    through scheduler._run_cycle_blocking with all I/O stubbed."""
    import scheduler

    _seed_caches(tmp_path, tmdb_collections=[
        (1, "Die Hard Collection", ["Die Hard", "Die Hard 2"]),
    ])
    movie_map, show_map = _maps()

    (tmp_path / "config.json").write_text(json.dumps({"tunarr_url": "http://t"}))
    (tmp_path / "channels.json").write_text(json.dumps({"channels": [{
        "number": 7, "name": "Die Hard 24/7", "shuffle": "ordered", "live": True,
        "content": [{"match": "franchise", "name": "Die Hard Collection",
                     "order": "release_date", "exclude": []}],
    }]}))

    monkeypatch.setattr(scheduler, "DATA_DIR", tmp_path)
    monkeypatch.setattr(channel_engine, "build_library_index",
                        lambda url: (movie_map, show_map))
    monkeypatch.setattr(channel_engine, "find_channel_by_number",
                        lambda url, n: {"id": "tid-7", "number": n, "name": "Die Hard 24/7"})
    # Current programming is empty → the fresh ids must register as a change.
    monkeypatch.setattr(channel_engine, "read_channel_programming",
                        lambda url, cid: set())

    summary = scheduler._run_cycle_blocking(apply=False)
    assert summary["error"] is None
    assert summary["changed"] == 1
    assert summary["changes"][0]["number"] == 7
```

NOTE: check how `scheduler.py` locates its data dir — it may use a module-level `DATA_DIR` or path helpers (`_load_config`/`_load_channels`/`_load_state`). Read the module first; monkeypatch whatever it actually uses so the test's temp files are read (if it builds paths per-call from a constant, patching the constant as above works; if not, adapt the patching — NOT the production code structure). Also check `_program_ids` shape — if `read_channel_programming` returns a set of ids and resolved programs need `p["id"]`, give the fixture movies/show programs `"id"` fields, e.g. `{"id": "p1", "program": {...}}`; adjust `_movie`/`_maps` in this test file accordingly (adding `"id"` keys to the existing fixtures is fine and won't break earlier tests).

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/pytest backend/tests/test_franchise_refs.py -v`
Expected: the new test fails — the cycle resolves the franchise ref to nothing because no index is passed (summary shows 0 changed or a skip).

- [ ] **Step 4: Implement the three call sites**

`backend/scheduler.py`, in `_run_cycle_blocking`, next to the existing plex_sections conditional block (mirror its style):

```python
    # Franchise index only if a live channel uses franchise refs
    franchise_index = {}
    if any(isinstance(it, dict) and it.get("match") == "franchise"
           for ch in live for it in ch.get("content", [])):
        franchise_index = channel_engine.load_franchise_index(DATA_DIR)
```

and add `franchise_index=franchise_index` to its `resolve_content(...)` call. (Use the module's actual data-dir variable name.)

`backend/routers/channels_router.py`, in `apply_channel._do()`: add `franchise_index=channel_engine.load_franchise_index(DATA_DIR)` to its `resolve_content(...)` call (build it inline only when the channel has a franchise ref, mirroring the collection check — or unconditionally; it's cheap. Unconditional is fine).

`backend/routers/pipeline_router.py`: find the surgical-deploy path's `resolve_content(` call(s) (used for update-in-place of changed channels). Pass `franchise_index=channel_engine.load_franchise_index(DATA_DIR)` (computed once before the loop, not per channel). If pipeline_router does not import channel_engine directly, import it the same way the other routers do.

- [ ] **Step 5: Run tests — all pass; full suite green**

Run: `.venv/bin/pytest backend/tests/test_franchise_refs.py -v && .venv/bin/pytest`

- [ ] **Step 6: Commit**

```bash
git add backend/scheduler.py backend/routers/channels_router.py backend/routers/pipeline_router.py backend/tests/test_franchise_refs.py
git commit -m "feat(live): scheduler, apply, and surgical deploy resolve franchise refs

Every backend resolve_content caller now passes the franchise index, so a
live franchise channel re-resolves by cached membership each cycle and
through every deploy path. Proven by a stubbed end-to-end scheduler cycle."
```

---

### Task 4: Compose emits live franchise channels

**Files:**
- Modify: `backend/routers/pipeline_router.py` (CandidateSpec model + the `spec.kind == "franchise"` compose handler)
- Modify: `backend/tests/test_compose.py` (append)

- [ ] **Step 1: Read the existing compose franchise handling**

Read the `CandidateSpec` pydantic model and the two `spec.kind == "franchise"` sites in `pipeline_router.py` (one builds content, one names/labels — near lines 1864 and 1903; numbers may have drifted). Today: `content = spec.titles` (static). Read one existing test in `backend/tests/test_compose.py` to copy its calling convention (the `pr` fixture + posting CandidateSpecs to compose).

- [ ] **Step 2: Append failing tests to `backend/tests/test_compose.py`** (adapt naming/fixtures to the file's existing style — these are behavioral requirements, copy the file's conventions for invoking compose):

```python
def test_compose_live_franchise_emits_franchise_ref(pr, seed, ...):
    # Seed library + write tmdb_enrichment.json into pr._test_data_dir with a
    # "Die Hard Collection" containing ["Die Hard", "Die Hard 2", "Die Hard 3"].
    # Compose with spec: kind="franchise", name="Die Hard Collection",
    #   titles=["Die Hard", "Die Hard 2"], live=True.
    # Assert the draft channel has:
    #   live is True
    #   content == [{"match": "franchise", "name": "Die Hard Collection",
    #                "order": "release_date", "exclude": ["Die Hard 3"]}]
    #   (exclude = detected members NOT in the checked titles)

def test_compose_live_franchise_without_cache_falls_back_static(pr, seed, ...):
    # Same spec with live=True but NO cache files in the data dir.
    # Assert the draft channel is static: no "live" key (or false), and
    # content == the checked titles (today's behavior).

def test_compose_non_live_franchise_unchanged(pr, seed, ...):
    # live omitted/False → exactly today's static behavior.
```

Write these as REAL tests (full code) once you've read the file's conventions — every assertion above is mandatory.

- [ ] **Step 3: Run to verify they fail, then implement**

In `pipeline_router.py`:
1. `CandidateSpec` gains `live: bool = False`.
2. In the franchise compose handler, replace the static content assignment with:

```python
    elif spec.kind == "franchise" and spec.titles:
        if spec.live and spec.name:
            fr_index = channel_engine.load_franchise_index(DATA_DIR)
            entry = fr_index.get(channel_engine._norm_franchise_name(spec.name))
            if entry:
                checked = {t.lower().strip() for t in spec.titles}
                exclude = [t for t in entry["titles"] if t.lower().strip() not in checked]
                channel["live"] = True
                channel["content"] = [{"match": "franchise", "name": entry["name"],
                                       "order": "release_date", "exclude": exclude}]
            else:
                channel["content"] = list(spec.titles)  # cache miss → static fallback
        else:
            channel["content"] = list(spec.titles)
```

Adapt variable names to the handler's actual structure (it may build a dict at the end rather than mutate `channel` — preserve the existing flow; the REQUIREMENT is the emitted draft entry shape asserted in the tests). Default `shuffle` for live franchise channels: `"ordered"` (watch order is the point) — check what the handler sets today for franchise and keep that unless it's `shuffle`, in which case set `ordered` only for the live path.

- [ ] **Step 4: Run tests — all pass; full suite green. Commit.**

```bash
git add backend/routers/pipeline_router.py backend/tests/test_compose.py
git commit -m "feat(planner): compose emits live franchise channels with identity refs

A franchise spec with live=true becomes a live channel whose content is a
{\"match\": \"franchise\"} ref; unchecked members become the exclude list.
Cache-miss falls back to a static channel — a live channel that would
resolve from nothing is never created."
```

---

### Task 5: Recipes preview supports franchise mode

**Files:**
- Modify: `backend/routers/recipes_router.py`
- Create: `backend/tests/test_recipes_preview.py` (if a preview test file exists, append there instead)
- Modify: `docs/api.md` (the `/api/recipes/preview` row)

- [ ] **Step 1: Failing tests**

```python
"""/recipes/preview — franchise mode."""

import json

import pytest
from fastapi import HTTPException

import channel_engine
from routers import recipes_router


def test_preview_franchise_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(recipes_router, "DATA_DIR", tmp_path)
    (tmp_path / "config.json").write_text(json.dumps({"tunarr_url": "http://t"}))
    (tmp_path / "tmdb_enrichment.json").write_text(json.dumps({
        "sig": "x", "enrichment": {
            "Die Hard": {"title": "Die Hard", "year": 1988,
                         "collection": {"id": 1, "name": "Die Hard Collection"},
                         "keywords": []}}}))
    (tmp_path / "wikidata_cache.json").write_text(json.dumps({"sig": "x", "franchises": []}))

    movie_map = {"die hard": {"id": "p1", "program": {
        "title": "Die Hard", "releaseDate": 1, "year": 1988}}}
    monkeypatch.setattr(channel_engine, "build_library_index",
                        lambda url: (movie_map, {}))

    res = recipes_router.preview_recipe(recipes_router.PreviewRequest(
        value="Die Hard Collection", match="franchise"))
    assert res["count"] == 1
    assert res["matches"][0]["title"] == "Die Hard"


def test_preview_title_contains_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(recipes_router, "DATA_DIR", tmp_path)
    (tmp_path / "config.json").write_text(json.dumps({"tunarr_url": "http://t"}))
    movie_map = {"die hard": {"id": "p1", "program": {
        "title": "Die Hard", "releaseDate": 1, "year": 1988}}}
    monkeypatch.setattr(channel_engine, "build_library_index",
                        lambda url: (movie_map, {}))
    res = recipes_router.preview_recipe(recipes_router.PreviewRequest(value="Die Hard"))
    assert res["count"] == 1
```

- [ ] **Step 2: Verify fail, then implement**

In `recipes_router.py`:
1. `PreviewRequest` gains `match: str = "title_contains"`.
2. In `preview_recipe`, after building the index maps:

```python
    if req.match == "franchise":
        fr_index = channel_engine.load_franchise_index(DATA_DIR)
        _, preview = channel_engine.match_franchise(
            req.value, fr_index, movie_map, show_map,
            order=req.order or "release_date", exclude=req.exclude)
    else:
        _, preview = channel_engine.match_titles(
            req.value, movie_map, show_map, order=req.order, exclude=req.exclude)
    return {"value": req.value, "match": req.match, "order": req.order,
            "count": len(preview), "matches": preview}
```

Update the endpoint docstring (it now previews both ref types).

- [ ] **Step 3: Update `docs/api.md`** — extend the `/api/recipes/preview` row's description: body now accepts `match: "title_contains"|"franchise"` (default title_contains); franchise mode previews cached-membership resolution.

- [ ] **Step 4: Tests green, full suite green, commit.**

```bash
git add backend/routers/recipes_router.py backend/tests/test_recipes_preview.py docs/api.md
git commit -m "feat(live): recipes preview supports franchise refs

Same author-time confirm step as title_contains, backed by cached
membership instead of name matching."
```

---

### Task 6: Frontend — "Keep updated" switch + ref tolerance

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/Run.tsx`
- Modify: `frontend/src/pages/Channels.tsx`

READ each file's relevant region before editing. Verify with `cd frontend && npx tsc --noEmit && npm run build`.

- [ ] **Step 1: client.ts types**

1. `CandidateSpec` gains `live?: boolean;`.
2. Next to `MatchRef` add:

```ts
export interface FranchiseRef { match: 'franchise'; name: string; order?: string | null; exclude?: string[] }
```

3. Find the content-item union (how `Channel.content` items are typed — there's a `ContentItem` or inline union including `MatchRef`); add `FranchiseRef` to it.
4. If `previewRecipe` has a fixed body, add an optional `match` parameter defaulting to `'title_contains'` and include it in the body.

- [ ] **Step 2: Run.tsx — per-card "Keep updated" switch**

Read the franchise card component (Section 2 of the accordion; `toggleFranchise` / `toggleFranchiseMember` / `cid.franchise(...)` are the anchors). Add to each franchise card (visible when the franchise is selected):

```tsx
<Switch
  size="xs"
  label="Keep updated"
  description="Deploys live — new library additions to this franchise appear automatically"
  checked={!!sel?.live}
  onChange={(e) => setFranchiseLive(fr, e.currentTarget.checked)}
/>
```

with a handler beside the existing toggles:

```tsx
function setFranchiseLive(fr: FranchiseCandidate, live: boolean) {
  const id = cid.franchise(fr.name);
  const sel = planner.selected[id];
  if (!sel) return;
  patch({ selected: { ...planner.selected, [id]: { ...sel, live } } });
}
```

(`sel` in the JSX is the card's existing `planner.selected[cid.franchise(fr.name)]` lookup — reuse the variable the card already has. The switch only renders when the card is selected. Placement: with the card's other controls, visually consistent — match surrounding Mantine layout. `Switch` may need adding to the Mantine import.)

Planner state persistence is automatic (the debounced PUT saves `selected`, and `live` rides inside the spec). Compose already receives the full spec objects — verify the compose POST sends `selected` specs as-is (it does — specs go straight into the request body).

- [ ] **Step 3: Channels.tsx — don't mangle franchise refs**

The editor (`ChannelModal`) separates a `title_contains` ref via an `isMatchRef` helper and renders remaining content as editable strings. A franchise ref must survive open→save untouched:
1. Find `isMatchRef` / the `MatchRule` handling. Add a parallel `isFranchiseRef` check (`(c): c is FranchiseRef => typeof c === 'object' && c !== null && (c as any).match === 'franchise'`).
2. When loading the channel, pull franchise refs out of `content` into a `franchiseRefs` state array (like `matchRef`), so the string-content editor never sees them.
3. Render each as a read-only line under the content list:

```tsx
{franchiseRefs.map((r) => (
  <Text key={r.name} size="sm" c="dimmed">
    🔁 Franchise: {r.name} (auto-updating{r.exclude?.length ? `, ${r.exclude.length} excluded` : ''})
  </Text>
))}
```

4. On save (`persist`), re-append `franchiseRefs` to the content payload (mirror how `matchRef` is re-appended).

Authoring/editing franchise refs in the editor is out of scope (Planner-authored in 2a) — preservation + display only.

- [ ] **Step 4: Verify + commit**

```bash
cd frontend && npx tsc --noEmit && npm run build && cd ..
git add frontend/src/api/client.ts frontend/src/pages/Run.tsx frontend/src/pages/Channels.tsx
git commit -m "feat(planner): Keep-updated switch on franchise cards; editor preserves franchise refs

The switch marks the spec live; compose turns it into a live channel with an
identity-based franchise ref. The Channels editor displays franchise refs
read-only and round-trips them unmangled on save."
```

---

### Task 7: Docs

**Files:**
- Modify: `CLAUDE.md` (Live Channels section)
- Modify: `docs/live-channels-design.md` (append a section)

- [ ] **Step 1: CLAUDE.md — Live Channels section**

The section documents `title_contains` as "the one new item allowed in a channel's `content` list". Replace that framing: there are now TWO live content-ref types. After the existing `title_contains` block (keep it), add:

```markdown
**Franchise content-ref** — identity-based, for franchises whose members don't share a name:
```json
{"match": "franchise", "name": "Die Hard Collection", "order": "release_date", "exclude": []}
```
Members come from the Planner's cached TMDB (`belongs_to_collection`) + Wikidata franchise
data (`channel_engine.load_franchise_index` / `match_franchise`) — never name matching, so
new sequels join by membership once the scans have seen them (cache refresh stays on the
Planner's scan triggers). Authored by the Planner's per-franchise **"Keep updated"** switch
(`/pipeline/compose` computes `exclude` from unchecked members — the card's member list is
the author-time preview). Cache-miss at compose time falls back to a static channel; at
resolve time it counts as matched-nothing, and the refuse-to-wipe guards keep the channel
intact.
```

Adjust the preceding sentence ("the one new item") to say "two content-ref types beyond plain titles and collections".

- [ ] **Step 2: docs/live-channels-design.md** — append:

```markdown
## Franchise refs (Phase 2a, 2026-06)

`{"match": "franchise", "name": …}` joins `title_contains` as the second live ref type.
Rationale: title matching cannot express franchises whose members share no words (MCU).
Membership is read from the TMDB/Wikidata caches via `channel_engine.load_franchise_index`
(TMDB wins name collisions, same rule as the Planner merge) and resolved by
`match_franchise`, which mirrors `match_titles`' contract — (resolved, preview), shows sort
after movies in release order. The scheduler is unchanged: refs resolve through
`resolve_content`, the diff/patch cycle is ref-agnostic. Rejected: embedding TMDB/Wikidata
IDs in the ref (cache is name-keyed; IDs differ across sources), scheduler-triggered cache
refresh (circular import with the router layer; revisit in 2b if staleness bites).
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/live-channels-design.md
git commit -m "docs: franchise live content-refs — second ref type, identity-based"
```

---

### Task 8: Final verification (orchestrator)

- [ ] `.venv/bin/pytest` — full suite green.
- [ ] `cd frontend && npx tsc --noEmit && npm run build` — clean.
- [ ] Live smoke with the user's real data: mark one franchise live in the Planner, compose, inspect `channels.draft.json` for the ref shape; `POST /recipes/run?apply=false` dry-cycle and read the summary.
- [ ] Docker parity build on the Windows side (user).

---

## Self-review notes

- Spec coverage: index+matcher (T1), ref resolution (T2), all backend callers (T3), compose+live switch (T4, T6), preview (T5), docs (T7). Playback structure deliberately absent (Phase 2b).
- Naming consistency: `load_franchise_index`, `match_franchise`, `_norm_franchise_name`, `franchise_index=` kwarg, ref field `name` (not `value`) — used identically across tasks.
- Invariants: update-in-place untouched; refuse-to-wipe (`resolved to empty`) guards inherited; `channels.json` writers unchanged; planner-state stickiness carries `live` inside specs automatically.
- Tasks 4 and 6 require reading the target code first; their tests/assertions are the contract where exact surrounding code couldn't be pinned in the plan.
