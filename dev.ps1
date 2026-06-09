# dev.ps1 — fast local dev loop (frontend HMR + backend auto-reload).
#
# This is the FAST iteration loop: frontend edits are instant (Vite HMR) and
# backend edits reload in ~1s (watchfiles restarts the process) — no Docker rebuild per tweak.
# NOTE: backend uses watchfiles, NOT `uvicorn --reload`, on purpose — see the backend block
# below for why (uvicorn --reload breaks pipeline subprocesses on Windows).
# Docker (`docker compose build && docker compose up`) stays the PARITY check you
# run before shipping. See CLAUDE.md → "Local Development".
#
# Opens two PowerShell windows:
#   Frontend (HMR):   http://localhost:5173   <-- open this one in your browser
#   Backend (reload): http://localhost:7979   (Vite proxies /api here)
#
# Data + scripts are pointed at the repo so the backend reads ./data/config.json,
# channels.json, plex_library.csv exactly like the Docker container does.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# Backend: watchfiles restarts the WHOLE uvicorn process on save (process-level reload),
# NOT uvicorn's built-in --reload. This is deliberate and required on Windows:
# uvicorn --reload runs the server in a worker subprocess and forces the Selector event
# loop, which CANNOT do asyncio.create_subprocess_exec — so export.py and every pipeline
# script die with NotImplementedError. Running plain `uvicorn` (no --reload) lets main.py's
# WindowsProactorEventLoopPolicy stand, and watchfiles gives us the ~1s reload-on-save by
# restarting the entire process. Best of both: fast reload AND working pipeline subprocesses.
# (No-op concern on Docker/Linux — that path uses the image's entrypoint, not this script.)
# PROGRAMMARR_DATA -> ./data (Docker layout), PROGRAMMARR_SCRIPTS -> repo root.
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "`$env:PROGRAMMARR_DATA='$root\data'; `$env:PROGRAMMARR_SCRIPTS='$root'; python -m watchfiles 'python -m uvicorn main:app --port 7979 --app-dir $root\backend' '$root\backend'"
)

# Frontend: Vite dev server with HMR on :5173 (proxies /api -> :7979).
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "Set-Location '$root\frontend'; npm run dev"
)

Write-Host ""
Write-Host "Dev loop starting in two new windows:" -ForegroundColor Cyan
Write-Host "  Frontend (HMR):   http://localhost:5173   <- open this in your browser"
Write-Host "  Backend (reload): http://localhost:7979"
Write-Host ""
Write-Host "Close those windows (or Ctrl+C in each) to stop. Rebuild in Docker before shipping."
