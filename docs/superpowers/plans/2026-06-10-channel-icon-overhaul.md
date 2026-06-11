# Channel Icon Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kill icon false-positives (a "Horror" channel getting the American Horror Story logo) by gating TMDB lookups behind a verified-name-match rule, and give every other channel a generated badge — curated glyph + channel name stamped on a colored tile — uploaded to Tunarr, with a per-channel icon control in the Channels editor.

**Architecture:** Two new pure root-level modules (mirroring `channel_engine.py`): `icon_engine.py` (kind-gated icon policy + verified TMDB searches + Tunarr icon/upload helpers) and `badge_renderer.py` (Pillow-only badge PNG rendering from committed `badge_assets/`). `fetch_images.py` becomes a thin CLI wrapper over both. A new `POST /api/channels/{number}/icon` endpoint gives the Channels editor a manual override that *pins* the choice in `channels.json` so automatic passes skip it.

**Tech Stack:** Python 3 stdlib + Pillow (new runtime dep), Tabler Icons (MIT, pre-rendered to PNG at dev time via cairosvg — dev-only dep), Anton font (OFL), FastAPI, React + Mantine v7.

**Key decisions (settled during design — do not relitigate):**
- TMDB is only consulted for solo-title channels and `marathon` / `franchise` / `network` / `studio` kinds. All other kinds (`genre`, `genre_decade`, `blend`, `tv_genre`, `tv_movie_mix`, `theme`, `country`, `mood`, `style`, `programming_block`, `director`, `actor`) go straight to a badge.
- A TMDB result is accepted **only** if its name equals the query after normalization (lowercase, strip punctuation, strip leading article). Never `results[0]` on faith.
- Badges always carry the channel name as text (Plex hides channel names when an icon is set, so the badge IS the name).
- `tmdb_api_key` becomes optional for icons: without it, every channel gets a badge.
- Badge PNGs upload via Tunarr's `POST /api/upload/image` (multipart; returns `{name, fileUrl}`; Tunarr serves the file) — Programmarr hosts nothing.
- A user choice in the editor writes `"icon": {"mode": ..., "url": ..., "pinned": true}` into the channel's `channels.json` entry; `fetch_images.py` skips pinned channels. "Reset to automatic" removes the field.
- `fetch_images.py` (a subprocess) must **never write `channels.json`** — only the backend router writes pins.

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `scripts/make_badge_assets.py` | Create | Dev-only: download Tabler SVGs + Anton font, render white glyph PNGs. Outputs are committed. |
| `badge_assets/glyphs/*.png`, `badge_assets/font/*`, `badge_assets/LICENSE-tabler-icons.txt` | Create (generated) | Committed badge art inputs. |
| `icon_engine.py` (repo root) | Create | Pure module: normalization, verified TMDB searches, icon policy, Tunarr upload/icon helpers, planner-spec hints. No config.json/argv/sys.exit. |
| `badge_renderer.py` (repo root) | Create | Pure module: Pillow badge rendering + color/glyph style maps. |
| `fetch_images.py` | Rewrite | Thin CLI over icon_engine + badge_renderer. Same flags. |
| `backend/routers/channels_router.py` | Modify | Add `POST /channels/{number}/icon`. |
| `frontend/src/api/client.ts` | Modify | `ChannelIcon` type, `icon?` on `Channel`, `setChannelIcon` method. |
| `frontend/src/pages/Channels.tsx` | Modify | "Channel icon" section in `ChannelModal`. |
| `backend/requirements.txt` | Modify | Add `pillow`. |
| `Dockerfile` | Modify | COPY the two new modules + `badge_assets/`. |
| `backend/tests/test_icon_engine.py`, `backend/tests/test_badge_renderer.py`, `backend/tests/test_channel_icons.py` | Create | Unit tests (no network — everything stubbed). |
| `CLAUDE.md`, `docs/api.md`, `docs/ideas.md` | Modify | Docs in the same commits as the behavior they describe. |

Note for all backend tests: `backend/tests/conftest.py` already inserts both the repo root and `backend/` into `sys.path`, so tests can `import icon_engine` / `import badge_renderer` / `from routers import channels_router` directly. Run tests with plain `pytest` from the repo root (reads `pytest.ini`).

---

### Task 1: Badge assets — generation script + committed art

**Files:**
- Create: `scripts/make_badge_assets.py`
- Create (generated, committed): `badge_assets/glyphs/*.png`, `badge_assets/font/Anton-Regular.ttf`, `badge_assets/font/OFL-Anton.txt`, `badge_assets/LICENSE-tabler-icons.txt`

- [ ] **Step 1: Install the dev-only renderer dep into the venv (NOT into any requirements file)**

```bash
.venv/bin/pip install cairosvg pillow
```

- [ ] **Step 2: Write `scripts/make_badge_assets.py`**

```python
#!/usr/bin/env python3
"""scripts/make_badge_assets.py — (re)generate the committed badge_assets/ dir.

Downloads Tabler icon SVGs (MIT) at a pinned tag, renders each to a white
256x256 PNG, and downloads the Anton font (OFL) + both licenses. The outputs
are COMMITTED — end users never run this; the runtime needs only Pillow.

Dev-only deps:  pip install cairosvg pillow
Usage:          python scripts/make_badge_assets.py
"""

import io
import os
import sys
import urllib.request

try:
    import cairosvg
except ImportError:
    sys.exit("cairosvg required (dev-only): pip install cairosvg")
from PIL import Image

TABLER_TAG = "v3.31.0"
TABLER_SVG = "https://raw.githubusercontent.com/tabler/tabler-icons/{tag}/icons/outline/{name}.svg"
TABLER_LICENSE = "https://raw.githubusercontent.com/tabler/tabler-icons/{tag}/LICENSE"
ANTON_TTF = "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf"
ANTON_OFL = "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/OFL.txt"

# Single source of truth for which glyphs exist. badge_renderer.py's
# GENRE_GLYPHS / KIND_GLYPHS values must be a subset of this list.
GLYPHS = sorted({
    "antenna", "ball-football", "bomb", "broadcast", "brush", "building",
    "cactus", "calendar", "camera", "color-swatch", "compass", "device-tv",
    "device-tv-old", "eye", "fingerprint", "heart", "hourglass",
    "layout-grid", "masks-theater", "mood-smile", "moon", "movie", "music",
    "palette", "question-mark", "rocket", "skull", "sparkles", "stack-2",
    "star", "swords", "users-group", "wand", "world",
})

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "badge_assets")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Programmarr-dev"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def main():
    glyph_dir = os.path.join(OUT, "glyphs")
    font_dir = os.path.join(OUT, "font")
    os.makedirs(glyph_dir, exist_ok=True)
    os.makedirs(font_dir, exist_ok=True)

    missing = []
    for name in GLYPHS:
        url = TABLER_SVG.format(tag=TABLER_TAG, name=name)
        try:
            svg = fetch(url)
        except Exception as e:
            missing.append(name)
            print(f"  ! {name}: {e}")
            continue
        png = cairosvg.svg2png(bytestring=svg, output_width=256, output_height=256)
        rendered = Image.open(io.BytesIO(png)).convert("RGBA")
        # Tabler outline icons render as black strokes; recolor to white by
        # painting a solid white tile through the rendered alpha channel.
        white = Image.new("RGBA", rendered.size, (255, 255, 255, 255))
        white.putalpha(rendered.getchannel("A"))
        white.save(os.path.join(glyph_dir, f"{name}.png"))
        print(f"  ok {name}")

    with open(os.path.join(OUT, "LICENSE-tabler-icons.txt"), "wb") as f:
        f.write(fetch(TABLER_LICENSE.format(tag=TABLER_TAG)))
    with open(os.path.join(font_dir, "Anton-Regular.ttf"), "wb") as f:
        f.write(fetch(ANTON_TTF))
    with open(os.path.join(font_dir, "OFL-Anton.txt"), "wb") as f:
        f.write(fetch(ANTON_OFL))

    if missing:
        sys.exit(
            f"\n{len(missing)} glyph(s) failed: {', '.join(missing)}.\n"
            "Substitute a similar icon name that exists at "
            f"https://tabler.io/icons (tag {TABLER_TAG}), update GLYPHS here "
            "AND the matching entry in badge_renderer.py, then re-run."
        )
    print(f"\nDone -> {OUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run it**

```bash
.venv/bin/python scripts/make_badge_assets.py
```

Expected: one `ok <name>` line per glyph, `Done -> .../badge_assets`. If any glyph 404s, do exactly what the error says (pick a visually similar existing Tabler icon, update `GLYPHS` and note the substitution in your report — Task 5's maps must then use the substituted name), and re-run until clean.

- [ ] **Step 4: Verify outputs**

```bash
ls badge_assets/glyphs | wc -l   # expected: 34 (or adjusted count after substitutions)
ls badge_assets/font             # Anton-Regular.ttf  OFL-Anton.txt
ls badge_assets                  # LICENSE-tabler-icons.txt  font  glyphs
.venv/bin/python -c "from PIL import Image; im = Image.open('badge_assets/glyphs/skull.png'); print(im.size, im.mode)"
```

Expected last line: `(256, 256) RGBA`

- [ ] **Step 5: Commit (assets ARE committed — they are not build artifacts)**

```bash
git add scripts/make_badge_assets.py badge_assets/
git commit -m "feat(icons): committed badge assets — Tabler glyph PNGs (MIT) + Anton font (OFL)

