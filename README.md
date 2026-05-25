# Programmarr

<div align="center">

**Turn your Plex library into themed virtual TV channels in [Tunarr](https://github.com/chrisbenincasa/tunarr)**

[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://hub.docker.com)
[![Built with Claude Code](https://img.shields.io/badge/Built%20with-Claude%20Code-D97757?logo=anthropic&logoColor=white)](https://claude.ai/claude-code)

</div>

---

Programmarr is a self-hosted web app that exports your Plex library, lets you feed it to an LLM, and deploys the results as themed virtual TV channels in Tunarr — with a web UI that feels like Sonarr or Radarr.

**Requires:** [Tunarr](https://github.com/chrisbenincasa/tunarr) + Plex

---

## Quick Start

### 1. Pull and start

```bash
docker compose up -d
```

That's it — the image is pre-built on [GHCR](https://github.com/AlpineArchitecture/programmarr/pkgs/container/programmarr) and pulls automatically. No local build step needed.

### 2. Open the UI

```
http://<your-server-ip>:7979
```

First run shows an onboarding wizard — create a login, enter your Tunarr and Plex URLs, done.

### Updates

The image is rebuilt and pushed automatically on every commit. To update:

```bash
docker compose pull && docker compose up -d
```

Or use the **Update** button in Portainer / TrueNAS Apps if you're using the `image:` reference below.

### TrueNAS (Custom App UI)

Paste this as a complete compose file in Apps → Custom App:

```yaml
services:
  programmarr:
    image: ghcr.io/alpinearchitecture/programmarr:latest
    container_name: programmarr
    restart: unless-stopped
    ports:
      - "7979:7979"
    volumes:
      - /mnt/YourPool/AppData/programmarr/data:/data
```

Replace `/mnt/YourPool/AppData/programmarr/data` with a real path on your TrueNAS pool. TrueNAS will show an **Update** button whenever a new image is pushed.

---

## What it does

| Path | How it works |
|------|-------------|
| **AI Path** | Export your library → copy prompt + CSV into any LLM → paste the result back → deploy |
| **No-AI Path** | Auto-generates decade, genre, and TV marathon channels from your metadata |
| **Collections** | Turns each Plex collection (Kometa, Trakt, Letterboxd) into its own channel |

All three paths end with a probe (dry run) → deploy to Tunarr. The app streams live output to the browser so you can watch it work.

### Also included

- **Channel logo fetching** — pulls TMDB clearlogos for single-show/movie channels
- **Plex DVR sync** — maps new channels into the Plex Live TV guide automatically
- **Channel editor** — edit names, numbers, shuffle mode, and content lists in the browser
- **Optional basic auth** — set a username/password if you expose the UI outside your LAN

---

## Configuration

Everything is set through the UI. Config is stored in `./data/config.json` (bind-mounted, never baked into the image).

| Field | Required | Notes |
|-------|----------|-------|
| Tunarr URL | Yes | e.g. `http://192.168.1.10:8000` |
| Plex URL | Yes | e.g. `http://192.168.1.10:32400` |
| Plex Token | Yes | [How to find yours](https://www.plexopedia.com/plex-media-server/general/plex-token/) |
| TMDB API Key | No | Free at [themoviedb.org](https://www.themoviedb.org/settings/api) — only needed for channel logos |

---

## CLI (advanced)

If you prefer the terminal, all the same functionality is available via `programmarr.py`:

```bash
python programmarr.py
```

The Python scripts have zero dependencies beyond the standard library and work standalone without Docker.

---

## Acknowledgments

Built with [Claude Code](https://claude.ai/claude-code). Made possible by [Tunarr](https://github.com/chrisbenincasa/tunarr), [Plex](https://www.plex.tv/), [TMDB](https://www.themoviedb.org/), and [Kometa](https://kometa.wiki/).

[⭐ Star on GitHub](https://github.com/AlpineArchitecture/programmarr) · [🐛 Report a Bug](https://github.com/AlpineArchitecture/programmarr/issues)
