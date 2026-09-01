.PHONY: test migrate seed tinker

# 테스트 실행
test:
	docker compose exec app php artisan test

# 마이그레이션 실행
migrate:
	docker compose exec app php artisan migrate

# 시드 실행
seed:
	docker compose exec app php artisan db:seed

# Tinker 실행
tinker:
	docker compose exec app php artisan tinker

# 캐시 클리어
clear:
	docker compose exec app php artisan cache:clear
	docker compose exec app php artisan config:clear
	docker compose exec app php artisan route:clear
	docker compose exec app php artisan view:clear

# 개발 서버 실행
serve:
	docker compose exec app php artisan serve

# 컴포저 의존성 설치
composer-install:
	docker compose exec app composer install

# npm 의존성 설치
npm-install:
	docker compose exec app npm install

# npm 빌드
npm-build:
	docker compose exec app npm run build