Generated by scripts/make_badge_assets.py (dev-only cairosvg; runtime needs
only Pillow). These feed badge_renderer.py: generated channel badges for
channels where a TMDB logo lookup can't be trusted."
```

---

### Task 2: `icon_engine.py` — normalization + verified TMDB searches

**Files:**
- Create: `icon_engine.py` (repo root)
- Create: `backend/tests/test_icon_engine.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_icon_engine.py`:

```python
"""icon_engine unit tests — pure logic, all HTTP stubbed. No network."""

import icon_engine


# ── normalize_title ───────────────────────────────────────────────────────────

def test_normalize_strips_article_case_punctuation():
    assert icon_engine.normalize_title("The Matrix") == "matrix"
    assert icon_engine.normalize_title("Spider-Man: No Way Home") == "spiderman no way home"
    assert icon_engine.normalize_title("  A  Bug's   Life ") == "bugs life"
    assert icon_engine.normalize_title(None) == ""


# ── verified searches ─────────────────────────────────────────────────────────

def _stub_results(monkeypatch, results):
    monkeypatch.setattr(icon_engine, "http_get",
                        lambda url, timeout=15: {"results": results})


def test_search_tv_verified_skips_name_mismatch(monkeypatch):
    # The American Horror Story bug: first result must NOT win on rank alone.
    _stub_results(monkeypatch, [
        {"id": 1, "name": "American Horror Story"},
        {"id": 2, "name": "Horror"},
    ])
    assert icon_engine.search_tv_verified("Horror", "key") == 2


def test_search_tv_verified_none_when_no_match(monkeypatch):
    _stub_results(monkeypatch, [{"id": 1, "name": "American Horror Story"}])
    assert icon_engine.search_tv_verified("Horror", "key") is None


def test_search_tv_verified_accepts_original_name(monkeypatch):
    _stub_results(monkeypatch, [{"id": 9, "name": "La Casa de Papel",
                                 "original_name": "Money Heist"}])
    assert icon_engine.search_tv_verified("Money Heist", "key") == 9


def test_search_movie_verified_matches_title_or_original(monkeypatch):
    _stub_results(monkeypatch, [
        {"id": 5, "title": "Die Hard 2", "original_title": "Die Hard 2"},
        {"id": 6, "title": "Die Hard", "original_title": "Die Hard"},
    ])
    assert icon_engine.search_movie_verified("Die Hard", "key") == 6


def test_search_company_verified(monkeypatch):
    _stub_results(monkeypatch, [
        {"id": 3, "name": "HBO Films"},
        {"id": 4, "name": "HBO"},
    ])
    assert icon_engine.search_company_verified("HBO", "key") == 4


def test_searches_handle_empty_results(monkeypatch):
    _stub_results(monkeypatch, [])
    assert icon_engine.search_tv_verified("X", "key") is None
    assert icon_engine.search_movie_verified("X", "key") is None
    assert icon_engine.search_company_verified("X", "key") is None


# ── best_logo_path ────────────────────────────────────────────────────────────

def test_best_logo_prefers_english_then_votes():
    images = {"logos": [
        {"file_path": "/de.png", "iso_639_1": "de", "vote_average": 9},
        {"file_path": "/en-lo.png", "iso_639_1": "en", "vote_average": 1},
        {"file_path": "/en-hi.png", "iso_639_1": "en", "vote_average": 5},
    ]}
    assert icon_engine.best_logo_path(images) == "/en-hi.png"


def test_best_logo_none_when_no_logos():
    assert icon_engine.best_logo_path({"logos": []}) is None
