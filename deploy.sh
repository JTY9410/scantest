#!/bin/bash

# 에러 발생 시 스크립트 중단
set -e

# 환경 변수 로드
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# 타임아웃 설정 (5분)
TIMEOUT=300

# 로그 파일 설정
LOG_FILE="_storage/logs/deploy_$(date +'%Y%m%d_%H%M%S').log"

# 로그 함수
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# 현재 실행 중인 컨테이너 확인
get_current_container() {
    docker compose ps -q app
}

# 데이터베이스 백업
backup_database() {
    log "데이터베이스 백업 중..."
    backup_date=$(date +%Y%m%d_%H%M%S)
    backup_file="_storage/backup/database_${backup_date}.sql"

    # 백업 디렉토리 생성
    mkdir -p _storage/backup

    # mysqldump 실행
    docker compose exec db mysqldump -u"${DB_USERNAME}" -p"${DB_PASSWORD}" "${DB_DATABASE}" > "${backup_file}" || {
        log "데이터베이스 백업 실패"
        exit 1
    }

    log "데이터베이스 백업 완료: ${backup_file}"
}

# Git 업데이트
update_git() {
    log "Git 업데이트 중..."
    git pull origin master || {
        log "Git pull 실패"
        exit 1
    }
}

# 새 컨테이너 빌드 및 시작
build_and_start_new_container() {
    log "새 컨테이너 빌드 중..."
    docker compose build app

    log "새 컨테이너 시작 중..."
    docker compose up -d --no-deps app

    # 새 컨테이너가 정상적으로 시작될 때까지 대기
    log "새 컨테이너 상태 확인 중..."
    max_attempts=30
    attempt=1
    while [ $attempt -le $max_attempts ]; do
        if docker compose exec app php artisan db:monitor; then
            break
        fi
        log "새 컨테이너 준비 중... (시도 $attempt/$max_attempts)"
        sleep 2
        attempt=$((attempt + 1))
    done

    if [ $attempt -gt $max_attempts ]; then
        log "새 컨테이너 시작 실패"
        exit 1
    fi
}

# Composer 업데이트
update_composer() {
    log "Composer 의존성 업데이트 중..."
    docker compose exec app composer install --optimize-autoloader || {
        log "Composer 업데이트 실패"
        exit 1
    }
}

# 마이그레이션 실행
run_migrations() {
    log "마이그레이션 실행 중..."
    docker compose exec app php artisan migrate --force
}

# 캐시 정리
clear_cache() {
    log "캐시 정리 중..."
    docker compose exec app php artisan cache:clear
    docker compose exec app php artisan config:clear
    docker compose exec app php artisan route:clear
    docker compose exec app php artisan view:clear
}

# 이전 컨테이너 정리
cleanup_old_container() {
    log "이전 컨테이너 정리 중..."
    docker compose stop app
    docker compose rm -f app
}

# 롤백 기능
rollback() {
    log "롤백 시작..."
    if [ -n "$current_container" ]; then
        docker compose up -d --no-deps app
    fi
    log "롤백 완료"
}

# 환경 변수 검증
validate_environment() {
    log "환경 변수 검증 중..."
    if ! docker compose exec app php artisan db:monitor; then
        log "데이터베이스 연결 실패"
        exit 1
    fi
    log "환경 변수 검증 완료"
}

# 메인 배포 프로세스
main() {
    log "배포 시작..."

    # 현재 실행 중인 컨테이너 확인
    current_container=$(get_current_container)
    if [ -n "$current_container" ]; then
        log "현재 실행 중인 컨테이너: $current_container"
    fi

    # 환경 변수 검증
    validate_environment

    # 데이터베이스 백업
    backup_database

    # Git 업데이트
    update_git

    # 새 컨테이너 빌드 및 시작
    build_and_start_new_container

    # Composer 업데이트
    update_composer

    # 마이그레이션 실행
    run_migrations

    # 캐시 정리
    clear_cache

    # 이전 컨테이너 정리
    if [ -n "$current_container" ]; then
        cleanup_old_container
    fi

    # 컨테이너 재시작
    log "컨테이너 재시작 중..."
    docker compose up -d app
    log "컨테이너 재시작 완료"

    log "배포 완료!"
}

# 스크립트 실행
main
