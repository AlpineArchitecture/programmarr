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

- **Logos for multi-title channels.** `fetch_images.py` only handles solo-title
  channels (one show/movie). Genre/decade/themed blocks still show the generic
  Tunarr icon in the Plex guide. Need a logo strategy for multi-title channels
  (generated tile? representative title? custom upload?).

- **`tmdb_franchise` match type.** A principled alternative to `title_contains`
  for live franchise channels: match by TMDB collection ID instead of guessing
  from title text — authoritative, no false positives. (See the franchise-matcher
  notes in [`live-channels-design.md`](live-channels-design.md).)

---

## Bigger directional bets (parked on purpose)

These are captured so the intent isn't lost, but deliberately **not** being built
until there's a concrete reason. Full reasoning lives in the design doc.

- **Source/target agnosticism** — support a second library source (Jellyfin, local
  files) and/or a second channel target (ErsatzTV). The adapter seam would go in
  `channel_engine.py`. Do **not** build the abstraction until a real second
  implementation exists to validate it against. See
  [`live-channels-design.md`](live-channels-design.md) → "Source & Target Agnosticism."