```

- [ ] **Step 2: Run them to verify they fail**

```bash
pytest backend/tests/test_icon_engine.py -v
```

Expected: collection error / failures — `ModuleNotFoundError: No module named 'icon_engine'`.

- [ ] **Step 3: Write `icon_engine.py` (first slice)**

```python
"""icon_engine.py — pure, importable channel-icon resolution logic.

Like channel_engine.py: no config.json, no argv, no sys.exit — safe to
import into the long-lived FastAPI process AND from the fetch_images.py CLI.
Must stay in the Dockerfile COPY line.

Three layers:
  1. Verified TMDB searches — a result is accepted only if its name equals
     the query after normalize_title(). Never results[0] on faith.
  2. Icon policy (icon_attempts) — which channels may consult TMDB at all;
     everything else gets a generated badge (badge_renderer.py).
  3. Tunarr helpers — multipart image upload + set/clear a channel's icon.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/original"

_ARTICLES = re.compile(r"^(the|a|an)\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize_title(s):
    """Lowercase, strip punctuation, drop a leading article, collapse spaces."""
    s = (s or "").strip().lower()
    s = _PUNCT.sub("", s)
    s = _ARTICLES.sub("", s)
    return _WS.sub(" ", s).strip()


# ── HTTP ───────────────────────────────────────────────────────────────────────

def http_get(url, timeout=15):
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "Programmarr/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        print(f"  ! HTTP {e.code}: {url}")
        return None
    except Exception as e:
        print(f"  ! Error fetching {url}: {e}")
        return None


# ── Verified TMDB searches ─────────────────────────────────────────────────────

def _tmdb_search(search_kind, query, api_key):
    q = urllib.parse.urlencode({"query": query, "api_key": api_key})
    data = http_get(f"https://api.themoviedb.org/3/search/{search_kind}?{q}")
    return (data or {}).get("results") or []


def _first_verified(results, query, *name_fields):
    """First result (top 5) whose normalized name equals the normalized query."""
    want = normalize_title(query)
    if not want:
        return None
    for r in results[:5]:
        for field in name_fields:
            if normalize_title(r.get(field)) == want:
                return r["id"]
    return None


def search_tv_verified(title, api_key):
    return _first_verified(_tmdb_search("tv", title, api_key), title,
                           "name", "original_name")


def search_movie_verified(title, api_key):
    return _first_verified(_tmdb_search("movie", title, api_key), title,
                           "title", "original_title")


def search_company_verified(name, api_key):
    return _first_verified(_tmdb_search("company", name, api_key), name, "name")


# ── Logo selection ─────────────────────────────────────────────────────────────

def best_logo_path(images, prefer_lang="en"):
    """Best logo file_path from a TMDB images response, or None.
    Prefers prefer_lang, then no-language, then highest vote overall."""
    logos = (images or {}).get("logos") or []
    if not logos:
        return None
    for lang in (prefer_lang, None, ""):
        candidates = [l for l in logos if l.get("iso_639_1") == lang]
        if candidates:
            return max(candidates, key=lambda l: l.get("vote_average", 0))["file_path"]
    return max(logos, key=lambda l: l.get("vote_average", 0))["file_path"]


def tv_logo_url(tv_id, api_key):
    q = urllib.parse.urlencode({"api_key": api_key, "include_image_language": "en,null"})
    path = best_logo_path(http_get(f"https://api.themoviedb.org/3/tv/{tv_id}/images?{q}"))
    return TMDB_IMAGE_BASE + path if path else None


def movie_logo_url(movie_id, api_key):
    q = urllib.parse.urlencode({"api_key": api_key, "include_image_language": "en,null"})
    path = best_logo_path(http_get(f"https://api.themoviedb.org/3/movie/{movie_id}/images?{q}"))
    return TMDB_IMAGE_BASE + path if path else None


def company_logo_url(company_id, api_key):
    q = urllib.parse.urlencode({"api_key": api_key})
    path = best_logo_path(http_get(f"https://api.themoviedb.org/3/company/{company_id}/images?{q}"))
    return TMDB_IMAGE_BASE + path if path else None
```

- [ ] **Step 4: Run the tests — all pass**

```bash
pytest backend/tests/test_icon_engine.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add icon_engine.py backend/tests/test_icon_engine.py
git commit -m "feat(icons): icon_engine — verified TMDB searches (name must match query)

A search result is accepted only when its normalized name equals the
normalized query; never results[0] on faith. This is the rule that kills
the 'Horror channel gets the American Horror Story logo' bug class."
```

---

### Task 3: `icon_engine.py` — kind-gated icon policy

**Files:**
- Modify: `icon_engine.py` (append)
- Modify: `backend/tests/test_icon_engine.py` (append)

- [ ] **Step 1: Append failing tests to `backend/tests/test_icon_engine.py`**

```python
# ── icon policy ───────────────────────────────────────────────────────────────

def test_badge_only_kinds_never_consult_tmdb():
    ch = {"name": "Horror", "content": ["It", "Scream", "The Thing"]}
    for kind in ("genre", "genre_decade", "blend", "tv_genre", "tv_movie_mix",
                 "theme", "country", "mood", "style", "programming_block",
                 "director", "actor"):
        assert icon_engine.icon_attempts(ch, kind) == [], kind


def test_unknown_multi_title_channel_is_badge_only():
    # The exact channel shape that used to produce false positives.
    ch = {"name": "Horror", "content": ["It", "Scream"]}
    assert icon_engine.icon_attempts(ch, None) == []


def test_solo_title_channel_tries_its_title_regardless_of_kind():
    ch = {"name": "Die Hard 24/7", "content": ["Die Hard"]}
    assert icon_engine.icon_attempts(ch, "genre") == [("tv", "Die Hard"),
                                                      ("movie", "Die Hard")]
    assert icon_engine.icon_attempts(ch, None) == [("tv", "Die Hard"),
                                                   ("movie", "Die Hard")]


def test_marathon_searches_tv_by_show_title():
    ch = {"name": "Seinfeld Marathon", "content": ["Seinfeld"]}
    assert icon_engine.icon_attempts(ch, "marathon") == [("tv", "Seinfeld"),
                                                         ("movie", "Seinfeld")]


def test_franchise_strips_suffix_and_tries_tv_then_movie():
    ch = {"name": "Star Wars Saga", "content": ["A New Hope", "Empire"]}
    assert icon_engine.icon_attempts(ch, "franchise") == [("tv", "Star Wars"),
                                                          ("movie", "Star Wars")]


def test_network_and_studio_search_company():
    ch = {"name": "HBO", "content": ["The Wire", "The Sopranos"]}
    assert icon_engine.icon_attempts(ch, "network") == [("company", "HBO")]
    ch2 = {"name": "A24", "content": ["Hereditary", "Lady Bird"]}
    assert icon_engine.icon_attempts(ch2, "studio") == [("company", "A24")]


def test_collection_ref_content_is_not_solo():
    ch = {"name": "Kometa Picks", "content": [{"collection": "Picks"}]}
    assert icon_engine.icon_attempts(ch, None) == []


# ── resolve_tmdb_logo ─────────────────────────────────────────────────────────

def test_resolve_walks_attempts_in_order(monkeypatch):
    monkeypatch.setattr(icon_engine, "search_tv_verified", lambda t, k: None)
    monkeypatch.setattr(icon_engine, "search_movie_verified",
                        lambda t, k: 42 if t == "Star Wars" else None)
    monkeypatch.setattr(icon_engine, "movie_logo_url",
                        lambda mid, k: "http://img/sw.png" if mid == 42 else None)
    attempts = [("tv", "Star Wars"), ("movie", "Star Wars")]
    assert icon_engine.resolve_tmdb_logo(attempts, "key") == "http://img/sw.png"


def test_resolve_verified_id_without_logo_falls_through(monkeypatch):
    monkeypatch.setattr(icon_engine, "search_tv_verified", lambda t, k: 7)
    monkeypatch.setattr(icon_engine, "tv_logo_url", lambda tid, k: None)
    monkeypatch.setattr(icon_engine, "search_movie_verified", lambda t, k: None)
    assert icon_engine.resolve_tmdb_logo([("tv", "X"), ("movie", "X")], "key") is None


def test_resolve_empty_attempts_is_none():
    assert icon_engine.resolve_tmdb_logo([], "key") is None


# ── planner spec hints ────────────────────────────────────────────────────────

def test_load_spec_hints(tmp_path):
    ps = tmp_path / "planner_state.json"
    ps.write_text('{"selected": {"a": {"kind": "genre", "name": "Horror", '
                  '"genre": "horror"}, "bad": {"kind": "x"}}}')
    hints = icon_engine.load_spec_hints(ps)
    assert hints == {"horror": {"kind": "genre", "name": "Horror", "genre": "horror"}}


def test_load_spec_hints_missing_file(tmp_path):
    assert icon_engine.load_spec_hints(tmp_path / "nope.json") == {}


def test_spec_genre_prefers_genre_then_genres():
    assert icon_engine.spec_genre({"genre": "horror"}) == "horror"
    assert icon_engine.spec_genre({"genres": ["western", "comedy"]}) == "western"
    assert icon_engine.spec_genre({}) is None
```

- [ ] **Step 2: Run to verify the new tests fail**

```bash
pytest backend/tests/test_icon_engine.py -v
```

Expected: Task-2 tests still PASS; new tests FAIL with `AttributeError: ... 'icon_attempts'`.

- [ ] **Step 3: Append the policy layer to `icon_engine.py`**

```python
# ── Icon policy ────────────────────────────────────────────────────────────────

# Kinds for which NO TMDB lookup is trustworthy — always a generated badge.
BADGE_ONLY_KINDS = {
    "genre", "genre_decade", "blend", "tv_genre", "tv_movie_mix", "theme",
    "country", "mood", "style", "programming_block", "director", "actor",
}

_FRANCHISE_SUFFIXES = re.compile(
    r"\s+(Collection|Series|Franchise|Universe|Saga|Trilogy|Tetralogy|"
    r"Anthology|Films?|Movies?|Pictures?)\s*$",
    re.IGNORECASE,
)


def icon_attempts(ch_def, kind):
    """Ordered (search_kind, query) attempts for a verified TMDB logo.

    Empty list => badge-only channel. search_kind is "tv" | "movie" | "company".
    Solo-title channels always try their one title (the channel IS that title),
    regardless of kind.
    """
    name = (ch_def.get("name") or "").strip()
    content = ch_def.get("content") or []
    strings = [c for c in content if isinstance(c, str)]
    solo = len(content) == 1 and len(strings) == 1

    if solo:
        return [("tv", strings[0]), ("movie", strings[0])]
    if kind in BADGE_ONLY_KINDS:
        return []
    if kind == "marathon":
        title = strings[0] if strings else name
        return [("tv", title), ("movie", title)]
    if kind == "franchise":
        cleaned = _FRANCHISE_SUFFIXES.sub("", name).strip() or name
        return [("tv", cleaned), ("movie", cleaned)]
    if kind in ("network", "studio"):
        return [("company", name)]
    return []  # unknown kind, multi-title: the old false-positive class — badge.


def resolve_tmdb_logo(attempts, api_key):
    """Run verified-search attempts in order; return the first logo URL or None."""
    searchers = {
        "tv": (search_tv_verified, tv_logo_url),
        "movie": (search_movie_verified, movie_logo_url),
        "company": (search_company_verified, company_logo_url),
    }
    for search_kind, query in attempts:
        search, logo = searchers[search_kind]
        found_id = search(query, api_key)
        if found_id:
            url = logo(found_id, api_key)
            if url:
                return url
    return None


# ── Planner spec hints ─────────────────────────────────────────────────────────

def load_spec_hints(path):
    """planner_state.json 'selected' specs keyed by lowercased channel name.
    Returns {} on any failure — hints are best-effort."""
    try:
        with open(path, encoding="utf-8") as f:
            ps = json.load(f)
        return {
            v["name"].strip().lower(): v
            for v in (ps.get("selected") or {}).values()
            if isinstance(v, dict) and v.get("name")
        }
    except (OSError, ValueError, AttributeError):
        return {}


def spec_genre(spec):
    """Best genre hint from a CandidateSpec dict (genre, else first of genres)."""
    return spec.get("genre") or (spec.get("genres") or [None])[0]
```

- [ ] **Step 4: Run tests — all pass**

```bash
pytest backend/tests/test_icon_engine.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add icon_engine.py backend/tests/test_icon_engine.py
git commit -m "feat(icons): kind-gated icon policy — TMDB only where trustworthy

genre/decade/mood/theme/etc channels never consult TMDB (straight to
badge); solo/marathon/franchise/network/studio run verified searches in a
fixed attempt order. Unknown multi-title channels are badge-only."
```

---

### Task 4: `icon_engine.py` — Tunarr upload + icon helpers

**Files:**
- Modify: `icon_engine.py` (append)
- Modify: `backend/tests/test_icon_engine.py` (append)

- [ ] **Step 1: Append failing tests**

```python
# ── Tunarr helpers ────────────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()
    def read(self):
        return self._payload
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


import json  # noqa: E402  (used by _FakeResp; keep test file self-contained)


def test_upload_image_multipart(monkeypatch):
    captured = {}
    def fake_urlopen(req, timeout=30):
        captured["req"] = req
        return _FakeResp({"name": "x.png",
                          "fileUrl": "http://t/images/uploads/x.png"})
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    url = icon_engine.upload_image_to_tunarr("http://t", b"\x89PNGfake", "x.png")

    assert url == "http://t/images/uploads/x.png"
    req = captured["req"]
    assert req.full_url == "http://t/api/upload/image"
    assert req.get_header("Content-type", "").startswith(
        "multipart/form-data; boundary=")
    assert b"\x89PNGfake" in req.data
    assert b'filename="x.png"' in req.data
    assert b'name="file"' in req.data


def test_set_tunarr_channel_icon(monkeypatch):
    sent = {}
    def fake_put(tunarr_url, path, body):
        sent["path"], sent["body"] = path, body
        return body
    monkeypatch.setattr(icon_engine, "_tunarr_put", fake_put)

    ch = {"id": "abc", "name": "X", "icon": {"path": "old"}}
    ok = icon_engine.set_tunarr_channel_icon("http://t", ch, "http://img/new.png")

    assert ok is True
    assert sent["path"] == "/api/channels/abc"
    assert sent["body"]["icon"]["path"] == "http://img/new.png"
    assert sent["body"]["icon"]["useDefaultIconFallback"] is False
    assert ch["icon"]["path"] == "old"  # input not mutated


def test_clear_tunarr_channel_icon(monkeypatch):
    sent = {}
    monkeypatch.setattr(icon_engine, "_tunarr_put",
                        lambda u, p, b: sent.update(body=b) or b)
    ok = icon_engine.clear_tunarr_channel_icon("http://t", {"id": "abc"})
    assert ok is True
    assert sent["body"]["icon"]["path"] == ""
    assert sent["body"]["icon"]["useDefaultIconFallback"] is True


def test_set_icon_reports_failure(monkeypatch):
    monkeypatch.setattr(icon_engine, "_tunarr_put", lambda u, p, b: None)
    assert icon_engine.set_tunarr_channel_icon("http://t", {"id": "x"}, "u") is False
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest backend/tests/test_icon_engine.py -v
```

Expected: new tests FAIL (`AttributeError: ... 'upload_image_to_tunarr'`).

- [ ] **Step 3: Append the Tunarr layer to `icon_engine.py`**

```python
# ── Tunarr helpers ────────────────────────────────────────────────────────────

def _tunarr_put(tunarr_url, path, body):
    url = tunarr_url + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, method="PUT",
        headers={"Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        print(f"  ! HTTP {e.code} [PUT {path}]: {raw[:200]}")
        return None
    except Exception as e:
        print(f"  ! Error [PUT {path}]: {e}")
        return None


def get_full_channel(tunarr_url, channel_id):
    """Full Tunarr channel object (the summary from /api/channels lacks fields
    the PUT round-trip needs)."""
    return http_get(f"{tunarr_url}/api/channels/{channel_id}", timeout=30)


def upload_image_to_tunarr(tunarr_url, png_bytes, filename):
    """POST multipart to Tunarr /api/upload/image. Returns the Tunarr-served
    fileUrl. Raises on HTTP failure (callers decide how to report)."""
    boundary = uuid.uuid4().hex
    body = (
        (f"--{boundary}\r\n"
         f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
         f"Content-Type: image/png\r\n\r\n").encode()
        + png_bytes
        + f"\r\n--{boundary}--\r\n".encode()
    )
    req = urllib.request.Request(
        tunarr_url + "/api/upload/image", data=body, method="POST",
        headers={"Accept": "application/json",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["fileUrl"]


def set_tunarr_channel_icon(tunarr_url, channel, icon_url):
    """PUT the channel back with icon.path set. Returns True on success."""
    updated = dict(channel)
    updated["icon"] = dict(channel.get("icon") or {})
    updated["icon"]["path"] = icon_url
    updated["icon"]["useDefaultIconFallback"] = False
    return _tunarr_put(tunarr_url, f"/api/channels/{channel['id']}", updated) is not None


def clear_tunarr_channel_icon(tunarr_url, channel):
    """Reset a channel to the Tunarr default icon. Returns True on success."""
    updated = dict(channel)
    updated["icon"] = dict(channel.get("icon") or {})
    updated["icon"]["path"] = ""
    updated["icon"]["useDefaultIconFallback"] = True
    return _tunarr_put(tunarr_url, f"/api/channels/{channel['id']}", updated) is not None
```

- [ ] **Step 4: Run tests — all pass**

```bash
pytest backend/tests/test_icon_engine.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add icon_engine.py backend/tests/test_icon_engine.py
git commit -m "feat(icons): Tunarr helpers — multipart image upload + set/clear channel icon

Badges upload via Tunarr POST /api/upload/image (Tunarr stores and serves
the file), so Programmarr never has to host icon files itself."
```

---

### Task 5: `badge_renderer.py` — Pillow badge rendering

**Files:**
- Create: `badge_renderer.py` (repo root)
- Create: `backend/tests/test_badge_renderer.py`
- Modify: `backend/requirements.txt` (add `pillow>=10.0.0`)

**Precondition:** Task 1's `badge_assets/` is committed. If Task 1 substituted any glyph names, use the substituted names in the maps below.

- [ ] **Step 1: Add Pillow to runtime requirements and install**

In `backend/requirements.txt`, append:

```
pillow>=10.0.0
```

```bash
.venv/bin/pip install -r backend/requirements.txt
```

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_badge_renderer.py`:

```python
"""badge_renderer tests — real Pillow rendering against committed badge_assets/."""

import io

from PIL import Image

import badge_renderer


def _open(png_bytes):
    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")


def test_render_returns_512_png():
    img = _open(badge_renderer.render_badge("Horror", kind="genre", genre="horror"))
    assert img.size == (512, 512)


def test_genre_sets_background_color():
    img = _open(badge_renderer.render_badge("Horror", kind="genre", genre="horror"))
    # (256, 40): top-center, inside the rounded rect fill, above the glyph.
    assert img.getpixel((256, 40)) == (139, 0, 0, 255)  # horror = #8b0000


def test_different_genres_render_differently():
    horror = badge_renderer.render_badge("Late Night", kind="genre", genre="horror")
    comedy = badge_renderer.render_badge("Late Night", kind="genre", genre="comedy")
    assert horror != comedy


def test_kind_color_when_no_genre():
    img = _open(badge_renderer.render_badge("HBO", kind="network"))
    assert img.getpixel((256, 40)) == (40, 53, 147, 255)  # network = #283593


def test_unknown_everything_uses_default():
    img = _open(badge_renderer.render_badge("Mystery Box"))
    assert img.getpixel((256, 40)) == (55, 71, 79, 255)  # default = #37474f


def test_long_names_do_not_crash():
    png = badge_renderer.render_badge(
        "The Totally Excellent Late Night Creature Feature Double Bill Marathon",
        kind="theme")
    assert _open(png).size == (512, 512)


def test_name_text_changes_output():
    a = badge_renderer.render_badge("Horror", genre="horror")
    b = badge_renderer.render_badge("80s Horror", genre="horror")
    assert a != b
```

- [ ] **Step 3: Run to verify they fail**

```bash
pytest backend/tests/test_badge_renderer.py -v
```

Expected: `ModuleNotFoundError: No module named 'badge_renderer'`.

- [ ] **Step 4: Write `badge_renderer.py`**

```python
"""badge_renderer.py — render channel badge PNGs. Pillow only, pure module.

