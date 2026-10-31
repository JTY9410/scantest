# WecarScan

차량 진단 앱(WecarScan)의 API 서버와 관리자 웹입니다. 요구사항은 `pro.md`(기술개발 정의서)를 따릅니다.

- 백엔드: Python 3.12, Flask 3.1, SQLAlchemy 2.0, Flask-Migrate(Alembic), PostgreSQL 16
- 관리자 화면: Jinja 템플릿, Tailwind CSS 4(근거는 `docs/adr/0001-tailwind-instead-of-bootstrap.md`), PWA
- 모바일 앱 API: `/api/*`. 이전 Laravel 서버와 응답 형식이 같습니다(`docs/legacy/laravel-api.json`).

## 폴더 구조

```
app/
  __init__.py        create_app, 오류 처리, 보안 헤더
  config.py          환경 변수 → 설정
  core/              감사기록(audit), 암호화, 페이지네이션, 입력 검증, 시간
  modules/<기능>/    routes(요청·응답) → service(업무 규칙) → models(저장)
  templates/         layouts, components(공통 매크로·푸터), 기능별 화면
  static/css/        tokens.css(색·간격), components.css, app.css(Tailwind 입력)
  static/js/         app.js(드로어·툴팁·확인), components/pwa.js
migrations/          Alembic 이전 스크립트
tests/               api(앱 호환), admin(관리자 화면)
docs/flows/          기능별 흐름, docs/adr/ 기술 결정
```

## 로컬 실행

Docker Desktop이 필요합니다.

```bash
cp .env.example .env           # 비밀값 3개와 DB 비밀번호를 채운다(파일 안 안내 참고)
docker compose up -d --build   # web(18080), assets(CSS 감시), db
docker compose exec web flask db upgrade
docker compose exec web flask create-admin --tid wecar --name 관리자   # 비밀번호는 프롬프트 또는 ADMIN_PASSWORD
# 이미 계정이 있는데 .env 의 ADMIN_PASSWORD 로 로그인이 안 되면:
docker compose exec web flask reset-admin-password --tid wecar
```

브라우저에서 <http://localhost:18080/admin/> 로 접속합니다. 관리자 계정은 `create-admin`으로 한 번만 만들며, 코드나 이미지에 비밀번호를 넣지 않습니다.

CSS를 고치면 `assets` 컨테이너가 `app/static/dist/app.css`를 다시 만듭니다. 컨테이너 없이 빌드하려면 `npm ci && npm run build:css`.

## 설정

모든 설정은 환경 변수로 받습니다. 목록과 설명은 `.env.example`에 있습니다.

| 변수 | 용도 |
| --- | --- |
| `SECRET_KEY`, `JWT_SECRET` | 세션 서명, 앱 JWT 서명 |
| `ENCRYPTION_KEY` | AI 키·OTP 비밀값 암호화(Fernet). 바꾸면 기존 값은 복호화되지 않습니다. |
| `DATABASE_URL`, `TEST_DATABASE_URL` | 운영·테스트 DB |
| `RATELIMIT_STORAGE_URI` | 로그인 속도 제한 저장소. 운영은 Redis |
| `SESSION_COOKIE_SECURE`, `PROXY_FIX_HOPS` | HTTPS 쿠키, 프록시 뒤 실제 IP |
| `PUBLIC_BASE_URL` | OBD HTTPS 안내에 표시할 공개 HTTPS 주소. 비우면 현재 사이트 주소 기준으로 안내 |
| `AUTO_DB_UPGRADE` | Mac/prod Compose에서 web 기동 전 `flask db upgrade` 실행 |

`.env`, `.env.production`은 저장소에 올리지 않습니다.

## DB 이전

```bash
docker compose exec web flask db migrate -m "설명"   # 스크립트 생성
# migrations/versions/ 의 새 파일을 검토한다(인덱스, FK 정책, 기본값)
docker compose exec web flask db upgrade
```

Mac/prod Compose 운영은 `AUTO_DB_UPGRADE=1`로 web 기동 전 `flask db upgrade`를 실행합니다. 새 마이그레이션을 만들 때는 위 순서대로 스크립트를 생성하고 반드시 검토합니다.

## 테스트

```bash
docker compose run --rm --no-deps web python -m pytest -q
```

테스트는 `TEST_DATABASE_URL`(기본 `wecarscan_test`, db 컨테이너가 처음 뜰 때 생성)을 씁니다. CSRF와 속도 제한을 켠 상태로 검사합니다.

## 배포 (Mac 서버 · 공식)

