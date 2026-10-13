# WecarScan Flask 전환 구현 계획

**Goal:** `docs/superpowers/specs/2026-10-13-flask-rewrite-design.md`의 설계를 구현한다.

**Architecture:** Flask 앱 팩토리 + 기능별 Blueprint(route → service → model). 모바일 API는 `/api` Blueprint에서 Laravel과 같은 형식으로 응답하고, 관리자 웹은 `/admin` Blueprint에서 Jinja + Tailwind로 렌더링한다.

**Tech Stack:** Python 3.12, Flask 3.1, SQLAlchemy 2.0, Flask-Migrate 4, Flask-Login, Flask-WTF, Flask-Limiter, PyJWT, bcrypt, cryptography(Fernet), pyotp, segno, httpx, psycopg 3, gunicorn, Tailwind CSS v4, PostgreSQL 16.

## Global Constraints

- 모바일 API 응답 형식은 `docs/legacy/laravel-api.json`과 Laravel 동작 기준으로 유지한다.
- 비밀값은 환경변수로만 주입한다. 이미지·저장소·로그에 비밀값을 남기지 않는다.
- 목록 `per_page` 상한 100. 검색·정렬 필드는 화이트리스트.
- 색·간격 수치는 `app/static/css/tokens.css`에서만 정의한다.

## Tasks

| # | 작업 | 산출물 | 검증 |
|---|---|---|---|
| 1 | 골격 | `pyproject.toml`, `requirements.lock`, `app/__init__.py`, `config.py`, `extensions.py`, `compose.yaml`, `Dockerfile` | `GET /up` 200 |
| 2 | 모델·마이그레이션 | `app/modules/*/models.py`, `migrations/` | `flask db upgrade` 성공, 테이블 생성 확인 |
| 3 | 모바일 API | `app/modules/api/*` | `tests/api/` 통과 |
| 4 | 관리자 인증·MFA·CLI | `app/modules/auth/*`, `app/cli.py` | `tests/admin/test_auth.py` 통과 |
| 5 | 관리자 화면 | `members`, `catalog`, `monitoring`, `admin` 모듈 + 템플릿 | `tests/admin/` 통과 |
| 6 | AI 연결 | `app/modules/admin/ai_*` | `tests/admin/test_ai.py` 통과 |
| 7 | UI·PWA | `templates/`, `static/` | 브라우저 320/390px·데스크톱 확인 |
| 8 | 운영 배포·문서 | `compose.prod.yaml`, `README.md`, `docs/flows/`, `docs/adr/` | 운영 이미지 빌드, 비루트 실행 확인 |
| 9 | 최종 검증·배포 | 로컬 컨테이너 교체, Docker Hub 푸시 | 전체 pytest, `/up`, 관리자 로그인 |