Badges exist because (a) TMDB has no trustworthy logo for concept channels
(genre/decade/mood/theme/...), and (b) Plex hides a channel's text name once
any icon is set — so the badge must CARRY the name. Every badge: colored
rounded tile + white glyph + the channel name stamped in Anton caps.

Art inputs live in badge_assets/ (committed; regenerate via
scripts/make_badge_assets.py). Must stay in the Dockerfile COPY lines.
"""

import io
import os

from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "badge_assets")
FONT_PATH = os.path.join(ASSETS_DIR, "font", "Anton-Regular.ttf")

CANVAS = 512
GLYPH_SIZE = 176
TEXT_MAX_WIDTH = 440

GENRE_COLORS = {
    "action": "#c0392b", "adventure": "#ef6c00", "animation": "#00acc1",
    "comedy": "#f59f00", "crime": "#37474f", "documentary": "#00695c",
    "drama": "#34495e", "family": "#43a047", "fantasy": "#6a1b9a",
    "history": "#6d4c41", "horror": "#8b0000", "music": "#d81b60",
    "musical": "#d81b60", "mystery": "#4527a0", "romance": "#c2185b",
    "sci-fi": "#5e35b1", "science fiction": "#5e35b1", "sport": "#2e7d32",
    "thriller": "#455a64", "war": "#5d4037", "western": "#8d6e63",
    "film-noir": "#212121", "noir": "#212121",
}
KIND_COLORS = {
    "marathon": "#1565c0", "network": "#283593", "franchise": "#4e342e",
    "studio": "#006064", "director": "#424242", "actor": "#827717",
    "country": "#00838f", "mood": "#ad1457", "style": "#7b1fa2",
    "theme": "#00897b", "programming_block": "#3949ab",
}
DEFAULT_COLOR = "#37474f"

GENRE_GLYPHS = {
    "action": "bomb", "adventure": "compass", "animation": "palette",
    "comedy": "mood-smile", "crime": "fingerprint", "documentary": "camera",
    "drama": "masks-theater", "family": "users-group", "fantasy": "wand",
    "history": "hourglass", "horror": "skull", "music": "music",
    "musical": "music", "mystery": "question-mark", "romance": "heart",
    "sci-fi": "rocket", "science fiction": "rocket", "sport": "ball-football",
    "thriller": "eye", "war": "swords", "western": "cactus",
    "film-noir": "moon", "noir": "moon",
}
KIND_GLYPHS = {
    "marathon": "device-tv", "tv_genre": "device-tv",
    "tv_movie_mix": "device-tv-old", "network": "broadcast",
    "franchise": "stack-2", "studio": "building", "director": "movie",
    "actor": "star", "country": "world", "mood": "mood-smile",
    "style": "brush", "theme": "sparkles", "programming_block": "layout-grid",
    "genre": "movie", "genre_decade": "calendar", "blend": "color-swatch",
}
DEFAULT_GLYPH = "antenna"


def _norm(s):
    return (s or "").strip().lower()


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _darken(rgb, factor=0.65):
    return tuple(int(c * factor) for c in rgb)


def color_for(kind=None, genre=None):
    return (GENRE_COLORS.get(_norm(genre))
            or KIND_COLORS.get(_norm(kind))
            or DEFAULT_COLOR)


def glyph_path_for(kind=None, genre=None):
    name = (GENRE_GLYPHS.get(_norm(genre))
            or KIND_GLYPHS.get(_norm(kind))
            or DEFAULT_GLYPH)
    return os.path.join(ASSETS_DIR, "glyphs", f"{name}.png")


def _wrap(draw, text, font, max_width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if not cur or draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_badge(name, kind=None, genre=None):
    """Render a 512x512 badge PNG for a channel. Returns PNG bytes."""
    rgb = _hex_to_rgb(color_for(kind, genre))
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([8, 8, CANVAS - 8, CANVAS - 8], radius=48,
                           fill=rgb + (255,),
                           outline=_darken(rgb) + (255,), width=6)

    glyph_file = glyph_path_for(kind, genre)
    if os.path.exists(glyph_file):
        glyph = Image.open(glyph_file).convert("RGBA").resize(
            (GLYPH_SIZE, GLYPH_SIZE), Image.LANCZOS)
        img.alpha_composite(glyph, ((CANVAS - GLYPH_SIZE) // 2, 64))

    text = (name or "").upper()
    size = 60
    font = ImageFont.truetype(FONT_PATH, size)
    lines = _wrap(draw, text, font, TEXT_MAX_WIDTH)
    while size > 28 and (len(lines) > 3 or any(
            draw.textlength(l, font=font) > TEXT_MAX_WIDTH for l in lines)):
        size -= 4
        font = ImageFont.truetype(FONT_PATH, size)
        lines = _wrap(draw, text, font, TEXT_MAX_WIDTH)

    line_height = size + 10
    block_height = line_height * len(lines)
    y = 268 + max(0, (200 - block_height) // 2)
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((CANVAS - w) / 2, y), line, font=font,
                  fill=(255, 255, 255, 255))
        y += line_height

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
```

- [ ] **Step 5: Run tests — all pass**

```bash
pytest backend/tests/test_badge_renderer.py -v
```

Expected: all PASS. If a textlength edge makes a long-name assertion fail, fix the renderer (not the test) — the invariant is "never crash, never exceed 3 lines wider than 440px at the floor size of 28".

- [ ] **Step 6: Eyeball one badge (manual sanity, not a test)**

```bash
.venv/bin/python -c "
import badge_renderer, pathlib
pathlib.Path('/tmp/badge-sample.png').write_bytes(
    badge_renderer.render_badge('80s Horror', kind='genre_decade', genre='horror'))
print('wrote /tmp/badge-sample.png')
"
```

Open `/tmp/badge-sample.png` and confirm: dark-red tile, white skull, "80S HORROR" legible. Include this sample (or a description) in your report.

- [ ] **Step 7: Commit**

```bash
git add badge_renderer.py backend/tests/test_badge_renderer.py backend/requirements.txt
git commit -m "feat(icons): badge_renderer — generated channel badges (glyph + stamped name)

Pillow-rendered 512px tiles: genre/kind color, white Tabler glyph, channel
name in Anton caps with wrap + autoshrink. The stamped name matters because
Plex suppresses a channel's text label whenever an icon is set."
```

---

### Task 6: Rewrite `fetch_images.py` + packaging

**Files:**
- Rewrite: `fetch_images.py`
- Modify: `Dockerfile:27-28` (COPY lines)
- Modify: `CLAUDE.md` (the `fetch_images.py` architecture bullet + two new module bullets)

**Behavior contract:** same CLI flags (`--json`, `--apply`, `--channel`, `--clear`). New: unified loop (no solo/multi split), pin-skip, badge fallback, key-optional. Subprocess runs with `cwd=DATA_DIR`, so bare relative filenames (`config.json`, `channels.json`, `planner_state.json`) keep working. **This script never writes `channels.json`.**

- [ ] **Step 1: Replace the entire contents of `fetch_images.py`**

```python
#!/usr/bin/env python3
"""
fetch_images.py — set every channel's Tunarr icon.

