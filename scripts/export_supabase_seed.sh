#!/bin/sh
set -eu

: "${SUPABASE_DATABASE_URL:?SUPABASE_DATABASE_URL is required}"

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
OUTPUT_FILE="$ROOT_DIR/data/seed/supabase_baseline.dump"

mkdir -p "$ROOT_DIR/data/seed"

pg_dump "$SUPABASE_DATABASE_URL" \
  -Fc \
  --schema=public \
  --no-owner \
  --no-acl \
  -f "$OUTPUT_FILE"
echo "Wrote $OUTPUT_FILE"
