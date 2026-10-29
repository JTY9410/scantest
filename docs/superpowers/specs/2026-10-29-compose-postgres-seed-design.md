# Compose PostgreSQL 전환 · Supabase 시드 최초 복원

날짜: 2026-10-29. Supabase·Vercel 앱 운영을 중단하고, Mac 서버 Docker Compose의 PostgreSQL만 쓴다. 기존 Supabase 데이터는 저장소 시드로 넣어 **빈 볼륨 최초 기동 시** 자동 복원한다.

## 확정된 결정

| 항목 | 선택 |
|------|------|
| DB | Docker Compose PostgreSQL 16 (`db` 서비스) |
| 운영 | 별도 Mac 서버 Docker만 |
| Vercel 앱 | 중단(운영 경로에서 제외) |
| 데이터 | Supabase `pg_dump -Fc` → 저장소 시드 → 빈 `pgdata` init 시 복원 |
| 시드 보관 | 저장소 포함(비공개 리포·개인정보 포함 가능 전제) |
| 기동 방식 | Postgres init 복원 + web `flask db upgrade` |

## 목표·경계

- Supabase 연결을 끊고 Compose `db`만 사용한다.
- Vercel을 공식 운영 배포로 안내하지 않는다.
- 시드는 **데이터 디렉터리가 비어 init이 돌 때만** 복원한다. 기존 볼륨은 덮어쓰지 않는다.
- Supabase 프로젝트 삭제는 저장소 밖(운영자 수동)이다.

## 디렉터리·기동 흐름

- `data/seed/supabase_baseline.dump` — `pg_dump -Fc` 결과(커밋). README에 개인정보 경고.
- `docker/postgres/init/10-restore-seed.sh` — 시드가 있으면 `pg_restore`(`ON_ERROR_STOP`). 없거나 0바이트면 스키마만 비운 채 기동(개발용)하고 경고 로그.
- `docker/postgres/init/20-create-test-db.sh` — 기존 `init-test-db.sh`와 동일(테스트 DB). 파일명 순서로 시드 다음.
- `scripts/export_supabase_seed.sh` — `SUPABASE_DATABASE_URL`(Direct, non-pooler)로 시드 재생성.
- Compose `db` 볼륨에 `docker/postgres/init/` 전체와 `data/seed/`를 마운트.
- `web` 엔트리(또는 compose `command` wrapper): 기동 전 `flask db upgrade`(이미 head면 no-op). Mac/prod에서 `AUTO_DB_UPGRADE=1` 기본.

흐름:

1. 첫 `compose up` → 빈 볼륨 → init: 시드 복원 → 테스트 DB 생성  
2. web → `flask db upgrade` → 서빙  
3. 재시작 → init 스킵, upgrade만  

`pro.md`의 “운영 시작 때 무조건 자동 이전 금지”는 Mac 최초 배포 편의를 위해 이 스펙 범위에서 예외로 두고, `docs/adr/`에 한 줄 ADR을 남긴다.

## 설정·문서·화면

- `database_url()`: `DATABASE_URL`만. `POSTGRES_URL`·`supa` 쿼리 제거 로직은 불필요하면 삭제.
- compose `.env` / `.env.example`: `DATABASE_URL=postgresql+psycopg://wecarscan:…@db:5432/wecarscan`. Supabase·Vercel 전용 변수 제거.
- `README`·`DEPLOY.md`·`DEPLOY_GUIDE.md`: Mac Compose가 공식 경로. Supabase/Vercel은 “중단됨” 절.
- `_obd_panel.html` HTTPS 안내의 `scantest-eta.vercel.app` → `PUBLIC_BASE_URL`(환경변수, 없으면 현재 origin 안내문).
- `vercel.json`은 당장 삭제하지 않아도 되나 운영 체크리스트·업로드 대상에서 제외.

## 데이터 이전·검증·실패

**시드 생성(구현/배포 전 1회)**

1. Supabase Direct URL로 `scripts/export_supabase_seed.sh` 실행 → `data/seed/supabase_baseline.dump`
2. 덤프에 `alembic_version` 포함 여부 확인. 복원 후 web upgrade가 head까지 올린다.
3. 시드가 아직 없으면 Mac 최초 up은 빈 DB + upgrade만(관리자 재등록). 시드 추가 후 **새 볼륨**으로만 재복원 가능함을 문서화.

**검증**

- 빈 볼륨으로 `compose up` → 시드 테이블/행 존재, 로그인 가능(시드에 관리자 있을 때).
- 같은 볼륨 재기동 → 데이터 유지, 중복 복원 없음.
- `flask db upgrade` 두 번 연속 no-op/성공.
- 관련 설정 단위 테스트(URL 해석, PUBLIC_BASE_URL 템플릿).

**실패**

- `pg_restore` 실패 시 DB 컨테이너가 unhealthy/재시작 → web은 depends_on으로 대기. 로그로 원인 확인.
- 시드 없음: 경고만 하고 빈 DB(개발 허용). 운영 Mac은 시드 커밋을 전제로 한다.

## 배포(이 작업의 업로드 범위)

- GitHub `main` 푸시
- 로컬/Mac Docker 이미지 재빌드·컨테이너 재기동
- GHCR는 기존 `docker-publish` 워크플로가 main 푸시로 처리
- **Vercel·Supabase 업로드/연동 변경은 하지 않음**(운영 중단)

## 비범위

- SQLite 전환
- 기존 `pgdata` 강제 재시드
- Supabase 대시보드 프로젝트 삭제 자동화
- Vercel 프로젝트 pause API 자동화