Verified TMDB logos where a lookup is trustworthy, generated badge art
everywhere else (see icon_engine.icon_attempts for the policy):

  * solo-title channels and marathon/franchise/network/studio kinds try a
    VERIFIED TMDB search — the result's name must equal the query after
    normalization. Never results[0] on faith.
  * every other kind (genre, decade, mood, theme, ...) and any TMDB miss
    gets a badge (badge_renderer) uploaded via Tunarr POST /api/upload/image.
  * channels pinned from the Channels editor ("icon": {"pinned": true} in
    channels.json) are skipped. This script NEVER writes channels.json.

"tmdb_api_key" in config.json is OPTIONAL — without it everything badges.

Usage:
    python fetch_images.py              # dry run — shows what would be set
    python fetch_images.py --apply      # actually update Tunarr
    python fetch_images.py --channel 10 [--apply]
    python fetch_images.py --clear      # remove all custom icons
"""

import argparse
import json
import sys
import time
import uuid

import badge_renderer
import icon_engine

CONFIG_FILE = "config.json"
DEFAULT_CHANNELS_FILE = "channels.json"
PLANNER_STATE_FILE = "planner_state.json"


def load_config():
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {CONFIG_FILE} not found.")
        sys.exit(1)
    if not cfg.get("tunarr_url"):
        print("ERROR: 'tunarr_url' not found in config.json.")
        sys.exit(1)
    return cfg


def get_tunarr_channels(tunarr_url):
    """number -> full channel object for every Tunarr channel."""
    channels = icon_engine.http_get(f"{tunarr_url}/api/channels", timeout=30) or []
    by_number = {}
    for ch in channels:
        full = icon_engine.get_full_channel(tunarr_url, ch["id"])
        if full:
            by_number[ch["number"]] = full
    return by_number


def run_clear(tunarr_url, apply):
    print("Fetching Tunarr channels...")
    cleared = 0
    for number, tch in sorted(get_tunarr_channels(tunarr_url).items()):
        if not tch.get("icon", {}).get("path"):
            continue
        label = f"#{number} {tch['name']}"
        if apply:
            ok = icon_engine.clear_tunarr_channel_icon(tunarr_url, tch)
            print(f"  {'Cleared' if ok else 'FAIL  '} {label}")
            cleared += 1 if ok else 0
        else:
            print(f"  [DRY RUN] Would clear {label}")
            cleared += 1
    print(f"\nDone: {cleared} icons {'cleared' if apply else 'would be cleared'}")


def main():
    parser = argparse.ArgumentParser(
        description="Set Tunarr channel icons: verified TMDB logos + generated badges")
    parser.add_argument("--json", default=DEFAULT_CHANNELS_FILE, help="channels.json file")
    parser.add_argument("--apply", action="store_true",
                        help="Actually update Tunarr (default is dry run)")
    parser.add_argument("--channel", type=int, help="Process only this channel number")
    parser.add_argument("--clear", action="store_true",
                        help="Remove all custom icons, reset to Tunarr default")
    args = parser.parse_args()

    cfg = load_config()
    tunarr_url = cfg["tunarr_url"].rstrip("/")
    tmdb_key = cfg.get("tmdb_api_key", "")

    if not args.apply:
        print("DRY RUN — pass --apply to update Tunarr\n")
    if args.clear:
        run_clear(tunarr_url, args.apply)
        return
    if not tmdb_key:
        print("NOTE: no tmdb_api_key in config.json — every channel gets a "
              "generated badge (no TMDB logo lookups).\n")

    try:
        with open(args.json, encoding="utf-8") as f:
            channels_def = json.load(f).get("channels", [])
    except FileNotFoundError:
        print(f"ERROR: {args.json} not found.")
        sys.exit(1)

    if args.channel:
        channels_def = [c for c in channels_def if c.get("number") == args.channel]
        if not channels_def:
            print(f"Channel #{args.channel} not found in {args.json}")
            sys.exit(1)

    hints = icon_engine.load_spec_hints(PLANNER_STATE_FILE)
    print(f"Processing {len(channels_def)} channel(s)\n")
    print("Fetching Tunarr channels...")
    tunarr_chs = get_tunarr_channels(tunarr_url)
    print()

    stats = {"tmdb": 0, "badge": 0, "pinned": 0, "no_channel": 0, "failed": 0}
    verb = "Set" if args.apply else "[DRY RUN] Would set"

    for ch_def in channels_def:
        number = ch_def.get("number")
        name = (ch_def.get("name") or "").strip()

        if (ch_def.get("icon") or {}).get("pinned"):
            print(f"  PIN  #{number} {name} — user-pinned icon, skipping")
            stats["pinned"] += 1
            continue

        tch = tunarr_chs.get(number)
        if not tch:
            print(f"  SKIP #{number} {name} — not found in Tunarr (not deployed yet?)")
            stats["no_channel"] += 1
            continue

        spec = hints.get(name.lower(), {})
        kind = spec.get("kind")

        logo_url = None
        if tmdb_key:
            attempts = icon_engine.icon_attempts(ch_def, kind)
            if attempts:
                logo_url = icon_engine.resolve_tmdb_logo(attempts, tmdb_key)
                time.sleep(0.25)  # be polite to TMDB rate limits

        if logo_url:
            ok = icon_engine.set_tunarr_channel_icon(tunarr_url, tch, logo_url) \
                if args.apply else True
            print(f"  #{number} {name} — {verb} TMDB logo" if ok
                  else f"  #{number} {name} — FAILED to update Tunarr")
            if ok:
                print(f"    {logo_url}")
            stats["tmdb" if ok else "failed"] += 1
            continue

        # Badge path — the universal fallback.
        label = f"badge ({kind or 'generic'})"
        if args.apply:
            png = badge_renderer.render_badge(name, kind=kind,
                                              genre=icon_engine.spec_genre(spec))
            try:
                badge_url = icon_engine.upload_image_to_tunarr(
                    tunarr_url, png, f"programmarr-ch{number}-{uuid.uuid4().hex[:8]}.png")
                ok = icon_engine.set_tunarr_channel_icon(tunarr_url, tch, badge_url)
            except Exception as e:
                print(f"  #{number} {name} — FAILED badge upload: {e}")
                stats["failed"] += 1
                continue
        else:
            ok = True
        print(f"  #{number} {name} — {verb} {label}" if ok
              else f"  #{number} {name} — FAILED to update Tunarr")
        stats["badge" if ok else "failed"] += 1

    print(f"\n{'Applied' if args.apply else 'Dry run'}: "
          f"{stats['tmdb']} TMDB logos, {stats['badge']} badges, "
          f"{stats['pinned']} pinned (skipped), "
          f"{stats['no_channel']} not in Tunarr"
          + (f", {stats['failed']} failed" if stats["failed"] else ""))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Sanity-check it imports and parses**

```bash
.venv/bin/python -c "import ast; ast.parse(open('fetch_images.py').read()); print('parses')"
.venv/bin/python fetch_images.py --help
```

Expected: `parses`, then the argparse help text (running `--help` exercises the imports of `icon_engine` and `badge_renderer`).

- [ ] **Step 3: Update the Dockerfile COPY lines**

Change lines 27–28 from:

```dockerfile
COPY export.py create.py channel_engine.py channel_blocks.py generate_no_ai.py generate_from_collections.py \
     fetch_images.py sync_plex.py PROMPT.md programming_blocks.json themed_keywords.json ./
```

to:

```dockerfile
COPY export.py create.py channel_engine.py channel_blocks.py generate_no_ai.py generate_from_collections.py \
     fetch_images.py sync_plex.py icon_engine.py badge_renderer.py PROMPT.md programming_blocks.json themed_keywords.json ./
COPY badge_assets/ ./badge_assets/
```

- [ ] **Step 4: Update CLAUDE.md Architecture section (same commit — repo rule)**

Replace the `fetch_images.py` bullet with:

```markdown
- **`fetch_images.py`** — sets every channel's Tunarr icon. Verified TMDB logos for
  solo-title/marathon/franchise/network/studio channels (the result's name must match the
  query after normalization — never `results[0]`); generated badge art for every other kind
  and any TMDB miss. Badges upload via Tunarr `POST /api/upload/image`. Channels pinned from
  the Channels editor (`"icon": {"pinned": true}` in channels.json) are skipped; the script
  never writes channels.json. `tmdb_api_key` is optional — without it everything badges.
  Dry-run by default; `--apply` to commit.
- **`icon_engine.py`** — shared, **pure, importable** icon policy + verified TMDB searches +
  Tunarr upload/icon helpers (no `config.json`/argv/`sys.exit`). Imported by `fetch_images.py`
  and in-process by `channels_router.py`. **Must stay in the Dockerfile `COPY` line.**
- **`badge_renderer.py`** — shared, **pure** Pillow badge rendering from committed
  `badge_assets/` (Tabler glyphs MIT, Anton font OFL; regenerate via
  `scripts/make_badge_assets.py`). Badges carry the channel name because Plex hides text
  labels once an icon is set. **Module + `badge_assets/` must stay in the Dockerfile `COPY` lines.**
```

- [ ] **Step 5: Run the whole suite**

```bash
pytest
```

Expected: all tests pass (the rewrite must not break any existing test).

- [ ] **Step 6: Commit**

```bash
git add fetch_images.py Dockerfile CLAUDE.md
git commit -m "feat(icons): fetch_images rewrite — kind-gated TMDB + badge fallback + pin-skip

Unified loop over channels.json: verified TMDB logo where the policy allows,
generated badge everywhere else, user-pinned icons skipped. tmdb_api_key now
optional (keyless = all badges). Ships icon_engine/badge_renderer/badge_assets
in the Docker image."
```

---

### Task 7: `POST /api/channels/{number}/icon` endpoint

**Files:**
- Modify: `backend/routers/channels_router.py`
- Create: `backend/tests/test_channel_icons.py`
- Modify: `docs/api.md` (add the endpoint row to the channels table)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_channel_icons.py`:

```python
"""POST /channels/{number}/icon — pin/override a channel's Tunarr icon.

