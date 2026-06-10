#!/usr/bin/env bash
# dev.sh — fast local dev loop for Linux/WSL
#
# Runs Vite HMR (:5173) + uvicorn --reload (:7979) in one terminal.
# On Linux, uvicorn --reload works directly — no watchfiles wrapper needed
# (the Windows workaround in dev.ps1 is not required here).
#
# Open http://localhost:5173 in your browser (Vite proxies /api -> :7979).
# Ctrl+C stops both processes.

set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cleanup() { kill $(jobs -p) 2>/dev/null; }
trap cleanup EXIT INT TERM

export PROGRAMMARR_DATA="$ROOT/data"
export PROGRAMMARR_SCRIPTS="$ROOT"

echo ""
echo "Dev loop starting..."
echo "  Frontend (HMR):   http://localhost:5173   <- open this in your browser"
echo "  Backend (reload): http://localhost:7979"
echo "  Ctrl+C to stop both."
echo ""

"$ROOT/.venv/bin/python3" -m uvicorn main:app --reload --port 7979 --app-dir "$ROOT/backend" &
cd "$ROOT/frontend" && npm run dev &

wait
