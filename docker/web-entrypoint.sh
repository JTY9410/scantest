#!/bin/sh
set -eu

case "${AUTO_DB_UPGRADE:-}" in
  1|true|TRUE|True|yes|YES|Yes|on|ON|On)
    echo "AUTO_DB_UPGRADE is enabled; running flask db upgrade before startup."
    if ! flask db upgrade; then
      echo "ERROR: flask db upgrade failed. Container startup is aborted." >&2
      exit 1
    fi
    echo "Importing DTC workbooks into the knowledge base."
    if ! flask import-dtc-workbook || ! flask import-dtc-catalog || ! flask import-dtc-global; then
      echo "ERROR: DTC workbook import failed. Container startup is aborted." >&2
      exit 1
    fi
    ;;
esac

exec "$@"
