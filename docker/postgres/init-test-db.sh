#!/bin/sh
# 개발 DB 컨테이너를 처음 만들 때 pytest 전용 DB를 함께 만든다.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE DATABASE ${POSTGRES_DB}_test OWNER "$POSTGRES_USER";
SQL
