# Compose PostgreSQL · Supabase 시드 최초 복원 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Supabase/Vercel 의존을 끊고 Mac Docker Compose PostgreSQL만 쓰며, 저장소 시드를 빈 볼륨 최초 기동 시 자동 복원하고 web은 `flask db upgrade`로 스키마를 맞춘다.

**Architecture:** Postgres 공식 init(`docker-entrypoint-initdb.d`)에서 `pg_restore`로 시드를 넣고, web 엔트리스크립트가 기동 전 `flask db upgrade`를 실행한다. 앱 설정은 `DATABASE_URL`만 사용한다.

**Tech Stack:** Flask, SQLAlchemy 2, Alembic, PostgreSQL 16 Alpine, Docker Compose, `pg_dump`/`pg_restore`

**Spec:** `docs/superpowers/specs/2026-10-29-compose-postgres-seed-design.md`

## Global Constraints

- DB는 Compose PostgreSQL만; SQLite 운영 전환 없음
- 시드는 빈 `pgdata`에서만 복원; 기존 볼륨 덮어쓰기 금지
- 시드 파일은 저장소에 포함(개인정보 가능·비공개 리포 전제)
- 업로드 범위: GitHub + Docker/GHCR; Vercel·Supabase 연동 변경 없음
- `pro.md` 자동 upgrade 금지는 이 Mac 최초 배포 예외로 ADR 기록

## Review Focus

- 시드 파일 없음 → init이 실패하지 않고 경고 후 빈 DB로 기동
- 시드 복원 실패 → DB 컨테이너가 실패해 web이 healthy db를 기다림
- `POSTGRES_URL`만 있어도 더 이상 DB로 쓰지 않음
- 기존 볼륨 재기동 시 시드가 다시 적용되지 않음
- HTTPS 안내가 Vercel URL에 고정되지 않음(`PUBLIC_BASE_URL` 또는 origin)

---

### Task 1: DATABASE_URL만 쓰도록 설정 정리

**Recommended Skill:** `superpowers:test-driven-development`

**Files:**
- Modify: `app/config.py` (`database_url`)
- Modify: `tests/test_config.py`
- Modify: `.env.example` (`PUBLIC_BASE_URL`, `AUTO_DB_UPGRADE` 주석)

**Interfaces:**
- Produces: `database_url() -> str | None` — `DATABASE_URL`만 읽고, `postgres://`이면 `postgresql+psycopg`로 스킴 변환(쿼리에서 `supa` 제거는 유지해도 됨). `POSTGRES_URL` 폴백 없음.

- [ ] **Step 1: 테스트 수정(RED)** — `test_database_url_converts_vercel_supabase_url`를 `DATABASE_URL`의 `postgres://`+`supa` 변환 케이스로 바꾸고, `POSTGRES_URL`만 있으면 `None`인 테스트 추가

- [ ] **Step 2: 실행** `pytest tests/test_config.py -q` → 실패 확인

- [ ] **Step 3: `database_url()` 구현** — `POSTGRES_URL` 폴백 제거

- [ ] **Step 4: 테스트 통과** `pytest tests/test_config.py -q`

- [ ] **Step 5: Commit** `config: DATABASE_URL만 사용하고 POSTGRES_URL 폴백을 제거한다`

---

### Task 2: 시드 init · export 스크립트 · Compose 마운트

**Recommended Skill:** `superpowers:test-driven-development` (스크립트는 shellcheck/수동 + 단위로 경로 상수 검증 가능하면 `tests/docker/test_seed_init.py`에서 파일 존재·shebang만)

**Files:**
- Create: `docker/postgres/init/10-restore-seed.sh`
- Create: `docker/postgres/init/20-create-test-db.sh` (기존 `init-test-db.sh` 내용 이동)
- Create: `scripts/export_supabase_seed.sh`
- Create: `data/seed/README.md` (시드 설명·개인정보 경고; dump는 Task 5)
- Create: `data/seed/.gitkeep` (dump 없을 때 디렉터리 유지)
- Modify: `compose.yaml`, `compose.prod.yaml` — init 디렉터리·시드 마운트
- Delete or leave stub: `docker/postgres/init-test-db.sh` → init/20으로 대체 후 구 경로 제거

