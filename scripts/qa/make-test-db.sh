#!/usr/bin/env bash
# Create (or recreate) an isolated `blnd_test` database inside the local Supabase Postgres.
# Why: pytest truncates/rolls back data; running it on the `postgres` DB wipes the demo data the
# warm simulators use. Tests point at blnd_test instead:
#   export TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/blnd_test
# Schema is cloned from the migrated `postgres` DB (so run `supabase start` / `supabase db reset --local` first).
set -euo pipefail
C="${SUPABASE_DB_CONTAINER:-supabase_db_blnd_backend}"
docker inspect "$C" >/dev/null 2>&1 || { echo "Local Supabase is not running ($C). Run: supabase start" >&2; exit 1; }
docker exec -e PGPASSWORD=postgres "$C" sh -c '
set -e
A="psql -h 127.0.0.1 -U supabase_admin"
pg_dump -h 127.0.0.1 -U supabase_admin -d postgres --schema-only --no-owner -n public -n auth -n extensions -n storage > /tmp/blnd_schema.sql
$A -d postgres -q -c "drop database if exists blnd_test with (force)" -c "create database blnd_test owner postgres"
$A -d blnd_test -q -c "create schema extensions" -c "create extension vector with schema public" \
  -c "create extension \"uuid-ossp\" with schema extensions" -c "create extension pgcrypto with schema extensions"
$A -d blnd_test -q -f /tmp/blnd_schema.sql 2>&1 | grep ERROR | grep -v "already exists" || true
echo "blnd_test ready: $($A -d blnd_test -tAc "select count(*) from information_schema.tables where table_schema=\$\$public\$\$") public tables"
'
