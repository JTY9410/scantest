#!/bin/sh
set -eu

# Always run migrations on startup (fail loudly if it fails)
echo "Running flask db upgrade before startup..."
if ! flask db upgrade; then
  echo "ERROR: flask db upgrade failed. Container startup is aborted." >&2
  exit 1
fi

# Import DTC data and seed reference data (only if AUTO_DB_UPGRADE is explicitly enabled)
case "${AUTO_DB_UPGRADE:-}" in
  1|true|TRUE|True|yes|YES|Yes|on|ON|On)
    echo "AUTO_DB_UPGRADE is enabled; importing DTC workbooks and seeding data."
    echo "Importing DTC workbooks into the knowledge base."
    if ! flask import-dtc-workbook || ! flask import-dtc-catalog || ! flask import-dtc-global; then
      echo "ERROR: DTC workbook import failed. Container startup is aborted." >&2
      exit 1
    fi
    echo "Seeding Tesla reference data."
    if ! flask seed-tesla-reference; then
      echo "ERROR: Tesla reference data seed failed. Container startup is aborted." >&2
      exit 1
    fi
    ;;
esac

exec "$@"