Everything external is monkeypatched on the modules channels_router imports;
no Tunarr, no TMDB, no Pillow font rendering in the endpoint tests."""

import asyncio
import json

import pytest
from fastapi import HTTPException

import badge_renderer
import channel_engine
import icon_engine
from routers import channels_router


@pytest.fixture
def chdir_data(tmp_path, monkeypatch):
    """Point channels_router at a temp DATA_DIR seeded with one channel."""
    monkeypatch.setattr(channels_router, "DATA_DIR", tmp_path)
    (tmp_path / "channels.json").write_text(json.dumps({
        "channels": [{"number": 5, "name": "Horror", "shuffle": "shuffle",
                      "content": ["It", "Scream"]}],
        "orphaned": [], "suggested_channels": [],
    }))
    (tmp_path / "config.json").write_text(json.dumps({
        "tunarr_url": "http://tunarr:8000", "tmdb_api_key": "k",
    }))
    return tmp_path


@pytest.fixture
def tunarr_ok(monkeypatch):
    """A deployed Tunarr channel #5 plus capture of icon writes."""
    calls = {}
    monkeypatch.setattr(channel_engine, "find_channel_by_number",
                        lambda url, n: {"id": "tid-5", "number": n, "name": "Horror"})
    monkeypatch.setattr(icon_engine, "get_full_channel",
                        lambda url, cid: {"id": cid, "name": "Horror", "icon": {}})
    monkeypatch.setattr(icon_engine, "set_tunarr_channel_icon",
                        lambda url, ch, icon_url: calls.update(set=icon_url) or True)
    monkeypatch.setattr(icon_engine, "clear_tunarr_channel_icon",
                        lambda url, ch: calls.update(cleared=True) or True)
    monkeypatch.setattr(icon_engine, "upload_image_to_tunarr",
                        lambda url, png, fn: "http://tunarr:8000/images/uploads/b.png")
    monkeypatch.setattr(badge_renderer, "render_badge",
                        lambda name, kind=None, genre=None: b"\x89PNGfake")
    return calls


