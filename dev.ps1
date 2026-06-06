# dev.ps1 — fast local dev loop (frontend HMR + backend auto-reload).
#
# This is the FAST iteration loop: frontend edits are instant (Vite HMR) and
# backend edits reload in ~1s (uvicorn --reload) — no Docker rebuild per tweak.
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

# Backend: uvicorn with --reload. PROGRAMMARR_DATA -> ./data (Docker layout),
# PROGRAMMARR_SCRIPTS -> repo root (where export.py / channel_engine.py live).
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "`$env:PROGRAMMARR_DATA='$root\data'; `$env:PROGRAMMARR_SCRIPTS='$root'; python -m uvicorn main:app --reload --port 7979 --app-dir '$root\backend'"
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
