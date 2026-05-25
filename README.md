```ansi
[1m[36m______
[1m[36m| ___ \
[1m[36m| |_/ / __ ___   __ _ _ __ __ _ _ __ ___   __ _ _ __ _ __
[1m[36m|  __/ '__/ _ \ / `_` | '__/ `_` | '_ ` _ \ / `_` | '__| '__|
[1m[36m| |  | | | (_) | (_| | | | (_| | | | | | | (_| | |  | |
[1m[36m\_|  |_|  \___/ \__, |_|  \__,_|_| |_| |_|\__,_|_|  |_|
[1m[36m                 __/ |
[1m[36m                |___/[0m
```

<div align="center">

**Turn your Plex library into themed virtual TV channels in [Tunarr](https://github.com/chrisbenincasa/tunarr)**

[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Tunarr](https://img.shields.io/badge/Requires-Tunarr-blueviolet)](https://github.com/chrisbenincasa/tunarr)
[![Built with Claude Code](https://img.shields.io/badge/Built%20with-Claude%20Code-D97757?logo=anthropic&logoColor=white)](https://claude.ai/claude-code)

**[Quick Start](#-quick-start)** •
**[Workflow](#-workflow)** •
**[Channel Numbering](#-channel-numbering-scheme)** •
**[All Flags](#-all-flags)**

</div>

---

## 📺 What is Programmarr?

Programmarr is a Python 3 CLI pipeline that turns your self-hosted Plex library into a set of themed virtual TV channels in [Tunarr](https://github.com/chrisbenincasa/tunarr). Channels loop forever with no dead air — no manual scheduling, no massive static playlists.

**Perfect for:**
- 📡 Tunarr users who want curated, themed channels instead of a flat library
- 🤖 Anyone who wants AI to do the programming work for them
- 🗂️ Kometa/Trakt users who want to turn their collections into live channels
- 🕹️ Hobbyists who want their Plex to feel like real cable TV

> [!NOTE]
> **Vibe-coded with Claude Code** — this project was built entirely through AI-assisted development using [Claude Code](https://claude.ai/claude-code). See [Acknowledgments](#-acknowledgments).

---

## ✨ Features

<table>
<tr>
<td width="33%" valign="top">

### 🤖 AI Path
**LLM-curated channels**
- Export your Plex library to CSV
- Paste into any LLM (Claude, GPT-4o, Gemini)
- LLM designs themed channels from your actual content
- Save output, deploy to Tunarr

</td>
<td width="33%" valign="top">

### ⚙️ No-AI Path
**Auto-generated from metadata**
- Decade channels (80s, 90s, 2000s…)
- Genre channels (Action, Comedy, Horror…)
- TV marathon channels (50+ episode shows)
- Franchise placeholders to fill manually

</td>
<td width="33%" valign="top">

### 🗂️ Collections Path
**Plex collections → channels**
- One channel per Kometa/Trakt/Letterboxd collection
- Re-run any time collections change
- Smart deduplication and base-channel scoping
- Mix with plain titles in the same channel

</td>
</tr>
</table>

### 🔧 More Highlights
- 🔍 **Probe mode** — always dry-runs before touching Tunarr
- 🖼️ **Channel logos** — fetches TMDB clearlogos for solo-show channels
- 🔄 **Plex sync** — auto-maps new channels into the Plex Live TV guide
- 📦 **Zero dependencies** — Python standard library only, no pip installs

---

## 🚀 Quick Start

```
python programmarr.py
```

That's it. On first run, Programmarr detects that `config.json` is missing and walks you through setup interactively:

```
No config.json found. Let's set one up.

Tunarr URL (e.g. http://192.168.1.10:8000):
Plex URL (e.g. http://192.168.1.10:32400):
Plex token:
TMDB API key (optional - for channel logos, press Enter to skip):

[ok] Config saved to config.json.
```

Your credentials are stored in `config.json` (gitignored — never leaves your machine).

### 🔑 Finding your Plex token

Open Plex Web, press F12 to open DevTools, go to the Network tab, click any library item, and look for requests to your Plex server URL — the token is in the query string as `X-Plex-Token=...`.

---

## 🔄 Workflow

```
export.py  →  LLM (Claude / GPT-4o / Gemini)  →  create.py
               or
export.py  →  generate_no_ai.py                →  create.py
               or
generate_from_collections.py --apply           →  create.py
```

The interactive wrapper (`programmarr.py`) handles all three paths and always runs a dry-run probe before deploying.

### 📤 Step 1 — Export your library

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

### 🤖 Step 2A — AI path (recommended)

Open `PROMPT.md`, set `{TARGET}` to your desired channel count, then send it to any LLM along with `plex_library.csv` — either as a file attachment or pasted inline. Save the JSON output as `channels.json`.

**Tips:**
- Use the largest model available — speed-optimized models (Flash, Mini, Lite) tend to produce incomplete results on a task this size
- Aim for ~1 channel per 15–20 titles in your library as a starting point for `{TARGET}`

### ⚙️ Step 2B — No-AI path

```
python generate_no_ai.py
```

Auto-generates `channels.json` with decade channels, genre channels, TV marathon channels, and franchise placeholders to fill in manually.

### 🗂️ Step 2C — Collections path

```
python generate_from_collections.py              # preview
python generate_from_collections.py --apply      # write to channels.json
```

Generates one channel per Plex collection (Kometa, Trakt, Letterboxd, etc.). Re-run any time your collections change to keep the block in sync.

### 📡 Step 3 — Deploy to Tunarr

Always probe first:

```
python create.py --probe    # dry run — shows what would be created
python create.py            # delete existing channels, create all new ones
```

---

## 📋 channels.json Format

```json
{
  "channels": [
    {
      "number": 10,
      "name": "Breaking Bad 24/7",
      "shuffle": "ordered",
      "content": ["Breaking Bad"]
    },
    {
      "number": 20,
      "name": "Crime TV",
      "shuffle": "shuffle",
      "content": ["Breaking Bad", "The Wire", "Ozark", "True Detective"]
    },
    {
      "number": 80,
      "name": "Criterion Collection",
      "shuffle": "shuffle",
      "content": [{"collection": "Criterion Collection"}]
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

Content titles must match Plex library names exactly (case-insensitive). A title can appear on multiple channels — this is intentional. See `channels.json.example` for a full working example.

---

## 📺 Channel Numbering Scheme

| Block | Range | Content |
|-------|-------|---------|
| 📺 TV Marathons | 10–19 | 24/7 single-show loops (50+ episodes) |
| 📺 TV Blocks | 20–29 | Themed multi-show rotations |
| 🎬 Movies | 30–49 | Genre and decade channels |
| 🎬 Franchise | 50–69 | Ordered series (Star Wars, James Bond, etc.) |
| ⭐ Specialty | 70–79 | Single-movie loops, holiday, niche |
| 🗂️ Collections | 80+ | Auto-generated from Plex collections |

---

## 🔁 Syncing to Plex

After deploying, Plex may not know about new channels. Run:

```
python sync_plex.py
```

This compares Tunarr's channel list against Plex's DVR mappings and attempts to add missing ones automatically. If auto-sync isn't supported by your Plex version, it prints your XMLTV URL and manual setup steps. The script never deletes your Plex DVR setup.

---

## 🖼️ Channel Logos

```
python fetch_images.py --probe     # preview what would be updated
python fetch_images.py --apply     # fetch and apply TMDB clearlogos
```

For solo-title channels (a single show or movie), Programmarr can fetch the real logo from TMDB and set it as the channel icon in Tunarr, so your Plex Live TV guide shows proper show/movie branding instead of the generic Tunarr icon.

Requires a free [TMDB API key](https://www.themoviedb.org/settings/api).

---

## 🏳️ All Flags

```
programmarr.py
  (no flags — fully interactive)

export.py
  --out FILE          Output CSV path (default: plex_library.csv)
  --no-crossref       Skip Tunarr sync check

generate_no_ai.py
  --csv FILE          Input CSV path (default: plex_library.csv)
  --out FILE          Output JSON path (default: channels.json)

generate_from_collections.py
  --apply             Write to channels.json (default: preview only)
  --base N            Start collection block at channel N (default: 80)
  --condense          Skip collections whose name matches an existing channel
  --min-items N       Skip collections with fewer than N items

create.py
  --json FILE         Input channels file (default: channels.json)
  --probe             Dry run — show what would be created, no changes
  --no-delete         Create channels without deleting existing ones
  --from N            Only touch channels numbered N and above

fetch_images.py
  --apply             Commit logo changes (default: dry run)
  --channel N         Only process channel number N
  --clear             Remove all custom icons

sync_plex.py
  --probe             Show mapping state only, no changes
```

---

## ⚙️ Configuration

All config lives in `config.json` (gitignored — never commit this):

```json
{
  "tunarr_url": "http://your-tunarr:8000",
  "plex_url":   "http://your-plex:32400",
  "plex_token": "your-token",
  "tmdb_api_key": "your-tmdb-key"
}
```

`tmdb_api_key` is optional — only required for `fetch_images.py`. See `config.json.example` for the template.

---

## 🙏 Acknowledgments

**The problem:** Building a great themed TV channel lineup from a large Plex library is tedious. Tunarr does the hard work of channel management and scheduling — but deciding *what goes on each channel* is a creative, time-consuming task.

**The solution:** Let an LLM read your library and design the lineup. Programmarr handles the plumbing — export, deploy, sync — so you paste once and have live TV.

**The build:** This project was built entirely through [Claude Code](https://claude.ai/claude-code) using AI-assisted development. Every script, flag, and feature came out of a conversation, not a text editor.

Special thanks to:
- [Tunarr](https://github.com/chrisbenincasa/tunarr) — the IPTV channel manager that makes all of this possible
- [Plex](https://www.plex.tv/) — media server
- [TMDB](https://www.themoviedb.org/) — movie/TV metadata and logos
- [Kometa](https://kometa.wiki/) — Plex collection management

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

**Built with [Claude Code](https://claude.ai/claude-code) 🤖 for the Tunarr & Plex community 📺**

[⭐ Star on GitHub](https://github.com/jamesmattson-blip/programmarr) • [🐛 Report a Bug](https://github.com/jamesmattson-blip/programmarr/issues) • [💡 Request a Feature](https://github.com/jamesmattson-blip/programmarr/issues)

</div>
