#!/usr/bin/env bash
# dev.sh — fast local dev loop for Linux/WSL
#
# Kills any old instance, then starts:
#   Vite HMR   -> http://localhost:5173  (open this — frontend with instant hot reload)
#   uvicorn    -> http://localhost:7979  (API, auto-reloads on Python changes)
#
# Ctrl+C stops both.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Kill anything holding our ports
fuser -k 7979/tcp 5173/tcp 2>/dev/null || true
sleep 0.5

cleanup() { kill "$(jobs -p)" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

export PROGRAMMARR_DATA="$ROOT/data"
export PROGRAMMARR_SCRIPTS="$ROOT"

echo ""
echo "  Frontend (HMR):  http://localhost:5173  <- open this"
echo "  Backend (API):   http://localhost:7979"
echo "  Ctrl+C to stop."
echo ""

"$ROOT/.venv/bin/python3" -m uvicorn main:app --reload --port 7979 --app-dir "$ROOT/backend" &
cd "$ROOT/frontend" && npm run dev &

wait
