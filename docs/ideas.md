# Ideas / Backlog — NOT BUILT

> ⚠️ **Nothing on this page exists yet.** This is a free-dump scratchpad for
> things we *might* build. It is **not a roadmap** and **not a description of how
> the app works** — it changes constantly with user feedback. For what actually
> exists today, see [`../CLAUDE.md`](../CLAUDE.md) (developer reference) and
> [`../README.md`](../README.md) (user guide).
>
> When an idea graduates to "built," delete it from here and document the real
> behaviour in CLAUDE.md / README. If a cohesive roadmap ever forms, it can move
> into its own section.

---

## Jot ideas here

_(Add freely. One bullet per idea. Rough is fine — this is a notebook, not a spec.)_

- **Plex playlists as channels.** Extend the "Add Plex Collections" step to also
  cover Plex *playlists* — likely rename it "Collections & Playlists." Playlists
  are user-ordered, so they could map naturally to `ordered` channels.

- **`tmdb_franchise` match type.** A principled alternative to `title_contains`
  for live franchise channels: match by TMDB collection ID instead of guessing
  from title text — authoritative, no false positives. (See the franchise-matcher
  notes in [`live-channels-design.md`](live-channels-design.md).)

- **Surgical commercial pooling (era/type-matched).** Today the Planner's commercials
  toggle is a *blanket* — one filler list applied to every channel in the batch. The
  dream is era-matched ads: **90s commercials on the 90s sitcom marathon, 80s trailers
  on the 80s movie station, holiday spots on the holiday channel.** The data model is
  *already built for this* — `commercials` is a **per-channel** object
  (`{filler_list_id, pad_minutes}` in channels.json), and the Channels-page editor
  already lets you pick a different filler list per channel by hand. So this is an
  *enhancement*, not a rebuild. The future work is making it effortless:
  - auto-suggest a filler list per channel by matching decade/genre to filler-list name
    (e.g. a channel named "90s Comedy" → a list named "90s Commercials");
  - bulk-assign in the Planner ("pick a pool per decade") instead of one blanket list;
  - maybe allow **multiple** pools per channel (Tunarr's `fillerCollections` is already
    an array with weights — currently we only write a single-element list).
  Keep the blanket toggle as the easy default; layer precision on top.

---

## Bigger directional bets (parked on purpose)

These are captured so the intent isn't lost, but deliberately **not** being built
until there's a concrete reason. Full reasoning lives in the design doc.

- **Source/target agnosticism** — support a second library source (Jellyfin, local
  files) and/or a second channel target (ErsatzTV). The adapter seam would go in
  `channel_engine.py`. Do **not** build the abstraction until a real second
  implementation exists to validate it against. See
  [`live-channels-design.md`](live-channels-design.md) → "Source & Target Agnosticism."