**Interfaces:**
- Consumes: 시드 경로 `/seed/supabase_baseline.dump` (컨테이너 안)
- Produces: 빈 데이터 디렉터리에서만 restore; 파일 없으면 echo 경고 후 exit 0

- [ ] **Step 1: `10-restore-seed.sh`** — `set -eu`; dump 있으면 `pg_restore --no-owner --role="$POSTGRES_USER" -d "$POSTGRES_DB"`; 없으면 경고

- [ ] **Step 2: `20-create-test-db.sh`** — 기존 test DB 생성 SQL

- [ ] **Step 3: `export_supabase_seed.sh`** — `SUPABASE_DATABASE_URL` 필수, `pg_dump -Fc -f data/seed/supabase_baseline.dump`

- [ ] **Step 4: compose 볼륨**  
  - `./docker/postgres/init:/docker-entrypoint-initdb.d:ro`  
  - `./data/seed:/seed:ro`

- [ ] **Step 5: Commit** `db: 빈 볼륨 최초 기동 시 Supabase 시드를 복원하는 init을 추가한다`

---

### Task 3: web 기동 시 AUTO_DB_UPGRADE

**Files:**
- Create: `docker/web-entrypoint.sh`
- Modify: `Dockerfile` (prod·dev CMD/ENTRYPOINT)
- Modify: `compose.mac.yaml` / `compose.prod.yaml` — `AUTO_DB_UPGRADE=1`
- Create: `docs/adr/0002-auto-db-upgrade-on-boot.md` (한 페이지)

**Interfaces:**
- Produces: `AUTO_DB_UPGRADE=1`이면 `flask db upgrade` 후 exec 원래 CMD; 아니면 바로 exec

- [ ] **Step 1: entrypoint 스크립트** (root가 아닌 app 유저로 upgrade 가능해야 함)

- [ ] **Step 2: Dockerfile** — entrypoint 복사, `ENTRYPOINT ["/srv/docker/web-entrypoint.sh"]` 또는 `/srv/web-entrypoint.sh`; CMD는 기존 유지. Dockerfile 주석의 “시작 시 DB 이전을 자동 실행하지 않는다”를 ADR 예외로 수정

- [ ] **Step 3: ADR 0002**

- [ ] **Step 4: Commit** `deploy: AUTO_DB_UPGRADE 시 기동 전 flask db upgrade를 실행한다`

---

### Task 4: PUBLIC_BASE_URL · 문서 · OBD HTTPS 안내

**Files:**
- Modify: `app/config.py` — `PUBLIC_BASE_URL`
- Modify: `app/__init__.py` — `inject_globals`에 `public_base_url`
- Modify: `app/templates/canlab/_obd_panel.html`
- Modify: `tests/admin/test_pages.py` (vercel 하드코딩 assert 제거/교체)
- Modify: `README.md`, `DEPLOY.md`, `DEPLOY_GUIDE.md` — Mac Compose 공식, Supabase/Vercel 중단

- [ ] **Step 1: 테스트** — insecure 안내 HTML에 vercel 호스트가 없고 `PUBLIC_BASE_URL` 또는 상대 안내가 있음

- [ ] **Step 2: 템플릿·config·문서**

- [ ] **Step 3: Commit** `docs: Mac Compose PostgreSQL을 공식 운영으로 하고 Vercel URL 안내를 제거한다`

---

### Task 5: Supabase 시드 dump 생성 · Docker 검증 · GitHub 푸시

**Files:**
- Create: `data/seed/supabase_baseline.dump` (가능 시)

- [ ] **Step 1:** `SUPABASE_DATABASE_URL`이 환경/`.env`에 있으면 `scripts/export_supabase_seed.sh` 실행. 없으면 README에 “시드 없이 빈 DB” 상태로 두고 진행(차단하지 않음)

- [ ] **Step 2:** 로컬에서 **새 볼륨 이름**으로 `docker compose … up -d --build` 스모크(`/up` 200). 기존 `wecarscan_dh_pgdata`는 덮지 말 것(검증용 임시 프로젝트명 또는 별도 volume)

- [ ] **Step 3:** `main`에 커밋·푸시 → GHCR Actions 확인. Vercel/Supabase MCP 업로드 없음

- [ ] **Step 4:** 완료 보고(시드 포함 여부, Docker 상태, commit SHA)