def _call(number, body):
    return asyncio.run(channels_router.channel_icon(number, body))


def _saved_channel(tmp_path):
    data = json.loads((tmp_path / "channels.json").read_text())
    return data["channels"][0]


def test_badge_mode_uploads_sets_and_pins(chdir_data, tunarr_ok):
    res = _call(5, {"mode": "badge"})
    assert res["ok"] is True
    assert tunarr_ok["set"] == "http://tunarr:8000/images/uploads/b.png"
    pin = _saved_channel(chdir_data)["icon"]
    assert pin == {"mode": "badge",
                   "url": "http://tunarr:8000/images/uploads/b.png",
                   "pinned": True}


def test_custom_mode_sets_given_url(chdir_data, tunarr_ok):
    res = _call(5, {"mode": "custom", "url": "http://x/i.png"})
    assert res["url"] == "http://x/i.png"
    assert tunarr_ok["set"] == "http://x/i.png"
    assert _saved_channel(chdir_data)["icon"]["mode"] == "custom"


def test_custom_mode_requires_url(chdir_data, tunarr_ok):
    with pytest.raises(HTTPException) as e:
        _call(5, {"mode": "custom"})
    assert e.value.status_code == 409


def test_clear_mode_unpins(chdir_data, tunarr_ok):
    _call(5, {"mode": "badge"})
    res = _call(5, {"mode": "clear"})
    assert res["ok"] is True
    assert tunarr_ok["cleared"] is True
    assert "icon" not in _saved_channel(chdir_data)


def test_tmdb_mode_409_when_no_verified_logo(chdir_data, tunarr_ok, monkeypatch):
    monkeypatch.setattr(icon_engine, "resolve_tmdb_logo", lambda a, k: None)
    with pytest.raises(HTTPException) as e:
        _call(5, {"mode": "tmdb"})
    assert e.value.status_code == 409


def test_tmdb_mode_sets_verified_logo(chdir_data, tunarr_ok, monkeypatch):
    monkeypatch.setattr(icon_engine, "resolve_tmdb_logo",
                        lambda a, k: "http://img/logo.png")
    res = _call(5, {"mode": "tmdb"})
    assert res["url"] == "http://img/logo.png"
    assert _saved_channel(chdir_data)["icon"]["mode"] == "tmdb"


def test_unknown_channel_404(chdir_data, tunarr_ok):
    with pytest.raises(HTTPException) as e:
        _call(99, {"mode": "badge"})
    assert e.value.status_code == 404


def test_undeployed_channel_409(chdir_data, tunarr_ok, monkeypatch):
    monkeypatch.setattr(channel_engine, "find_channel_by_number", lambda u, n: None)
    with pytest.raises(HTTPException) as e:
        _call(5, {"mode": "badge"})
    assert e.value.status_code == 409


def test_bad_mode_422(chdir_data, tunarr_ok):
    with pytest.raises(HTTPException) as e:
        _call(5, {"mode": "sparkly"})
    assert e.value.status_code == 422
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest backend/tests/test_channel_icons.py -v
```

Expected: FAIL — `AttributeError: module ... has no attribute 'channel_icon'`.

- [ ] **Step 3: Implement the endpoint in `backend/routers/channels_router.py`**

Add to the imports block (after `import scheduler`):

```python
import badge_renderer  # noqa: E402
import icon_engine     # noqa: E402
```

Add after the `apply_channel` endpoint:

```python
@router.post("/channels/{number}/icon")
async def channel_icon(number: int, body: dict):
    """Set or pin a channel's Tunarr icon.

    body: {"mode": "badge" | "tmdb" | "custom" | "clear", "url": "..."(custom only)}
    badge/tmdb/custom write a pin into channels.json ("icon": {..., "pinned": true})
    so automatic art passes (fetch_images.py) skip the channel; "clear" resets the
    Tunarr icon to default and removes the pin (back to automatic).
    """
    mode = (body or {}).get("mode")
    if mode not in ("badge", "tmdb", "custom", "clear"):
        raise HTTPException(422, "mode must be one of: badge, tmdb, custom, clear")

    data = load()
    ch = next((c for c in data.get("channels", []) if c.get("number") == number), None)
    if ch is None:
        raise HTTPException(404, f"Channel {number} not in channels.json")

    cfg = _load_config()
    tunarr_url = cfg.get("tunarr_url", "").rstrip("/")
    if not tunarr_url:
        raise HTTPException(400, "Tunarr not configured")

    name = (ch.get("name") or "").strip()

    def _do():
        summary = channel_engine.find_channel_by_number(tunarr_url, number)
        if summary is None:
            raise channel_engine.ChannelEngineError(
                f"Channel #{number} not in Tunarr — deploy it first")
        tch = icon_engine.get_full_channel(tunarr_url, summary["id"])
        if tch is None:
            raise channel_engine.ChannelEngineError("Could not read channel from Tunarr")

        if mode == "clear":
            if not icon_engine.clear_tunarr_channel_icon(tunarr_url, tch):
                raise channel_engine.ChannelEngineError("Tunarr icon reset failed")
            return ""

        if mode == "custom":
            url = (body.get("url") or "").strip()
            if not url:
                raise channel_engine.ChannelEngineError("url required for custom mode")
        elif mode == "badge":
            spec = icon_engine.load_spec_hints(
                DATA_DIR / "planner_state.json").get(name.lower(), {})
            png = badge_renderer.render_badge(
                name, kind=spec.get("kind"), genre=icon_engine.spec_genre(spec))
            url = icon_engine.upload_image_to_tunarr(
                tunarr_url, png, f"programmarr-ch{number}-{os.urandom(4).hex()}.png")
        else:  # tmdb
            key = cfg.get("tmdb_api_key", "")
            if not key:
                raise channel_engine.ChannelEngineError(
                    "tmdb_api_key not configured — use a badge or custom URL")
            spec = icon_engine.load_spec_hints(
                DATA_DIR / "planner_state.json").get(name.lower(), {})
            url = icon_engine.resolve_tmdb_logo(
                icon_engine.icon_attempts(ch, spec.get("kind")), key)
            if not url:
                raise channel_engine.ChannelEngineError(
                    "No verified TMDB logo for this channel — use a badge or custom URL")

        if not icon_engine.set_tunarr_channel_icon(tunarr_url, tch, url):
            raise channel_engine.ChannelEngineError("Tunarr icon update failed")
        return url

    try:
        async with scheduler.deploy_lock:
            url = await asyncio.to_thread(_do)
    except channel_engine.ChannelEngineError as e:
        raise HTTPException(409, str(e))

    if mode == "clear":
        ch.pop("icon", None)
    else:
        ch["icon"] = {"mode": mode, "url": url, "pinned": True}
    save(data)
    return {"ok": True, "mode": mode, "url": url}
```

Note: `os` is already imported at the top of `channels_router.py`. `DATA_DIR` is module-level — the test monkeypatches it.

- [ ] **Step 4: Run the new tests, then the whole suite**

```bash
pytest backend/tests/test_channel_icons.py -v && pytest
```

Expected: all PASS.

- [ ] **Step 5: Document the endpoint in `docs/api.md`**

In the channels endpoints table, add (matching the table's existing style):

```markdown
| POST | `/api/channels/{number}/icon` | Set/pin the channel's Tunarr icon. Body `{"mode": "badge"\|"tmdb"\|"custom"\|"clear", "url"?}`. badge/tmdb/custom pin the choice in channels.json (skipped by automatic art passes); clear resets to the Tunarr default and unpins. 409 if the channel isn't deployed or no verified TMDB logo exists. |
```

- [ ] **Step 6: Commit**

```bash
git add backend/routers/channels_router.py backend/tests/test_channel_icons.py docs/api.md
git commit -m "feat(icons): POST /channels/{number}/icon — manual icon control with pinning

