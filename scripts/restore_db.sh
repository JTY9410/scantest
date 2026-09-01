#!/bin/bash

BACKUP_DIR="_storage/backup"

# 백업 디렉토리가 존재하는지 확인
if [ ! -d "$BACKUP_DIR" ]; then
    echo "오류: 백업 디렉토리를 찾을 수 없습니다: $BACKUP_DIR"
    exit 1
fi

# 가장 최근 백업 파일 찾기
LATEST_BACKUP=$(ls -t $BACKUP_DIR/backup_*.sql.gz 2>/dev/null | head -n 1)

if [ -z "$LATEST_BACKUP" ]; then
    echo "오류: 백업 파일을 찾을 수 없습니다."
    exit 1
fi

echo "가장 최근 백업 파일을 찾았습니다: $LATEST_BACKUP"
read -p "이 백업 파일로 복구를 진행하시겠습니까? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "복구가 취소되었습니다."
    exit 1
fi

# 환경 변수 로드
source .env

echo "데이터베이스 복구를 시작합니다..."

# 마이그레이션 초기화
echo "마이그레이션 초기화 중..."
docker compose exec -T app php artisan migrate:fresh

# 백업 파일이 gzip으로 압축되어 있는 경우
if [[ $LATEST_BACKUP == *.gz ]]; then
    # 압축 해제 후 복구
    gunzip -c $LATEST_BACKUP | docker compose exec -T db mysql \
        -u$DB_USERNAME \
        -p$DB_PASSWORD \
        $DB_DATABASE
else
    # 압축되지 않은 파일 복구
    docker compose exec -T db mysql \
        -u$DB_USERNAME \
        -p$DB_PASSWORD \
        $DB_DATABASE < $LATEST_BACKUP
fi

echo "데이터베이스 복구가 완료되었습니다."
