#!/bin/sh
set -eu

case "${AUTO_DB_UPGRADE:-}" in
  1|true|TRUE|True|yes|YES|Yes|on|ON|On)
    echo "AUTO_DB_UPGRADE is enabled; running flask db upgrade before startup."
    if ! flask db upgrade; then
      echo "ERROR: flask db upgrade failed. Container startup is aborted." >&2
      exit 1
    fi
    ;;
esac

exec "$@"
