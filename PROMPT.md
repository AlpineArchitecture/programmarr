# ChannelMaker — LLM Prompt

Copy everything below the line and paste it into your LLM (Gemini, Claude, ChatGPT, etc.)
followed by the full contents of `plex_library.csv`.

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
- **20–29**: TV Blocks — themed multi-show rotations (TGIF, Saturday Morning Cartoons, etc.)
- **30–49**: Movie Channels — genre and decade-based pools
- **50–69**: Franchise & Curated Series — ordered collections (MCU in release order, etc.)
- **70–79**: Specialty — single-movie loops, holiday, niche themes

Keep numbers sequential within each block. Leave gaps for future additions.

## Shuffle Types

Each channel must have one of these shuffle types:
- `ordered` — plays content in strict order (use for franchises, chronological series)
- `shuffle` — random rotation (use for genre pools, decade channels)
- `block` — round-robin between shows/movies (2 episodes per show per turn; use for multi-show TV blocks)

## Output Format

Output ONLY valid JSON in exactly this schema. No markdown fences, no commentary outside the JSON.

```json
{
  "channels": [
    {
      "number": 10,
      "name": "Channel Name",
      "shuffle": "ordered",
      "content": [
        "Exact Title From CSV",
        "Another Exact Title"
      ]
    }
  ],
  "orphaned": [
    {
      "title": "Some Title",
      "reason": "One-sentence explanation of why it did not fit any channel"
    }
  ],
  "suggested_channels": [
    {
      "name": "Suggested Channel Name",
      "reason": "Why this channel makes sense",
      "content": ["Title A", "Title B"]
    }
  ]
}
```

## My Channel Ideas (use as a starting point, modify freely)

Here are channels I want. Fill them with matching titles from the CSV, reorder them, split or merge them as needed:

- **TV Marathons (10s)**: King of the Hill 24/7, New Girl 24/7, Fresh Prince of Bel-Air 24/7, Superstore 24/7, Roseanne 24/7, Justified 24/7
- **TV Blocks (20s)**: TGIF (90s family/sitcom block), Saturday Morning Cartoons (animated series block), Batman Animated TV block
- **Movie Channels (30s)**: Comedy Movies, Action Movies, 80s Movies, 80s Action, 80s Comedy, 90s Movies, 90s Action, 90s Comedy, 2000s Movies, 2000s Action, 2000s Comedy, 2010s Movies, 2010s Action, 2010s Comedy, 2020s Movies, 2020s Action, 2020s Comedy
- **Franchise (50s)**: Marvel MCU (in release order), Batman Live Action Movies (in order), Batman Animated Movies (in order), The Matrix Quad (in order), Kevin Smith View Askewniverse (in order), Bad Boys Movies (in order), Deadpool Movies (in order), Adam Sandler Movies
- **Specialty (70s)**: Hackers 24/7 (single movie loop — the 1995 film), Holiday Cheer (Christmas movies)

## The Library

(Paste the full contents of plex_library.csv here)
