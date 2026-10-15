#!/bin/bash
set -euo pipefail
shopt -s nullglob
for f in /migrations/*.sql; do
  echo "Applying $(basename "$f")"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$f"
done
