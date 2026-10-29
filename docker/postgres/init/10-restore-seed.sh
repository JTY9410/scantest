#!/bin/sh
set -eu

SEED_FILE=/seed/supabase_baseline.dump

if [ -s "$SEED_FILE" ]; then
  echo "Restoring PostgreSQL seed from $SEED_FILE"
  pg_restore \
    --verbose \
    --exit-on-error \
    --no-owner \
    --role="$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    "$SEED_FILE"
else
  echo "WARNING: PostgreSQL seed $SEED_FILE is missing or empty; starting with an empty development database." >&2
fi
