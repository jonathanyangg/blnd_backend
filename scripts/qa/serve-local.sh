#!/usr/bin/env bash
# Run the backend for simulators/Maestro against local Supabase (never prod).
#   scripts/qa/serve-local.sh [port]            # foreground
# Secrets: the app's own .env is used by the app process; this script never prints or reads it.
# Set BLND_ENV_FILE to a .env (default: ./.env). It is symlinked, not copied or echoed.
set -euo pipefail
cd "$(dirname "$0")/../.."
PORT="${1:-${PORT:-8100}}"
ENV_FILE="${BLND_ENV_FILE:-$HOME/cursor-work/blnd_backend-preview/.env}"
[ -e .env ] || { [ -e "$ENV_FILE" ] && ln -s "$ENV_FILE" .env; }
export DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:54322/postgres"   # local only
export SUPABASE_URL="http://127.0.0.1:54321"
export BLND_DISABLE_RATE_LIMITS=true
exec uv run uvicorn main:app --host 127.0.0.1 --port "$PORT"