badge/tmdb/custom set the Tunarr icon and pin the choice in channels.json
(fetch_images skips pinned channels); clear resets to default and unpins.
Holds the deploy lock; update-in-place on the existing Tunarr id."
```

---

### Task 8: Channels-editor icon control (frontend)

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/Channels.tsx` (inside `ChannelModal`)

- [ ] **Step 1: Add the type + API method to `frontend/src/api/client.ts`**

Add near the other channel interfaces (around `Channel`, line ~185):

```ts
export interface ChannelIcon { mode: 'badge' | 'tmdb' | 'custom'; url?: string; pinned?: boolean }
```

Add `icon?: ChannelIcon;` as a new optional field on the existing `Channel` interface (do not remove or reorder existing fields).

Add to the `api` object, after `deleteChannel`:

```ts
setChannelIcon: (n: number, body: { mode: 'badge' | 'tmdb' | 'custom' | 'clear'; url?: string }) =>
  req<{ ok: boolean; mode: string; url: string }>(`/channels/${n}/icon`, {
    method: 'POST',
    body: JSON.stringify(body),
  }),
```

- [ ] **Step 2: Add the icon section to `ChannelModal` in `frontend/src/pages/Channels.tsx`**

Inside the `ChannelModal` component, add state next to the existing commercials state (~line 187):

```tsx
// Channel icon
const [iconBusy, setIconBusy] = useState<string | null>(null);
const [iconUrl, setIconUrl] = useState('');
const [customIconUrl, setCustomIconUrl] = useState('');
```

In the effect that populates the form from the loaded `channel` (where `commercials` is read, ~line 201), add:

```tsx
setIconUrl(channel.icon?.url ?? '');
setCustomIconUrl('');
```

Add the handler next to `persist`/`saveAndApply`:

```tsx
async function applyIcon(mode: 'badge' | 'tmdb' | 'custom' | 'clear') {
  if (!channel) return;
  setIconBusy(mode);
  try {
    const res = await api.setChannelIcon(
      channel.number,
      mode === 'custom' ? { mode, url: customIconUrl.trim() } : { mode },
    );
    setIconUrl(res.url);
    notifications.show({
      message: mode === 'clear' ? 'Icon reset to automatic' : 'Channel icon updated',
      color: 'green',
    });
  } catch (e: any) {
    notifications.show({ title: 'Icon update failed', message: e.message, color: 'red' });
  } finally {
    setIconBusy(null);
  }
}
```

Add the JSX after the Commercials block (the `<Divider label="Commercials" ...>` section) and before the modal's action buttons. Render it only when editing an existing channel:

```tsx
{channel && (
  <>
    <Divider label="Channel icon" labelPosition="left" />
    {iconUrl && (
      <img src={iconUrl} alt="channel icon"
           style={{ height: 48, width: 48, objectFit: 'contain', alignSelf: 'flex-start' }} />
    )}
    <Group gap="xs">
      <Button size="xs" variant="light" loading={iconBusy === 'badge'}
              onClick={() => applyIcon('badge')}>
        Use badge
      </Button>
      <Button size="xs" variant="light" loading={iconBusy === 'tmdb'}
              onClick={() => applyIcon('tmdb')}>
        Re-fetch TMDB logo
      </Button>
      <Button size="xs" variant="subtle" color="gray" loading={iconBusy === 'clear'}
              onClick={() => applyIcon('clear')}>
        Reset to automatic
      </Button>
    </Group>
    <Group gap="xs">
      <TextInput size="xs" placeholder="https://… custom icon URL"
                 value={customIconUrl} style={{ flex: 1 }}
                 onChange={(e) => setCustomIconUrl(e.currentTarget.value)} />
      <Button size="xs" variant="light" disabled={!customIconUrl.trim()}
              loading={iconBusy === 'custom'} onClick={() => applyIcon('custom')}>
        Set
      </Button>
    </Group>
    <Text size="xs" c="dimmed">
      Choosing an icon pins it — automatic art passes skip this channel. “Reset to
      automatic” unpins it.
    </Text>
  </>
)}
```

Check the imports at the top of `Channels.tsx`: `Button`, `Group`, `Divider`, `Text`, `TextInput` and `notifications` are all already imported (verify; add any that are missing to the existing import statements rather than new ones).

- [ ] **Step 3: Type-check and build**

```bash
cd frontend && npx tsc --noEmit && npm run build && cd ..
```

Expected: no type errors, build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/pages/Channels.tsx
git commit -m "feat(icons): Channels-editor icon control — badge / TMDB / custom / reset

Per-channel escape hatch for the rare wrong or ugly icon. Choices pin in
channels.json via POST /channels/{number}/icon so automatic art passes
respect them; reset returns the channel to automatic."
```

---

### Task 9: Docs sweep

**Files:**
- Modify: `CLAUDE.md` (Known Limitations, Configuration, channels.json schema)
- Modify: `docs/ideas.md`

- [ ] **Step 1: Update CLAUDE.md "Known Limitations"**

Replace the existing "Plex guide shows channel icons, not text names." paragraph's last two sentences (from "`fetch_images.py` gives solo-title channels…" to "…Refreshing/restarting Plex does not change this.") with:

```markdown
`fetch_images.py` now gives **every** channel an icon: verified TMDB logos where
trustworthy, generated name-stamped badges everywhere else — so the guide is readable even
though Plex hides the text labels. Refreshing/restarting Plex does not change the
icon-suppression behavior itself.
```

- [ ] **Step 2: Update CLAUDE.md Configuration section**

Change the `tmdb_api_key` line to:

```markdown
- `tmdb_api_key` — optional; used by `fetch_images.py` for verified TMDB logo lookups.
  Without it, every channel gets a generated badge instead (icons still work). Free key at
  https://www.themoviedb.org/settings/api
```

- [ ] **Step 3: Update CLAUDE.md channels.json schema section**

After the **Commercials (optional).** paragraph, add:

```markdown
**Icon pin (optional).** A channel may carry `"icon": {"mode": "badge"|"tmdb"|"custom",
"url": "…", "pinned": true}` — written only by `POST /api/channels/{number}/icon` (the
Channels-editor icon control). `fetch_images.py` skips pinned channels and never writes
this field; removing it (the editor's "Reset to automatic") returns the channel to the
automatic art pass.
```

- [ ] **Step 4: Update `docs/ideas.md`**

Delete the "Logos for multi-title channels." bullet (it's built now). If surrounding text references it, adjust minimally.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/ideas.md
git commit -m "docs: icon overhaul — badges for all channels, optional tmdb_api_key, icon pins"
```

---

### Task 10: Final verification (run by the orchestrator, not a subagent)

- [ ] **Step 1: Full test suite**

```bash
pytest
```

Expected: everything passes.

- [ ] **Step 2: Frontend build**

```bash
cd frontend && npx tsc --noEmit && npm run build && cd ..
```

- [ ] **Step 3: Docker parity build (repo rule: before shipping)**

```bash
docker compose build
```

Expected: image builds — proves the Dockerfile COPY additions (icon_engine, badge_renderer, badge_assets) and the Pillow install are correct.

- [ ] **Step 4: Live smoke (requires the user's real Tunarr — coordinate with the user)**

```bash
.venv/bin/python fetch_images.py            # dry run against real channels.json
```

Inspect the dry-run output: badge-only kinds must show `badge (...)`, no channel may show a TMDB logo whose name doesn't match its query. Then, with user approval, `--apply` and eyeball the Plex/Tunarr guide.

---

## Self-review notes

- Spec coverage: kind gating (T3), verified match (T2), badge pack + stamping (T1, T5), Tunarr upload (T4), keyless operation (T6), editor control + pinning (T7, T8), docs (T6, T7, T9). Deploy cascade needs no change — `POST /pipeline/images` already runs `fetch_images.py --apply`.
- Naming consistency: `icon_attempts` / `resolve_tmdb_logo` / `load_spec_hints` / `spec_genre` / `set_tunarr_channel_icon` / `clear_tunarr_channel_icon` / `upload_image_to_tunarr` / `get_full_channel` / `render_badge` used identically across Tasks 2–8.
- Invariants respected: `fetch_images.py` never writes `channels.json`; the icon endpoint holds `scheduler.deploy_lock` and updates in place on the existing Tunarr id; no delete/recreate anywhere.
