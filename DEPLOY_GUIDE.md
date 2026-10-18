# WECAR Scan 배포 가이드

## 사전 준비

### 1. GitHub
- ✅ 코드가 `cursor/complete-wecar-scan-features-0b37` 브랜치에 푸시됨
- ✅ PR #2: https://github.com/JTY9410/wecarscan_dh/pull/2

### 2. 필요한 계정
- Vercel 계정 (https://vercel.com)
- Supabase 계정 (https://supabase.com)
- GitHub 저장소 접근 권한

---

## 로컬 테스트 (배포 전 필수)

### 1. Docker 빌드 테스트

```bash
# 프로젝트 루트에서
docker build --target prod -t scantest:latest .
```

**성공 시**: "Successfully tagged scantest:latest" 메시지 확인

### 2. Docker Compose로 로컬 실행

```bash
# .env 파일 생성
cp .env.example .env

# .env 파일 편집 (필수 환경변수 입력)
# POSTGRES_PASSWORD, SECRET_KEY, JWT_SECRET 등

# 실행
docker compose up -d

# 마이그레이션
docker compose exec web python -m flask db upgrade

# 표준 OBD2 데이터 시딩
docker compose exec web python -m flask shell
>>> from app.modules.knowledge.importer import seed_standard_obd2
>>> seed_standard_obd2()
>>> exit()

# 접속 테스트
open http://localhost:18080/admin/
```

### 3. 테스트 실행 (PostgreSQL 환경)

```bash
# Docker 환경에서
docker compose exec web python -m pytest -v

# 또는 로컬 PostgreSQL에서
export TEST_DATABASE_URL="postgresql://user:password@localhost/wecarscan_test"
python -m pytest -v
```

**목표**: 전체 테스트 통과 (247 pytest + 25 JS)

---

## Supabase 설정

### 1. 프로젝트 생성
1. https://supabase.com 로그인
2. "New Project" 클릭
3. 프로젝트 이름: `wecarscan-prod` (또는 원하는 이름)
4. 데이터베이스 비밀번호 설정 (강력한 비밀번호 사용)
5. 리전 선택: Northeast Asia (Seoul) 권장
6. 생성 완료 대기 (약 2분)

### 2. 데이터베이스 URL 확인
1. 프로젝트 대시보드 → Settings → Database
2. **Connection string** 섹션:
   - **Pooled URL** (Transaction mode): Vercel 웹 앱용
   - **Direct URL** (Session mode): 마이그레이션용

### 3. 데이터베이스 마이그레이션

```bash
# 로컬 또는 CI 환경에서
export DATABASE_URL="postgresql://postgres.[project-ref]:[password]@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres?pgbouncer=true"
export DIRECT_DATABASE_URL="postgresql://postgres.[project-ref]:[password]@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres"

# 마이그레이션 (Direct URL 사용)
DATABASE_URL=$DIRECT_DATABASE_URL python -m flask db upgrade

# 표준 OBD2 데이터 시딩
python -m flask shell
>>> from app.modules.knowledge.importer import seed_standard_obd2
>>> count = seed_standard_obd2()
>>> print(f"Seeded {count} items")
>>> exit()
```

### 4. 관리자 계정 생성

```bash
# 마이그레이션 후
python -m flask shell

>>> from app.cli import create_admin_user
>>> create_admin_user()
# 또는 직접 실행
>>> from app.modules.accounts.service import create_admin
>>> from app.extensions import db
>>> admin = create_admin(
...     tid="admin",
...     password="강력한_비밀번호",
...     name="관리자",
...     email="admin@wecar.kr"
... )
>>> db.session.commit()
>>> print(f"Admin created: {admin.tid}")
>>> exit()
```

---

## Vercel 배포

### 1. Vercel 프로젝트 생성
1. https://vercel.com 로그인
2. "Add New..." → "Project" 클릭
3. GitHub 저장소 선택: `JTY9410/wecarscan_dh`
4. 브랜치 선택: `cursor/complete-wecar-scan-features-0b37` 또는 `main` (PR 병합 후)

### 2. 환경변수 설정

**Project Settings → Environment Variables** 에서 다음 추가:

#### 필수 환경변수

```
# App
APP_ENV=production
DEBUG=False

# 보안 (강력한 무작위 문자열 생성)
SECRET_KEY=<openssl rand -base64 32>
JWT_SECRET=<openssl rand -base64 48>
ENCRYPTION_KEY=<python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">

# 데이터베이스 (Supabase Pooled URL)
SQLALCHEMY_DATABASE_URI=postgresql://postgres.[project-ref]:[password]@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres?pgbouncer=true

# Rate Limiting
RATELIMIT_STORAGE_URI=memory://
ADMIN_LOGIN_RATE_LIMIT=5 per 15 minutes

# Session
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE=Lax
REMEMBER_COOKIE_SECURE=True
PERMANENT_SESSION_LIFETIME=43200

# CORS (필요 시)
CORS_ORIGINS=https://your-domain.vercel.app
```

#### 선택 환경변수

```
# 차량정보 API
CAR_INFO_API_URL=https://api.car-info-service.com/get_car_info
CAR_INFO_API_KEY=<your-api-key>

# SMS 인증
SMS_API_KEY=<your-sms-api-key>
SMS_API_SECRET=<your-sms-api-secret>

# AI 연결 (CAN 분석)
OPENAI_API_KEY=<your-openai-key>

# 지식베이스 AI 연구 (선택)
KNOWLEDGE_AI_KEY=<your-ai-key>
```

### 3. vercel.json 확인

프로젝트 루트의 `vercel.json`:

```json
{
  "buildCommand": "pip install -e . && npm ci && npm run build:css",
  "devCommand": "gunicorn -c gunicorn.conf.py app.wsgi:app",
  "installCommand": "pip install -e .",
  "outputDirectory": "app/static",
  "framework": null,
  "rewrites": [
    {
      "source": "/(.*)",
      "destination": "/api/index"
    }
  ]
}
```

### 4. 배포 실행

1. Vercel 대시보드에서 "Deploy" 클릭
2. 빌드 로그 확인
3. 배포 완료 시 URL 확인: `https://your-project.vercel.app`

### 5. 배포 후 확인

```bash
# 헬스체크
curl https://your-project.vercel.app/api/health

# 관리자 로그인
open https://your-project.vercel.app/admin/login
```

---

## 배포 후 설정

### 1. 관리자 MFA 활성화
1. `/admin/login` 로그인
2. 우측 상단 계정 메뉴 → "계정 설정"
3. "2단계 인증 (MFA) 설정" 클릭
4. QR 코드를 Google Authenticator 등록
5. 확인 코드 입력 후 활성화

### 2. DTC 삭제 권한 부여
1. `/admin/members` 이동
2. 관리자 계정 편집
3. "권한" 섹션에서 "고장코드 지우기 (can_clear_dtc)" 체크
4. 저장

### 3. 표준 OBD2 데이터 확인
1. `/admin/knowledge/commands` 이동
2. 표준 명령어 확인 (Mode 01, UDS 서비스 등)
3. 없으면 `/admin/knowledge/import` → "표준 데이터 시딩" 클릭

### 4. 커스텀 도메인 설정 (선택)
1. Vercel Project Settings → Domains
2. 도메인 추가 (예: `scan.wecar.kr`)
3. DNS 레코드 설정 (CNAME 또는 A)

---

## 모니터링 및 유지보수

### 1. 로그 확인
- Vercel 대시보드 → Deployments → 최신 배포 → Logs
- Supabase 대시보드 → Database → Query 탭 (느린 쿼리 확인)

### 2. 데이터베이스 백업
- Supabase 대시보드 → Database → Backups
- 자동 백업 활성화 (Pro 플랜)
- 수동 백업: `pg_dump` 사용

```bash
# Supabase 백업
pg_dump "postgresql://postgres.[project-ref]:[password]@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres" > backup_$(date +%Y%m%d).sql
```

### 3. 마이그레이션 적용
```bash
# 새 마이그레이션 적용 (Direct URL 사용)
export DATABASE_URL="<Supabase Direct URL>"
python -m flask db upgrade
```

### 4. 에러 모니터링 (권장)
- Sentry 연동 (https://sentry.io)
- `.env`에 `SENTRY_DSN` 추가

---

## 트러블슈팅

### 빌드 실패
- **에러**: "No module named 'app'"
  - **해결**: `pyproject.toml` 확인, `pip install -e .` 실행
- **에러**: "Multiple top-level packages"
  - **해결**: 이미 수정됨 (setup.cfg 또는 pyproject.toml에 패키지 정의)

### 마이그레이션 실패
- **에러**: "Multiple head revisions"
  - **해결**: 이미 수정됨 (`87819b247758` → `d5e6f7a8b9c0`)
- **에러**: "relation already exists"
  - **해결**: DB 초기화 후 재시도 또는 충돌 마이그레이션 수동 해결

### Vercel 배포 타임아웃
- **원인**: 빌드 시간 초과 (10분 제한)
- **해결**: 
  - 의존성 캐싱 확인
  - `vercel.json`의 `buildCommand` 최적화

### Supabase Connection Pooling
- **증상**: "Too many connections"
- **해결**:
  - Pooled URL 사용 확인
  - `pgbouncer=true` 쿼리 파라미터 추가
  - Connection pooler mode: Transaction

---

## 체크리스트

### 배포 전
- [ ] 로컬에서 `docker build --target prod` 성공
- [ ] 로컬에서 `docker compose up` 및 접속 확인
- [ ] PostgreSQL 환경에서 전체 테스트 통과
- [ ] 마이그레이션 `flask db upgrade` 성공
- [ ] 표준 OBD2 데이터 시딩 완료

### Supabase 설정
- [ ] 프로젝트 생성 및 비밀번호 설정
- [ ] Pooled URL 및 Direct URL 확인
- [ ] 마이그레이션 실행 (Direct URL)
- [ ] 관리자 계정 생성
- [ ] 표준 OBD2 데이터 시딩

### Vercel 배포
- [ ] GitHub 저장소 연결
- [ ] 필수 환경변수 설정 (SECRET_KEY, JWT_SECRET, DATABASE_URL 등)
- [ ] 빌드 및 배포 성공
- [ ] 헬스체크 확인
- [ ] 관리자 로그인 확인

### 배포 후
- [ ] 관리자 MFA 활성화
- [ ] DTC 삭제 권한 부여
- [ ] 지식베이스 데이터 확인
- [ ] 커스텀 도메인 설정 (선택)
- [ ] 백업 정책 설정
- [ ] 모니터링 도구 연동 (선택)

---

## 참고 자료

- `GAPS.md`: 남은 작업 및 제약사항
- `pro.md`: 기술개발 정의서
- `AGENTS.md`: 개발 규칙
- Vercel 문서: https://vercel.com/docs
- Supabase 문서: https://supabase.com/docs
