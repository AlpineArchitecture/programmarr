# Claude Upgrades — tools to make us faster

A working checklist of every tool/workflow upgrade I asked for, with the *why*
(tied to how we actually worked on Planner v2), concrete setup steps, what each
one unlocks for me, and who does the setup. Ranked by how much time it would have
saved this session.

> Legend — **Owner:** 🧑 you (harness/config) · 🤖 me (I can build it in-repo) · 👥 both.
> **Status:** ☐ todo · ◐ in progress · ☑ done.

---

## Priority 1 — the big unlocks

### 1. Playwright / browser automation  ☑  Owner: 🧑 (then 🤖 uses it)

**What it is.** A headless-browser tool exposed to me (via an MCP server) so I can
navigate the running app, click, type, read the DOM, and take screenshots.

**Why (from our workflow).** All session I had to hand the loop back to you:
*"you click through and confirm it works."* I literally could not see the UI I was
building. The buried ✨ curate toggle, the collections-numbering collision, and the
duplicate-channel mess all reached **you** before they reached **me** — a browser
tool flips that. It's also the only way to regenerate `docs/run.png` /
`docs/dashboard.png`, which are now stale.

**Setup (Claude Code MCP).** The Microsoft Playwright MCP server is the usual path:

```bash
# one-time: register the MCP server with Claude Code
claude mcp add playwright -- npx @playwright/mcp@latest
# (first run will download a browser; or: npx playwright install chromium)
```

Then restart Claude Code so it picks up the new MCP. Verify it loaded with
`/mcp` (or `claude mcp list`). *Package/flags evolve — confirm against the current
`@playwright/mcp` README if the command shifts.*

**What it unlocks for me.**
- **Screenshots for docs** — finally regenerate `run.png`, `dashboard.png`, etc.
- **True end-to-end verification** — drive Setup → Planner → Build → Deploy and
  *confirm* the result in Tunarr myself, instead of asking you to.
- **Catch UI bugs early** — discoverability problems, layout breaks, conflicting
  states, before you ever click.
- **Visual regression** — snapshot a screen, diff it after a change.

**How we'll know it's working.** I'll be able to call browser tools (navigate /
screenshot / click) directly in a turn. First test: I screenshot the Planner at
`localhost:7979` and replace `docs/run.png`.

---

### 2. Hot-reload dev loop (vite dev + uvicorn --reload)  ☑  Owner: 🤖

**What it is.** Run the frontend and backend in watch/reload mode instead of
rebuilding the Docker image for every change.

**Why (from our workflow).** I rebuilt the Docker image **~15+ times** this session.
Each `docker build` + run is ~1–2 minutes of dead air — for one-line JSX/CSS tweaks
like moving the AI switch or relabeling a button. This was our single biggest time
sink. A dev loop makes frontend edits **instant** (HMR) and backend edits **~1s**
(uvicorn reload).

**Setup (I can do all of this in-repo).**
- Add a Vite dev proxy so the SPA on `:5173` forwards `/api` to a locally-running
  backend:

  ```ts
  // frontend/vite.config.ts → server block
  server: {
    port: 5173,
    proxy: { '/api': 'http://localhost:7979' },
  }
  ```
- Two commands to start dev:

  ```bash
  # terminal A — backend with reload (from backend/)
  PROGRAMMARR_DATA=../data PROGRAMMARR_SCRIPTS=.. uvicorn main:app --reload --port 7979
  # terminal B — frontend with HMR (from frontend/)
  npm run dev          # opens http://localhost:5173
  ```
- Document it in `CLAUDE.md` under "Local Development" as the **fast** loop, with
  Docker kept as the **parity** loop before shipping.

**Caveats to keep honest.** Windows + `asyncio.create_subprocess_exec` needs the
Proactor loop (already handled in `main.py`); the pipeline scripts run with
`cwd=DATA_DIR`, so the env vars above matter. Auth still reads `config.json`. We
verify in real Docker before every ship regardless — the dev loop is for *iteration
speed*, not the final check.

**What it unlocks for me.** ~10x faster UI iteration; I stop burning minutes per
tweak and can try two or three variations in the time one Docker rebuild took.

---

## Priority 2 — repeatable verification

### 3. Backend smoke tests (pytest)  ☑  Owner: 🤖

