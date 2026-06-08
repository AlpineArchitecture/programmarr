# Programmarr — LLM Prompt

Copy everything below the line and paste it into your LLM (Gemini, Claude, ChatGPT, etc.).

**Model recommendation:** Use the largest, most capable model available — Claude Opus,
Gemini Pro/Ultra, GPT-4o, etc. Speed-optimized models (Flash, Mini, Lite variants)
tend to hit output limits or produce incomplete results on a task this large. This is
one of those cases where the bigger model is worth it.

**Set {TARGET} before you paste.** Replace `{TARGET}` in the Rules section below with
your desired channel count (e.g. `40`). Too low and the LLM underfills the number
blocks; too high and it pads with thin channels. A good rule of thumb: ~1 channel per
15–20 titles in your library.

**Option A — File attachment (recommended if your LLM supports it):**
Paste the prompt, then attach `plex_library.csv` as a file. The LLM reads the
CSV as structured data rather than raw text, which produces more accurate results
and uses the context window more efficiently.

**Option B — Single paste (works everywhere):**
Paste the prompt, then paste the full contents of `plex_library.csv` directly
after it. Works with any LLM or interface that doesn't support file uploads.

> **Note on the Channel Numbering Scheme below:** the ranges shown are the defaults. When you
> copy the prompt from the web app, it regenerates that section to match your configured block
> sizes (Settings → Channel Numbering) and start number. The static text here is what the CLI uses.

---

You are a TV channel programmer. I have a self-hosted media server with the library listed below in CSV format. Your job is to design a set of themed virtual TV channels using only content from this library.

## Rules

1. **Only use titles that appear in the provided CSV.** Do not invent or suggest titles that are not in the list.
2. **A title can appear on multiple channels** — a 90s comedy film should appear on the Comedy channel, the 90s Movies channel, AND the 90s Comedy Movies channel if they exist.
3. **Not every title needs a channel.** Only include a title on a channel if it genuinely fits.
4. **Target approximately {TARGET} channels total.** Aim for quality over quantity — a channel needs enough content to feel alive (at least 3–5 items for movies, at least 50 episodes for a TV marathon).
5. **Suggest new channels** if you see clusters of content that would make a great themed station (e.g., if the library has 8 Pixar films, suggest a Pixar channel).
6. **Flag orphaned content** — at the end, list any notable titles that didn't fit any channel. If 5 or more orphaned titles share a theme, suggest a new channel for them.

## Channel Numbering Scheme

Assign channel numbers following this cable TV block structure:
- **10–19**: TV Marathons — 24/7 single-show loops (needs 50+ episodes to qualify)
- **20–29**: TV Blocks — themed multi-show rotations (era blocks, genre blocks, etc.)
- **30–49**: Movie Channels — genre and decade-based pools
- **50–69**: Franchise & Curated Series — ordered collections (film series in release order, etc.)
- **70–79**: Specialty — single-movie loops, holiday, niche themes

Keep numbers sequential within each block. Leave gaps for future additions.

## Shuffle Types

Each channel must have one of these shuffle types:
- `ordered` — plays content in strict order (use for franchises, chronological series)
- `shuffle` — random rotation (use for genre pools, decade channels)
- `block` — round-robin between shows/movies (2 episodes per show per turn; use for multi-show TV blocks)

## Output Format

Output one channel per line as a JSON object (JSONL). No wrapper object, no markdown fences, no commentary between lines — just one `{...}` per line.

```
{"number": 10, "name": "Breaking Bad Marathon", "shuffle": "ordered", "content": ["Breaking Bad"]}
{"number": 20, "name": "Crime TV Block", "shuffle": "block", "content": ["The Wire", "Ozark", "Justified"]}
{"number": 30, "name": "80s Action Movies", "shuffle": "shuffle", "content": ["Die Hard", "Lethal Weapon", "Predator"]}
```

Each line must have exactly these fields:
- `number` — integer channel number following the scheme above
- `name` — string channel name
- `shuffle` — one of `ordered`, `shuffle`, or `block`
- `content` — array of title strings copied exactly from the CSV

After the channel list, you may add a brief plain-text note listing any notable orphaned titles and why they didn't fit.

## The Library

(Option A: attach plex_library.csv as a file and delete this section)
(Option B: paste the full contents of plex_library.csv here)
