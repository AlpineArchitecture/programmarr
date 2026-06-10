# Release-Gated Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple the public `:latest` Docker image from master pushes so end users only receive a new image when a *version is released*, and give them an in-app "update available" notifier (replacing Watchtower-by-default) so they upgrade on their own terms.

**Architecture:** Four independent workstreams. **(A)** CI: `:latest` publishes only on a GitHub Release; master pushes run a non-publishing build-check. **(B)** A backend `/api/update-check` endpoint polls the GitHub Releases API (cached 6h, privacy-toggleable) + a dismissible frontend banner. **(C)** Docs/compose: manual-pull becomes the default, Watchtower becomes an opt-in. **(D)** Git-workflow simplification: master becomes the development trunk; `/release` is the only thing that ships; the `/ship` and `/release` skills + CLAUDE.md are rewritten to match.

**Tech Stack:** GitHub Actions (`docker/metadata-action`, `docker/build-push-action`), FastAPI + `urllib` (stdlib, no new deps), React + Mantine v7, pytest.

**Decisions locked during brainstorming (do not re-litigate):**
- `:latest` = release-only (the world tracks it). Master pushes publish nothing.
- The notifier *fetches + caches server-side* (privacy/rate-limit); the frontend supplies its own `current` version so no version needs baking into the backend.
- Source of truth for "newest release" = GitHub Releases API `/releases/latest` (returns the newest *published* release, which after (A) is exactly what users should run).
- Update check is **on by default** with a Settings opt-out (matches Tunarr/Plex/*arr norms).
- Master is the trunk; the release-readiness gate moves from *every commit* to *tag time*.

---

## File Structure

| File | Workstream | Responsibility |
|---|---|---|
| `.github/workflows/docker.yml` | A | Tag matrix + conditional push: latest/semver on release, build-check on master |
| `backend/routers/status_router.py` | B | `_parse_semver`, `is_newer`, `_fetch_latest_release`, `GET /update-check` |
| `backend/routers/config_router.py` | B | Persist `update_check_enabled` bool (special-cased past the falsy-prune) |
| `backend/tests/test_update_check.py` | B | Unit tests for version compare + endpoint gating/caching |
| `frontend/src/api/client.ts` | B | `api.updateCheck()` + `UpdateInfo` type |
| `frontend/src/components/UpdateBanner.tsx` | B | Dismissible "update available" banner (per-version localStorage) |
| `frontend/src/components/AppLayout.tsx` | B | Mount `<UpdateBanner/>` |
| `frontend/src/pages/Settings.tsx` | B | "Check for updates" toggle wired to config |
| `README.md` | C | Manual-update default; Watchtower demoted to optional |
| `~/.claude/skills/ship/SKILL.md` | D | Rewrite: commit-where-you-are, no master guard |
| `~/.claude/skills/release/SKILL.md` | D | Rewrite: trunk model, release = tag, latest=release-only |
| `CLAUDE.md` | D | Rewrite Git Workflow + correct the "every master push deploys" claims |

Workstreams A–D are independent and can ship in any order / separate commits. Within a workstream, do the tasks in order.

---

## Workstream A — CI: `:latest` only on release

### Task A1: Make master pushes build-only; publish tags on release only

**Files:**
- Modify: `.github/workflows/docker.yml`

- [ ] **Step 1: Replace the workflow body**

Replace the entire contents of `.github/workflows/docker.yml` with:

```yaml
name: Build and push Docker image

on:
  push:
    branches: [master]      # build-check only — publishes NOTHING (see push: below)
  release:
    types: [published]      # the ONLY event that publishes :latest + version tags

permissions:
  contents: read
  packages: write

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      # Login only needed when we actually push (release). Master build-check skips it.
      - name: Log in to GHCR
        if: github.event_name == 'release'
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/alpinearchitecture/programmarr
          tags: |
            type=raw,value=latest,enable=${{ github.event_name == 'release' }}
            type=semver,pattern={{version}}
            type=semver,pattern=v{{major}}.{{minor}}
            type=sha,prefix=sha-,format=short,enable=${{ github.event_name == 'release' }}

      # push: true ONLY on a release. On a master push this is a pure build-check —
      # it proves the image compiles but pushes nothing to GHCR, so no user ever pulls it.
      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          push: ${{ github.event_name == 'release' }}
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
```

What changed vs. the old file and why:
- `latest` enable flips from `{{is_default_branch}}` (every master push) to `${{ github.event_name == 'release' }}` — **this is the core fix.**
- `push:` is now `true` only on a release; a master push builds with `push: false` (the build-check).
- Login step gated to releases (build-check needs no registry auth).
- `sha-` tag gated to releases too (master pushes publish nothing anyway).
- `type=semver` already only resolves on a tag ref (the release event), unchanged.

- [ ] **Step 2: Validate the YAML parses**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/docker.yml')); print('ok')"`
Expected: `ok` (if PyYAML missing, skip — GitHub will validate on push).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/docker.yml
git commit -F - <<'EOF'
ci: publish :latest only on release, build-check on master push

Decouples the world-facing :latest image from master pushes. Previously
`type=raw,value=latest,enable={{is_default_branch}}` republished :latest on
every master push, and end users run :latest + Watchtower — so any master
commit shipped to every home lab within ~5 min.

Now :latest (and the version/sha tags) publish ONLY on a GitHub Release.
A master push runs `docker build` with push:false: it proves the image
compiles but publishes nothing. Users receive an image only when a version
is cut, which is the whole point of the trunk + release-gate model.
EOF
```

> **Verification note (do at release time, not now):** after the next real `/release`, confirm `gh run list` shows the `release`-event run pushed `:latest`, and that a *plain master push* run shows "build-check" with nothing new on GHCR.

---

## Workstream B — In-app update notifier

### Task B1: Pure version-compare helpers (TDD)

**Files:**
- Modify: `backend/routers/status_router.py` (add helpers near the top, after the imports)
- Test: `backend/tests/test_update_check.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_update_check.py`:

```python
"""Update-notifier unit tests.

`is_newer` must do NUMERIC semver comparison (0.10.0 > 0.9.0, not lexical),
tolerate a leading 'v', and never raise on junk input — a broken check must
degrade to "no update", never crash the footer.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
for _p in (str(BACKEND), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from routers import status_router as sr


def test_is_newer_basic():
    assert sr.is_newer("0.6.0", "0.5.0") is True
    assert sr.is_newer("0.5.1", "0.5.0") is True
    assert sr.is_newer("1.0.0", "0.9.9") is True


def test_is_newer_equal_or_older():
    assert sr.is_newer("0.5.0", "0.5.0") is False
    assert sr.is_newer("0.5.0", "0.6.0") is False


def test_is_newer_numeric_not_lexical():
    # The classic bug: "0.10.0" < "0.9.0" lexically but is NEWER numerically.
    assert sr.is_newer("0.10.0", "0.9.0") is True


def test_is_newer_tolerates_v_prefix():
    assert sr.is_newer("v0.6.0", "0.5.0") is True


def test_is_newer_no_current_is_false():
    assert sr.is_newer("0.6.0", "") is False


def test_is_newer_junk_is_false():
    assert sr.is_newer("not-a-version", "0.5.0") is False
    assert sr.is_newer("", "0.5.0") is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest backend/tests/test_update_check.py -v`
Expected: FAIL — `AttributeError: module 'routers.status_router' has no attribute 'is_newer'`.

- [ ] **Step 3: Implement the helpers**

In `backend/routers/status_router.py`, after the existing `import` block and before `router = APIRouter()`, add:

```python
import time

GITHUB_LATEST_RELEASE = (
    "https://api.github.com/repos/AlpineArchitecture/programmarr/releases/latest"
)


def _parse_semver(s: str) -> tuple[int, int, int]:
    """'v0.10.1' -> (0, 10, 1). Tolerant: missing parts -> 0; a pre-release suffix
    on a part ('1-beta') keeps only the leading digits. Raises ValueError on no digits."""
    s = (s or "").strip().lstrip("vV")
    if not s:
        raise ValueError("empty version")
    out = []
    for part in s.split(".")[:3]:
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)  # type: ignore[return-value]


def is_newer(latest: str, current: str) -> bool:
    """True iff `latest` is a strictly higher semver than `current`. Never raises;
    any unparseable input (or empty `current`) yields False so a failed check
    degrades to 'no update' rather than crashing the UI."""
    try:
        return _parse_semver(latest) > _parse_semver(current)
    except Exception:
        return False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_update_check.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/routers/status_router.py backend/tests/test_update_check.py
git commit -F - <<'EOF'
feat(backend): add semver compare helpers for the update notifier

is_newer() does numeric (not lexical) semver comparison so 0.10.0 reads as
newer than 0.9.0, tolerates a leading 'v', and never raises — a broken
version string degrades to "no update available" instead of erroring.
EOF
```

### Task B2: `GET /api/update-check` endpoint (fetch + cache + gate)

**Files:**
- Modify: `backend/routers/status_router.py`
- Test: `backend/tests/test_update_check.py`

- [ ] **Step 1: Write the failing test (append to the test file)**

Append to `backend/tests/test_update_check.py`:

```python
import pytest


@pytest.fixture(autouse=True)
def _reset_update_cache():
    """Each test starts with an empty notifier cache."""
    sr._update_cache["at"] = 0.0
    sr._update_cache["data"] = None
    yield


def test_update_check_disabled_returns_enabled_false(monkeypatch):
    monkeypatch.setattr(sr, "load_config", lambda: {"update_check_enabled": False})
    # Even if a fetch would succeed, disabled short-circuits before any network call.
    monkeypatch.setattr(sr, "_fetch_latest_release", lambda: (_ for _ in ()).throw(AssertionError("must not fetch")))
    out = sr.update_check(current="0.5.0")
    assert out == {"enabled": False}


def test_update_check_reports_available(monkeypatch):
    monkeypatch.setattr(sr, "load_config", lambda: {})  # absent key => enabled by default
    monkeypatch.setattr(sr, "_fetch_latest_release", lambda: {
        "latest": "0.6.0", "name": "v0.6.0", "url": "https://example/releases/v0.6.0",
    })
    out = sr.update_check(current="0.5.0")
    assert out["enabled"] is True
    assert out["update_available"] is True
    assert out["latest"] == "0.6.0"
    assert out["url"] == "https://example/releases/v0.6.0"


def test_update_check_up_to_date(monkeypatch):
    monkeypatch.setattr(sr, "load_config", lambda: {})
    monkeypatch.setattr(sr, "_fetch_latest_release", lambda: {
        "latest": "0.5.0", "name": "v0.5.0", "url": "x",
    })
    out = sr.update_check(current="0.5.0")
    assert out["update_available"] is False


def test_update_check_caches_within_ttl(monkeypatch):
    monkeypatch.setattr(sr, "load_config", lambda: {})
    calls = {"n": 0}

    def fake_fetch():
        calls["n"] += 1
        return {"latest": "0.6.0", "name": "v0.6.0", "url": "x"}

    monkeypatch.setattr(sr, "_fetch_latest_release", fake_fetch)
    sr.update_check(current="0.5.0")
    sr.update_check(current="0.5.0")
    assert calls["n"] == 1, "second call within TTL must use the cache, not refetch"


def test_update_check_fetch_failure_is_safe(monkeypatch):
    monkeypatch.setattr(sr, "load_config", lambda: {})
    monkeypatch.setattr(sr, "_fetch_latest_release", lambda: None)  # network down
    out = sr.update_check(current="0.5.0")
    assert out["enabled"] is True
    assert out["update_available"] is False
    assert out["latest"] is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest backend/tests/test_update_check.py -v`
Expected: FAIL — `AttributeError: ... has no attribute '_update_cache'` / `update_check`.

- [ ] **Step 3: Implement the cache, fetcher, and endpoint**

In `backend/routers/status_router.py`, add the module-level cache next to the `GITHUB_LATEST_RELEASE` constant from B1:

```python
# Notifier cache: one GitHub hit per _UPDATE_TTL seconds, regardless of UI loads.
_UPDATE_TTL = 6 * 3600
_update_cache: dict = {"at": 0.0, "data": None}
```

Then add the fetcher and endpoint (place the endpoint among the other `@router.get` handlers):

```python
def _fetch_latest_release() -> dict | None:
    """Hit the GitHub Releases API for the newest published release. Returns
    {latest, name, url} or None on any failure. GitHub requires a User-Agent."""
    try:
        req = urllib.request.Request(
            GITHUB_LATEST_RELEASE,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "programmarr"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            rel = json.loads(r.read())
        return {
            "latest": (rel.get("tag_name") or "").lstrip("vV"),
            "name": rel.get("name") or rel.get("tag_name") or "",
            "url": rel.get("html_url") or "",
        }
    except Exception:
        return None


@router.get("/update-check")
def update_check(current: str = ""):
    """Is a newer release available? `current` is the running app version (the
    frontend passes its baked-in package.json version). Off when the user has
    disabled update checks. Result cached server-side for _UPDATE_TTL."""
    cfg = load_config()
    if not cfg.get("update_check_enabled", True):
        return {"enabled": False}

    now = time.time()
    if now - _update_cache["at"] > _UPDATE_TTL:
        # Bound to one fetch per TTL even on failure: keep any prior (stale) data,
        # accept a 6h gap on outage rather than hammering GitHub from a home lab.
        fetched = _fetch_latest_release()
        if fetched is not None:
            _update_cache["data"] = fetched
        _update_cache["at"] = now

    data = _update_cache["data"]
    if not data:
        return {"enabled": True, "update_available": False, "current": current, "latest": None}
    return {
        "enabled": True,
        "update_available": is_newer(data["latest"], current) if current else False,
        "current": current,
        "latest": data["latest"],
        "name": data["name"],
        "url": data["url"],
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest backend/tests/test_update_check.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add backend/routers/status_router.py backend/tests/test_update_check.py
git commit -F - <<'EOF'
feat(backend): add GET /api/update-check endpoint

Server-side poll of the GitHub Releases API (cached 6h, one hit per TTL even
on failure) comparing the newest published release against the running
version the frontend passes as ?current=. Honors update_check_enabled
(default on); returns {"enabled": false} when the user opts out. Network
failure degrades to "no update", never an error.
EOF
```

### Task B3: Persist the `update_check_enabled` toggle past the falsy-prune

**Files:**
- Modify: `backend/routers/config_router.py`
- Test: `backend/tests/test_update_check.py`

> **Why this is its own task — the gotcha:** `config_router.save_config` prunes falsy
> values (`for k, v in data.items(): if v: merged[k] = v else: merged.pop(...)`). A plain
> `bool` field set to **False** would be *deleted*, so the toggle could never persist "off".
> We special-case it exactly like `channel_order` is special-cased: pop it out before the
> prune and always write it explicitly.

- [ ] **Step 1: Write the failing test (append to the test file)**

Append to `backend/tests/test_update_check.py`:

```python
import json as _json
import importlib


def test_update_check_enabled_persists_false(tmp_path, monkeypatch):
    """A False toggle must survive save_config's falsy-prune."""
    monkeypatch.setenv("PROGRAMMARR_DATA", str(tmp_path))
    from routers import config_router as cr
    importlib.reload(cr)  # re-bind DATA_DIR to the temp dir

    cr.save_config(cr.ConfigModel(update_check_enabled=False))
    saved = _json.loads((tmp_path / "config.json").read_text())
    assert saved["update_check_enabled"] is False

    cr.save_config(cr.ConfigModel(update_check_enabled=True))
    saved = _json.loads((tmp_path / "config.json").read_text())
    assert saved["update_check_enabled"] is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest backend/tests/test_update_check.py::test_update_check_enabled_persists_false -v`
Expected: FAIL — `KeyError: 'update_check_enabled'` (field doesn't exist / got pruned).

- [ ] **Step 3: Add the field to `ConfigModel`**

In `backend/routers/config_router.py`, add to `ConfigModel` (after `channel_order`):

```python
    # Whether the app polls GitHub for a newer release (the in-app update banner).
    # Default on; stored explicitly so the falsy-prune below can't drop a False.
    update_check_enabled: bool = True
```

- [ ] **Step 4: Special-case it in `save_config`**

In `save_config`, just after the `order = data.pop("channel_order", None) or []` line, add:

```python
    # Booleans must bypass the falsy-prune below (False is falsy → would be deleted).
    update_check = bool(data.pop("update_check_enabled", True))
```

Then, just after the `if order: merged["channel_order"] = order` line, add:

```python
    merged["update_check_enabled"] = update_check
```

- [ ] **Step 5: Run to verify pass**

Run: `pytest backend/tests/test_update_check.py -v`
Expected: PASS (all tests, including the new persistence test).

- [ ] **Step 6: Commit**

```bash
git add backend/routers/config_router.py backend/tests/test_update_check.py
git commit -F - <<'EOF'
feat(backend): persist update_check_enabled toggle

Adds the bool to ConfigModel and special-cases it in save_config (popped out
before the falsy-prune, always written explicitly) so a False value isn't
silently dropped — same pattern as channel_order. Default on.
EOF
```

### Task B4: Frontend API client method + type

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add the type** (in the `// ── Types ──` section, near `ConnStatus`):

```typescript
export interface UpdateInfo {
  enabled: boolean;
  update_available?: boolean;
  current?: string;
  latest?: string | null;
  name?: string;
  url?: string;
}
```

- [ ] **Step 2: Add the API method** (inside the `api` object, next to `getStatus`):

```typescript
  updateCheck: (current: string) =>
    req<UpdateInfo>(`/update-check?current=${encodeURIComponent(current)}`),
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat(frontend): add api.updateCheck() client method + UpdateInfo type"
```

### Task B5: The dismissible update banner

**Files:**
- Create: `frontend/src/components/UpdateBanner.tsx`
- Modify: `frontend/src/components/AppLayout.tsx`

- [ ] **Step 1: Create the banner component**

Create `frontend/src/components/UpdateBanner.tsx`:

```tsx
import { Alert, Anchor, Code, Group, Text } from '@mantine/core';
import { IconArrowUpCircle } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { version } from '../../package.json';
import { api, type UpdateInfo } from '../api/client';

const DISMISS_KEY = 'programmarr.updateDismissed';

/**
 * Polls /api/update-check once on mount and shows a banner when a newer release
 * exists. Dismissal is remembered PER VERSION (localStorage holds the dismissed
 * `latest`), so dismissing v0.6.0 stays quiet until v0.7.0 ships.
 */
export default function UpdateBanner() {
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [dismissed, setDismissed] = useState<string | null>(
    () => localStorage.getItem(DISMISS_KEY),
  );

  useEffect(() => {
    api.updateCheck(version).then(setInfo).catch(() => {});
  }, []);

  if (!info?.update_available || !info.latest) return null;
  if (dismissed === info.latest) return null;

  function dismiss() {
    if (info?.latest) {
      localStorage.setItem(DISMISS_KEY, info.latest);
      setDismissed(info.latest);
    }
  }

  return (
    <Alert
      icon={<IconArrowUpCircle size={18} />}
      color="orange"
      variant="light"
      withCloseButton
      onClose={dismiss}
      mb="md"
    >
      <Group gap="xs" wrap="wrap">
        <Text size="sm" fw={600}>
          Update available: v{info.latest}
        </Text>
        {info.url && (
          <Anchor size="sm" href={info.url} target="_blank" rel="noreferrer">
            release notes
          </Anchor>
        )}
        <Text size="sm" c="dimmed">
          Pull it with <Code>docker compose pull &amp;&amp; docker compose up -d</Code>
        </Text>
      </Group>
    </Alert>
  );
}
```

- [ ] **Step 2: Mount it at the top of the main content area**

In `frontend/src/components/AppLayout.tsx`:

Add the import after the existing icon imports (line ~14):

```tsx
import UpdateBanner from './UpdateBanner';
```

Change the main area (currently `<AppShell.Main>{children}</AppShell.Main>`, line ~90) to:

```tsx
      <AppShell.Main>
        <UpdateBanner />
        {children}
      </AppShell.Main>
```

- [ ] **Step 3: Build the frontend to verify it compiles**

Run: `cd frontend && npm run build`
Expected: build succeeds, no TypeScript errors. (Or use the `build-ui` skill.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/UpdateBanner.tsx frontend/src/components/AppLayout.tsx
git commit -F - <<'EOF'
feat(frontend): in-app "update available" banner

Polls /api/update-check on mount and shows a dismissible banner when a newer
release exists, linking the release notes and the one-line pull command.
Dismissal is per-version (localStorage), so it reappears on the NEXT release.
EOF
```

### Task B6: Settings toggle for the update check

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`

- [ ] **Step 1: Add state + load**

In `Settings()`, add to the `values` initial state object (after `auth_password: ''`):

```tsx
    update_check_enabled: true,
```

And in the `api.getConfig().then((cfg) => { ... })` block, add to the `setValues({...})` call (after the `auth_password:` line):

```tsx
        update_check_enabled: cfg.update_check_enabled !== false,
```

- [ ] **Step 2: Add the toggle card**

In the JSX, immediately after the closing `</Card>` of the **Auth** card (before the **Channel ordering** card), insert:

```tsx
      {/* Updates */}
      <Card p="lg">
        <Text fw={700} mb={4}>Updates</Text>
        <Text size="xs" c="dimmed" mb="md">
          Check GitHub for new Programmarr releases and show a banner when one is available.
          Turning this off stops the app from contacting GitHub. New images only ever publish
          on a release — your container never auto-updates unless you add Watchtower yourself.
        </Text>
        <Switch
          checked={values.update_check_enabled}
          onChange={(e) =>
            setValues((v) => ({ ...v, update_check_enabled: e.currentTarget.checked }))
          }
          color="orange"
          label="Check for updates"
        />
      </Card>
```

> Note: `Switch` is already imported in this file (used by the Live Channels card). The
> existing `save()` posts `{ ...values, channel_order }`, so `update_check_enabled` is sent
> automatically — no change to `save()` needed.

- [ ] **Step 3: Build to verify it compiles**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Settings.tsx
git commit -m "feat(frontend): add 'Check for updates' toggle to Settings"
```

### Task B7: Full backend suite + CLAUDE.md API note

**Files:**
- Modify: `CLAUDE.md` (the API Endpoints pointer area — note the new endpoint) and `docs/api.md` if it enumerates endpoints
- Modify: `docs/api.md`

- [ ] **Step 1: Run the whole backend suite to confirm nothing regressed**

Run: `pytest`
Expected: all tests pass (existing suite + `test_update_check.py`).

- [ ] **Step 2: Document the endpoint in `docs/api.md`**

Read `docs/api.md`, find the table where the other `status_router` endpoints live (`/status`, `/guide`, `/tunarr/channels`, `/tunarr/filler-lists`), and add a row:

```
| `GET` | `/api/update-check?current=<semver>` | Newest published release vs. running version (cached 6h; honors `update_check_enabled`). Returns `{enabled, update_available, latest, url, ...}`. |
```

- [ ] **Step 3: Commit (docs)**

```bash
git add docs/api.md CLAUDE.md
git commit -m "docs: document GET /api/update-check"
```

---

## Workstream C — Docs: manual update default, Watchtower optional

### Task C1: Rewrite the README update section

**Files:**
- Modify: `README.md` (the install + Watchtower region — grep showed it spans roughly lines 31–95)

- [ ] **Step 1: Read the current section**

Read `README.md` lines 25–100 to see the exact current "pulls automatically" + Watchtower compose blocks.

- [ ] **Step 2: Reframe — manual update is the default, Watchtower is opt-in**

Edit the README so that:
1. The **default** quick-start compose has **no** Watchtower service — just the `programmarr` service on `:latest`.
2. A new **"Updating"** subsection states the model and the manual command:

```markdown
## Updating

Programmarr only publishes a new image when a **version is released** — your container
never changes on its own. When a new release is out, the app shows an **"update available"**
banner in the top bar with a link to the release notes. Update when it suits you:

```bash
docker compose pull && docker compose up -d
```

Your data (config, channels, library export) lives in the mounted `./data` volume and is
untouched by an update.

> Prefer hands-off? You can add [Watchtower](https://containrrr.dev/watchtower/) to
> auto-pull releases — see "Optional: automatic updates" below. Because images now publish
> only on releases, Watchtower will only ever pull *released versions*, never in-progress work.
```

3. Demote the existing Watchtower compose block under a clearly **optional** heading ("Optional: automatic updates with Watchtower"), keeping the `DOCKER_API_VERSION=1.44` note.

- [ ] **Step 3: Commit (docs — may go straight to master per the carve-out)**

```bash
git add README.md
git commit -F - <<'EOF'
docs: make manual update the default, Watchtower opt-in

Images now publish only on releases, and the app shows an in-app update
banner, so the recommended path is `docker compose pull && up -d` when you
choose. Watchtower moves to an explicit "optional automatic updates" section.
EOF
```

---

## Workstream D — Git-workflow simplification (skills + CLAUDE.md)

> These three files encode the OLD "master auto-deploys, never push code to it" model.
> After Workstream A that model is obsolete: master is the trunk, only a release ships.
> Rewrite all three together so the docs and the skills agree.

### Task D1: Rewrite the `/ship` skill — commit where you are

**Files:**
- Modify: `C:\Users\james\.claude\skills\ship\SKILL.md`

- [ ] **Step 1: Replace the skill body** with the trunk model. The new behavior:
  - **Remove the master branch-guard entirely** (steps 1's "STOP, you're on master" logic). Master is now a normal commit target.
  - New step 1: `git status` + `git branch --show-current`, just to report where work will land. Branches are optional (use one for big/risky work; commit small stuff straight to master).
  - Keep: build frontend if `frontend/src/` changed (stop on failure); keep `CLAUDE.md` in sync in the same commit; stage by name (never `config*.json`, `*.csv`, `backend/static/`, `data/`); verbose commit message via bash heredoc; push the current branch.
  - New closing note: "**Nothing you push here ships to users.** Images publish only on `/release`. Whether you're on master or a branch, this just saves work."

Write the full replacement file (keep the YAML frontmatter `name`/`description`, updating the description to drop "never master"):

```markdown
---
name: ship
description: Commit work to the current branch for the Programmarr project. Master is the development trunk — committing here is safe because images publish ONLY on /release, never on a push. Builds the frontend if frontend/src changed, keeps CLAUDE.md in sync, writes a verbose commit message, and pushes. Use when the user says "ship it", "commit", "save my work", "push".
---

`/ship` saves work to the current branch. **Nothing it pushes reaches users** — the public
`:latest` image publishes only when you cut a release (`/release`). Master is the development
trunk: commit small/low-risk work straight to it; use a `feature/`…`fix/`… branch when you
want isolation for a big or abandon-able change. See CLAUDE.md "Git Workflow".

1. **Report where this lands.** `git status` + `git branch --show-current`. If on a branch,
   everything below commits/pushes to that branch; if on master, straight to trunk. No guard —
   both are fine.

2. `git diff` to see exactly what changed.

3. **Build the frontend if any `frontend/src/` file changed:** `cd frontend && npm run build`.
   Stop and report on failure — never commit a broken build. `backend/static/` is gitignored;
   never stage it.

4. **Keep CLAUDE.md in sync** (it is tracked). If the change adds/removes a script, flag,
   endpoint, schema, or behavior, update CLAUDE.md in the SAME commit.

5. **Stage specific files by name.** Never stage `config*.json`, `*.csv`, `backend/static/`,
   `data/`, or `_archive/`.

6. **Verbose commit message** (what + why), bash heredoc (`git commit -F - <<'EOF' … EOF`) —
   not a PowerShell here-string.

7. **Push the current branch** (`git push -u origin "$(git branch --show-current)"`).

8. Confirm success; show the commit hash and branch. Remind: work goes live only via `/release`.

Always run from the project working directory.
```

- [ ] **Step 2: Commit** (skill files live outside the repo; commit separately or note they're personal config — they are not part of the Programmarr repo. If `~/.claude` is its own git repo, commit there; otherwise just save the file.)

### Task D2: Rewrite the `/release` skill — release = tag the trunk

**Files:**
- Modify: `C:\Users\james\.claude\skills\release\SKILL.md`

- [ ] **Step 1: Rewrite to the trunk model.** Key behavior changes from the current file:
  - Master is the trunk; a release **tags the current trunk state** rather than being "the only way code reaches master."
  - If the work to release sits on a feature branch, **merge it to master first** (`git checkout master && git merge --no-ff <branch>`), then proceed. If it's already on master (the common case now), skip the merge.
  - Keep: Docker parity verify (`docker compose build && up -d`, exercise the touched path at localhost:7979, `docker compose down`) — now the *primary* gate, since trunk is no longer pre-verified per-commit.
  - Keep: ask the SemVer version, bump `frontend/package.json` (no `v`) + `CHANGELOG.md`, sync CLAUDE.md, `npm run build`, commit `chore(release): prep vX.Y.Z`.
  - Keep: tag `vX.Y.Z`, push tag, **`gh release create`** (the event that publishes `:latest` — emphasize this even harder now, since a bare master push no longer publishes anything).
  - Update the "what triggers what" note: *master push → build-check only; GitHub Release → publishes `:latest` + version tags.*
  - Keep the Rollback section.

- [ ] **Step 2: Save the file.**

### Task D3: Rewrite the CLAUDE.md Git Workflow section

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Fix the now-false claims.** Find and correct:
  - The **"Local Development → Environments"** line: "new image on GHCR ~1 min after a master push; Watchtower picks it up within ~5 min" → describe release-only publishing.
  - The **"Git Workflow"** section header sentence: "`master` is **production**: every push triggers CI → GHCR → Watchtower → live redeploy within ~5 min." This is the core falsehood — rewrite.

- [ ] **Step 2: Replace the Git Workflow section** with the trunk model:

```markdown
## Git Workflow

**`master` is the development trunk.** Pushing to it ships **nothing** — a master push runs
a CI **build-check only** (`docker build` with `push: false`). The public `:latest` image —
which end users run via the `docker compose` in the README — publishes **only when a GitHub
Release is cut**. So users receive a new image exactly once per version, never on day-to-day
commits. This is the whole point: accumulate many changes on trunk, release them as one version.

**Two operations:**

1. **`/ship` — daily work.** Commit + push to the current branch. Small/low-risk work can go
   straight to master; use a short-lived `feature/…`/`fix/…`/`chore/…` branch for big or
   abandon-able changes, then merge to master when done. Nothing here deploys.

2. **`/release` — going live.** The single gate that publishes an image. Docker-verifies the
   current trunk, asks for the new semantic version, bumps `frontend/package.json` +
   `CHANGELOG.md`, tags `vX.Y.Z`, and cuts the GitHub Release — which fires the versioned GHCR
   build (`:latest`, `X.Y.Z`, `vX.Y`, `sha-…`). End users then see an in-app **update banner**
   (via `GET /api/update-check`) and pull on their own schedule.

**The release-readiness gate lives at TAG time, not commit time.** Don't cut a release while
trunk has half-finished work — but committing in-progress work to trunk is fine and expected.

**SemVer:** patch = fixes/tweaks; minor = new features/UI/flags/endpoints; major = breaking
pipeline/schema/API changes. `/release` suggests the bump and always confirms.

**Updates are opt-in for users.** The app polls GitHub for newer releases (toggle in Settings,
default on) and shows a banner. Watchtower is documented as an *optional* auto-pull; because
images publish only on releases, even Watchtower users only ever get released versions.

**Always:** commit in small focused chunks with verbose what+why messages; **never commit
secrets or personal data** (`config*.json`, `channels*.json`, `*.csv`, `PROMPT.personal.md`
stay gitignored); **keep this file in sync in the same commit** as any behavior change.
```

- [ ] **Step 3: Commit (docs — straight to master OK per the carve-out)**

```bash
git add CLAUDE.md
git commit -F - <<'EOF'
docs: rewrite Git Workflow for the trunk + release-only-ships model

master is now the development trunk; pushing runs a build-check only. The
public :latest image publishes ONLY on a GitHub Release, so users get one
image per version (not per master push), surfaced via the in-app update
banner. Corrects the old "every master push deploys" claims.
EOF
```

---

## Self-Review

**1. Spec coverage:**
- Q1 (`:latest` release-only) → **A1**. ✅
- Q2 (in-app notifier replaces Watchtower default) → **B1–B6** (endpoint + banner + toggle) and **C1** (README default). ✅
- Q3 (master = trunk) → **D1–D3**. ✅
- Q4 (local-Docker dogfood, no `:edge`) → no tag added; `/release`'s Docker-verify step (D2) is the dogfood gate. ✅
- Q5 (build-check on master push) → **A1** `push: false`. ✅
- Q7 (Releases API, server-side cache, on-by-default + opt-out, per-version dismiss) → **B2** (fetch+cache), **B3** (toggle persistence), **B5** (per-version dismiss). ✅

**2. Placeholder scan:** No "TBD"/"handle edge cases"/"add validation" — every code step has literal code. README/skill rewrites that can't be shown byte-exact (files not fully read here) are scoped to "read first, then apply this exact new text" with the full replacement text provided. ✅

**3. Type consistency:** `UpdateInfo` fields (`enabled`, `update_available`, `latest`, `url`, `name`, `current`) match the endpoint's return dict in B2 and the banner's usage in B5. `update_check_enabled` spelled identically in ConfigModel (B3), Settings (B6), endpoint (B2), and CLAUDE.md (D3). `is_newer(latest, current)` argument order consistent between B1 definition and B2 call. ✅

---

## Execution Handoff

Suggested order: **A → B → C → D** (A is the highest-value one-file fix; B is the feature; C/D are docs/process). Each workstream is independently shippable.
```