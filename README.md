# Programmarr

A Python 3 CLI pipeline that turns your Plex library into themed virtual TV channels in [Tunarr](https://github.com/chrisbenincasa/tunarr). Channels loop forever with no dead air — no manual scheduling, no massive static playlists.

Two paths: feed your library to an LLM and let it curate smart channels, or use the no-AI generator to auto-create decade/genre channels from metadata.

## Requirements

- Python 3.8+ (standard library only — no pip installs)
- [Tunarr](https://github.com/chrisbenincasa/tunarr) running with Plex connected
- A Plex token (see [Finding your Plex token](#finding-your-plex-token))

## Setup

```
python programmarr.py
```

That's it. On first run, `programmarr.py` detects that `config.json` is missing and walks you through setting it up interactively:

```
No config.json found. Let's set one up.

Tunarr URL (e.g. http://192.168.1.10:8000):
Plex URL (e.g. http://192.168.1.10:32400):
Plex token:
TMDB API key (optional - for channel logos, press Enter to skip):

[ok] Config saved to config.json.
```

Your credentials are stored in `config.json` (gitignored — never leave your machine).

### Finding your Plex token

Open Plex Web, press F12 to open DevTools, go to the Network tab, click any library item, and look for requests to your Plex server URL — the token is in the query string as `X-Plex-Token=...`.

---

## Quick start

```
python programmarr.py
```

The main menu offers three workflow paths:

```
----------------------------------------------------
  Programmarr
----------------------------------------------------

  1) AI path         - export -> paste into LLM -> deploy
  2) No-AI path      - auto-generate from metadata -> deploy
  3) Collections     - sync Plex collections -> deploy

  u) Utilities
  q) Quit
```

Pick a path, follow the prompts. The wrapper always runs a dry-run probe and asks for confirmation before touching Tunarr.

---

## Workflow

```
export.py  →  LLM (Gemini / Claude / ChatGPT)  →  create.py
               or
export.py  →  generate_no_ai.py                →  create.py
```

### Step 1 — Export your library

```
python export.py
```

Queries Plex directly for full metadata and writes `plex_library.csv`:

| Column | Description |
|--------|-------------|
| Title | Exact title as it appears in Plex |
| Year | Release year |
| Type | Movie or TV |
| Rating | Content rating (PG, R, TV-MA, etc.) |
| Genres | Pipe-separated genre tags |
| Director | Director(s) — movies only |
| Seasons | Season count — TV only |
| Episodes | Episode count — TV only |
| InTunarr | Yes/No — whether Tunarr has this synced |

### Step 2A — AI path (recommended)

If you're using `programmarr.py` (recommended), the AI path copies `PROMPT.md` to `prompt_for_llm.md` — a ready-to-paste file for your LLM.

If running manually: open `PROMPT.md`, set `{TARGET}` to your desired channel count, then send it to any LLM (Claude Opus, Gemini Pro, GPT-4o) along with `plex_library.csv` — either as a file attachment or pasted inline.

Save the JSON output as `channels.json`.

**Tips:**
- Use the largest model available — speed-optimized models (Flash, Mini, Lite) tend to produce incomplete results on a task this size
- Aim for ~1 channel per 15–20 titles in your library as a starting point for `{TARGET}`

The AI will:
- Create themed channels using only titles that exist in your library
- Allow the same title on multiple channels (a movie can be on both "80s Movies" and "Action Movies")
- Suggest channels for content that didn't fit elsewhere
- Flag orphaned titles it couldn't place

### Step 2B — No-AI path

```
python generate_no_ai.py
```

Auto-generates `channels.json` with:
- Decade channels (80s, 90s, 2000s, etc.) from year metadata
- Genre channels (Action, Comedy, Horror, etc.) from genre tags
- TV marathon channels for shows with 50+ episodes
- Placeholder entries for franchise/themed channels — edit `content` lists manually

### Step 3 — Create channels in Tunarr

Always probe first:

```
python create.py --probe    # dry run — shows what would be created
python create.py            # delete existing channels, create all new ones
```

---

## Channel Numbering Scheme

| Block | Range | Content |
|-------|-------|---------|
| TV Marathons | 10–19 | 24/7 single-show loops (50+ episodes) |
| TV Blocks | 20–29 | Themed multi-show rotations |
| Movies | 30–49 | Genre and decade channels |
| Franchise | 50–69 | Ordered series (MCU, Batman, etc.) |
| Specialty | 70–79 | Single-movie loops, holiday, niche |

---

## channels.json Format

```json
{
  "channels": [
    {
      "number": 10,
      "name": "My Show 24/7",
      "shuffle": "ordered",
      "content": ["Exact Title From Plex"]
    }
  ],
  "orphaned": [],
  "suggested_channels": []
}
```

**`shuffle` values:**

| Value | Behavior | Best for |
|-------|----------|----------|
| `ordered` | Plays in order, loops | Franchises, sequential series |
| `shuffle` | Random rotation | Genre pools, decade channels |
| `block` | Round-robin between shows | TV blocks (TGIF, Saturday Morning, etc.) |

Content titles must match Plex library names exactly (case-insensitive). A title can appear on multiple channels — this is intentional.

---

## Syncing Channels to Plex

After running `create.py`, Plex may not know about new or changed channels. Run:

```
python sync_plex.py
```

This checks what channels Tunarr has vs what Plex has mapped, then attempts to add missing ones automatically. If the auto-sync isn't supported by your Plex version, it prints your XMLTV guide URL and step-by-step manual setup instructions — the URL is the key piece you need for the Plex DVR wizard.

The script never deletes your Plex DVR setup.

---

## All Flags

```
programmarr.py
  (no flags — fully interactive)

export.py
  --out FILE          Output CSV path (default: plex_library.csv)
  --no-crossref       Skip Tunarr sync check

generate_no_ai.py
  --csv FILE          Input CSV path (default: plex_library.csv)
  --out FILE          Output JSON path (default: channels.json)

create.py
  --json FILE         Input channels file (default: channels.json)
  --probe             Dry run — show what would be created, no changes
  --no-delete         Create channels without deleting existing ones
  --from N            Only operate on channels numbered N and above (preserves lower channels and their custom images)

sync_plex.py
  --probe             Show mapping state only, no changes
```

---

## How the Endless Loop Works

Tunarr's random schedule type generates a 30-day rolling programming window that rebuilds continuously. There are no static playlists — the channel always has content queued and never goes dark. The `maxDays: 30` window means Tunarr is always planning 30 days ahead, so channels loop smoothly forever.