**What it is.** A small `pytest` suite over the pure backend logic, with a fixture
that points `PROGRAMMARR_DATA` at a temp dir seeded with a synthetic
`plex_library.csv` / `channels.json`.

**Why (from our workflow).** Every time I touched `facets` / `compose` /
`validate?append` / `discover-prompt` I re-verified with throwaway inline Python
(and twice hit the `File(None)` sentinel / shell-escaping gotchas). A suite turns
that into a 2-second `pytest` run that's repeatable and catches regressions when we
change the resolver.

**What it would cover (high-value, deterministic units):**
- `library_facets` — genre/decade/blend/entity/marathon counts + thresholds.
- `compose_channels` — each `CandidateSpec` kind resolves correctly; soft-block
  numbering + spill; empty specs skipped.
- `validate(append=True)` — collision renumber **and** name-dedup (`skipped_dupes`).
- `discover_prompt` — seeds from `channels.json`, numbers from `max+1`, curate +
  discover sections.
- `generate_no_ai` flags — `--genres/--decades/--types` produce the expected blocks.

**Setup.** Add `backend/tests/`, a `conftest.py` fixture, `pytest` to
`requirements-dev.txt`. Run with `pytest backend`. (Optional later: wire into the
GitHub Actions CI so it runs on every PR.)

**What it unlocks for me.** Verification in seconds instead of bespoke scripts, and
a safety net so a refactor of the candidate resolver can't silently break compose.

---

## Priority 3 — habits & nice-to-haves (low/zero setup)

### 4. Use the project skills I already have  ☑  Owner: 🤖 (habit — adopted)

This repo already ships skills I under-used — I kept hand-rolling Python to hit
Tunarr's API instead:
- **`channel-status`** — live state across Tunarr / Plex / `channels.json` in one
  call (I rebuilt this by hand every time I inspected the lineup).
- **`deploy`** — probe → confirm → deploy → check sync.
- **`ship`**, **`build-ui`**, **`verify`**, **`release`** — already in our flow.

No setup; just me defaulting to them.

### 5. Fast type-check alias (`tsc --noEmit`)  ☑  Owner: 🤖 (habit)

> Added `"typecheck": "tsc --noEmit"` to `frontend/package.json` — run `npm run typecheck`.

I ran the full `npm run build` (tsc **+** vite bundle) just to type-check. For a
quick "does it compile," `tsc --noEmit` is faster; full build only when I need the
bundle. Minor, but it adds up across many edits.

### 6. Doc-asset screenshot pipeline (after Playwright lands)  ◐  Owner: 🤖

> **Synthetic demo dataset built** (`scripts/make_demo_data.py` → committed `demo/`): real
> public titles, tuned so every Planner section populates, deterministic for pixel-stable
> shots. Run the app with `PROGRAMMARR_DATA=./demo` to screenshot without exposing the real
> library. **Refreshed from demo data:** `docs/channels.png`, `docs/settings.png`,
> `docs/onboarding.png`. **Still stale** (deferred): `docs/run.png` (Planner — gated behind a
> live/mocked Plex export) and `docs/dashboard.png` (needs a live/mocked Tunarr). Finishing
> those needs mock Plex/Tunarr servers or a gated demo flag — see the options weighed on
> 2026-06-05; user chose to defer.

Once Playwright is in, a small script that navigates each page and dumps
`docs/*.png` so screenshots never silently go stale again (today: `run.png` shows
the retired three-tab UI, `dashboard.png` says "81 channels"). Effectively a
freebie once #1 exists.

---

## What I deliberately did **not** ask for

- **More MCP servers beyond Playwright.** `gh` covers GitHub; Tunarr/Plex/TMDB are
  plain HTTP I can call directly. Adding Plex/Tunarr MCPs would be noise.
- **A heavier test framework / E2E rig** beyond pytest + Playwright — overkill for
  where the project is.

---

## Suggested order

1. 🧑 **Playwright MCP** (you're on it) — unblocks screenshots + self-verification.
2. 🤖 **Hot-reload dev loop** — I set it up; biggest day-to-day speedup.
3. 🤖 **pytest smoke suite** — I write it; repeatable backend verification.
4. 🤖 **Regenerate `docs/run.png` + `dashboard.png`** — first job once #1 is live.
5. 🤖 habits — lean on existing skills, `tsc --noEmit`, screenshot pipeline.

When you give the word, #2 and #3 are self-contained and I can build them
immediately while you finish the Playwright wiring.