구조: **nginx(https) → 127.0.0.1:포트 → 컨테이너**. Vercel·Supabase는 쓰지 않습니다.  
`main` push → 서버 웹훅이 pull·재기동. 서버는 레포의 `compose.prod.yaml`(또는 `compose.yaml`) + **서버 전용** `docker-compose.override.yml`(커밋 금지) + **서버 `.env`** 로 실행합니다. 시크릿은 서버 `.env`에만 둡니다.

```bash
cp .env.example .env          # 서버에서만 비밀값 채움
# 선택: cp docker-compose.override.example.yml docker-compose.override.yml
docker compose -f compose.prod.yaml up -d --build
curl -sS http://127.0.0.1:8000/up
```

- 포트: `${WEB_BIND:-127.0.0.1}:${WEB_PORT:-8000}:8000`
- 프록시 1단: `TRUST_PROXY=1` 또는 `PROXY_FIX_HOPS=1`, `SESSION_COOKIE_SECURE=true`, `PUBLIC_BASE_URL=https://…`
- `AUTO_DB_UPGRADE=1`이면 web 기동 전 `flask db upgrade` 1회
- 이미지: GHCR `ghcr.io/jty9410/scantest` (Actions가 `main` 푸시 시 빌드)

### Postgres 볼륨·메이저 버전

볼륨 이름 `wecarscan_dh_pgdata`와 이미지 `postgres:16-alpine`을 바꾸면 **기존 데이터를 읽지 못할 수 있습니다.** 변경이 필요하면:

1. `pg_dump`로 백업  
2. 새 볼륨/메이저로 compose 기동  
3. `pg_restore` 후 `flask db upgrade`  
4. 앱 `/up`·로그인 확인  

복원 실패 시 데이터가 반만 들어간 채로 healthy가 될 수 있으니, 빈 볼륨으로 `docker compose down -v` 후 재시도할지 운영에서 결정합니다(파괴적).

### Supabase → 내장 DB 이전

서버에서 일회성으로:

```bash
export SUPABASE_DATABASE_URL='…'   # Session pooler URI, 별도 채널
export TARGET_DATABASE_URL='…'     # Compose Postgres
./scripts/migrate_from_supabase.sh
```

**컷오버:** 스크립트 실행 직전부터 Supabase 쓰기를 중단하고 그 시각을 기록합니다. 이후 Supabase에 쓰면 데이터가 어긋납니다.  
dump에는 개인정보가 들어갈 수 있어 **레포에 커밋하지 않습니다.**

빈 볼륨 최초 기동 시 시드 복원은 `data/seed/` + `docker/postgres/init/` 흐름입니다(`data/seed/README.md`).

### 스케줄러·메모리

이 저장소에는 vehicle-data-hub 일일 수집·wecar_pm sync 같은 상시 스케줄러가 없습니다. gunicorn 워커·동시 스캔만 유의하면 됩니다. 대량 배치 작업이 생기면 서버 메모리에 맞춰 수동으로 켜고, 예상 행 수·피크 메모리를 이 절에 추가합니다.

### 중단된 운영 경로

Supabase·Vercel 앱 배포는 공식 경로에서 제외되었습니다.

## 기능 흐름

- 관리자 로그인·MFA: `docs/flows/auth.md`
- 회원 관리: `docs/flows/members.md`
- AI 연결: `docs/flows/ai.md`
- 블루투스 OBD2 연결 프로필: `docs/flows/obd.md`
- 모바일 앱 API: `docs/flows/api.md`
- CAN 역분석·운영 결과지·블루투스 수집: `docs/flows/canlab.md`

## CAN/UDS/BMS 역분석 도구

위스캔 스캔 데이터와 리버스 데이터(TRC)를 비교하는 역분석, 스캔 로직 적용, 운영 결과지는 관리자 메뉴 "CAN 분석"(`app/modules/canlab/`)에서 합니다(`docs/flows/canlab.md`). 쌓인 CAN 분석 데이터는 `flask canlab reset`(건수 확인) → `flask canlab reset --yes`로 지웁니다.

실제 차량 데이터(TRC·PDF)는 VIN 같은 차량 정보가 들어 있어 저장소에 넣지 않고 화면에서 올립니다(DB에 저장). 로컬에 둘 때는 git·Docker·Vercel에서 제외되는 `data/`에 둡니다.

## 남은 제약

- SMS 발송, 진단서 PDF, 이메일 발송은 이전 서버처럼 응답만 유지하고 실제 발송·생성은 하지 않습니다.
- 이전 Laravel 서버의 MySQL 데이터는 옮기지 않았습니다.

### Mac 상시 실행(운영 방식, gunicorn)

개발 서버(Flask 디버거) 대신 prod 이미지로 web 을 띄웁니다. db 컨테이너와 데이터는 그대로 씁니다.

```bash
docker compose -f compose.yaml -f compose.mac.yaml up -d --build web
```
