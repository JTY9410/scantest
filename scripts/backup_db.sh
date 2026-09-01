#!/bin/bash

# 현재 날짜와 시간을 가져옵니다
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="_storage/backup"

# 백업 디렉토리가 없으면 생성
mkdir -p $BACKUP_DIR

# 환경 변수 로드
source .env

# 백업 파일명 설정
BACKUP_FILE="$BACKUP_DIR/backup_$TIMESTAMP.sql"

echo "데이터베이스 백업을 시작합니다..."

# Docker Compose 컨테이너 상태 확인
DB_CONTAINER=$(docker compose ps -q db)
if [ -z "$DB_CONTAINER" ]; then
    echo "오류: DB 컨테이너를 찾을 수 없습니다."
    exit 1
fi

# MySQL 컨테이너에서 백업 실행
docker compose exec -T db mysqldump \
    -u$DB_USERNAME \
    -p$DB_PASSWORD \
    $DB_DATABASE > $BACKUP_FILE

# 백업 파일 압축
gzip $BACKUP_FILE

echo "백업이 완료되었습니다: ${BACKUP_FILE}.gz"
