#!/usr/bin/env bash
# One-command backend tests on an isolated database (does not touch the demo data the warm sims use).
#   scripts/qa/test.sh            unit + contract
#   scripts/qa/test.sh unit|contract
# Recreates `blnd_test` every run (a `supabase db reset` anywhere would otherwise delete it).
set -euo pipefail
cd "$(dirname "$0")/../.."
scripts/qa/make-test-db.sh
export TEST_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:54322/blnd_test"
export OPENAI_API_KEY="${OPENAI_API_KEY:-test-key}"
rm -f .env.bak
[ -e .env ] && { echo "refusing to run tests with a .env present (it can leak real keys into tests): move it away"; exit 2; }
mkdir -p "${QA_REPORT_DIR:-$HOME/cursor-work/qa/reports}"
R="${QA_REPORT_DIR:-$HOME/cursor-work/qa/reports}"
case "${1:-all}" in
  unit)     uv run --locked pytest -q -m "not contract" --junitxml="$R/backend-unit.xml";;
  contract) uv run --locked pytest -q -m contract --junitxml="$R/backend-contract.xml";;
  *)        uv run --locked pytest -q -m "not contract" --junitxml="$R/backend-unit.xml"
            uv run --locked pytest -q -m contract --junitxml="$R/backend-contract.xml";;
esac
