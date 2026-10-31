#!/bin/sh
# Supabase(public) → 서버 Compose Postgres 일회성 이전.
# 개인정보가 들어 있는 dump 는 레포에 커밋하지 말고 서버에만 두거나 별도 채널로 전달한다.
#
# 컷오버: 이 스크립트를 실행하기 직전부터 Supabase 쓰기를 중단한다.
#         중단 시각을 운영 기록에 남긴다. 이후 Supabase 쓰기가 있으면 데이터가 어긋난다.
#
# 필요 환경변수:
#   SUPABASE_DATABASE_URL  Session pooler 또는 Direct URI (비밀번호 포함, 별도 채널)
#   TARGET_DATABASE_URL    서버 내장 Postgres (예: postgresql://wecarscan:...@127.0.0.1:5432/wecarscan)
# 선택:
#   DUMP_FILE              기본 /tmp/scantest_supabase_public.dump (로컬/서버 임시 경로)
#
# 예:
#   export SUPABASE_DATABASE_URL='postgresql://...@aws-0-....pooler.supabase.com:5432/postgres'
#   export TARGET_DATABASE_URL='postgresql://wecarscan:...@127.0.0.1:5432/wecarscan'
#   ./scripts/migrate_from_supabase.sh
set -eu

: "${SUPABASE_DATABASE_URL:?SUPABASE_DATABASE_URL is required (Supabase Session pooler URI)}"
: "${TARGET_DATABASE_URL:?TARGET_DATABASE_URL is required (Compose Postgres)}"

DUMP_FILE=${DUMP_FILE:-/tmp/scantest_supabase_public.dump}

echo "Cutover: stop all writes to Supabase before continuing. Record the stop time in ops notes."
echo "Dumping public schema from Supabase → $DUMP_FILE"
pg_dump "$SUPABASE_DATABASE_URL" \
  -Fc \
  --schema=public \
  --no-owner \
  --no-acl \
  -f "$DUMP_FILE"

echo "Restoring into target (public schema). Existing objects may conflict — prefer empty volume or review first."
pg_restore \
  --verbose \
  --no-owner \
  --no-acl \
  --exit-on-error \
  -d "$TARGET_DATABASE_URL" \
  "$DUMP_FILE"

echo "Done. Run flask db upgrade on the target if alembic_version is behind head."
echo "Do not commit $DUMP_FILE to git (may contain PII)."
