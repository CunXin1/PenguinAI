#!/usr/bin/env bash
# scripts/dev.sh — start backend + frontend with auto-restart on crash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

cleanup() {
    echo "[dev] shutting down..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    echo "[dev] done."
}
trap cleanup EXIT INT TERM

# ── Backend (single start, uvicorn --reload handles restarts) ─────────────────
(cd backend && exec uvicorn app.main:app --reload --port 8000) &
BACKEND_PID=$!
echo "[dev] backend started (pid=$BACKEND_PID)"

# ── Frontend (auto-restart on crash) ──────────────────────────────────────────
start_frontend() {
    while true; do
        echo "[dev] starting frontend..."
        (cd frontend && NODE_OPTIONS="--max-old-space-size=1024" exec npm run dev) &
        FRONTEND_PID=$!
        wait $FRONTEND_PID || true
        RC=$?
        if [ $RC -eq 0 ]; then
            break  # clean exit
        fi
        echo "[dev] frontend crashed (rc=$RC), restarting in 3s..."
        sleep 3
        # Clear stale Turbopack state on crash
        rm -rf frontend/.next/cache 2>/dev/null || true
    done
}

start_frontend &
FRONTEND_PID=$!

echo "[dev] all services running — press Ctrl+C to stop"
wait
