# 배포 가이드

scantest의 공식 운영 경로는 **Mac 서버 Docker Compose + Compose PostgreSQL**입니다. Vercel 앱과 Supabase DB 운영은 이 프로젝트에서 중단되었습니다.

## 공식 운영 경로: Mac Docker Compose

1. 서버에 `.env.production`을 만들고 `.env.example`의 필수값을 채웁니다.
2. `DATABASE_URL`은 Compose `db` 서비스를 가리키는 `postgresql+psycopg://...@db:5432/wecarscan` 형식을 씁니다.
3. 공개 HTTPS 도메인이 있으면 `PUBLIC_BASE_URL=https://scan.example.com`처럼 설정합니다. 비우면 OBD 패널은 현재 사이트의 HTTPS 주소를 쓰라고 안내합니다.
4. 운영 컨테이너는 아래처럼 실행합니다.

```bash
docker compose -f compose.prod.yaml --env-file .env.production up -d
docker compose -f compose.prod.yaml ps
curl http://localhost:${WEB_PORT:-8000}/up
```

`compose.prod.yaml`은 `AUTO_DB_UPGRADE=1`로 web 기동 전 `flask db upgrade`를 실행합니다. 빈 PostgreSQL 볼륨은 `data/seed/supabase_baseline.dump`가 있을 때 최초 1회만 복원하고, 기존 볼륨을 덮어쓰지 않습니다.

## 중단된 운영 경로(보관)

아래 Vercel/Supabase 절차는 과거 이력 확인용입니다. 새 배포, 장애 대응, 운영 문서에는 사용하지 않습니다.

## 사전 준비

### 1. Supabase 프로젝트 생성
1. https://supabase.com 에서 새 프로젝트 생성
2. Database 설정에서 Connection String 확인
   - **Direct connection**: 마이그레이션용
   - **Connection pooling (Transaction mode)**: 운영용
3. Settings → Database → Connection string 복사

### 2. 환경 변수 준비

필수 환경 변수 목록 (`.env.example` 참고):

```bash
# 보안 (각각 다른 32바이트 이상 랜덤 값)
SECRET_KEY=<랜덤 문자열>
JWT_SECRET=<랜덤 문자열>
ENCRYPTION_KEY=<Fernet 키: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">

# 데이터베이스
DATABASE_URL=<Supabase pooled connection string>
DATABASE_URL_DIRECT=<Supabase direct connection string>

# 운영 설정
FLASK_ENV=production
SESSION_COOKIE_SECURE=true
PROXY_FIX_HOPS=1

# 선택 (있으면 기능 활성화)
RATELIMIT_STORAGE_URI=<Redis URL>  # 로그인 속도 제한
OPENAI_API_KEY=<API 키>  # AI 기능
```

## Vercel 배포(중단됨, 보관)

### 1. Vercel CLI 설치 (로컬)
```bash
npm install -g vercel
vercel login
```

### 2. 프로젝트 연결
```bash
cd /workspace
vercel link
# 팀 선택, 프로젝트 이름 입력
```

### 3. 환경 변수 설정
```bash
# Vercel 대시보드에서 설정하거나 CLI로 설정
vercel env add SECRET_KEY production
# 값 입력 (프롬프트)
vercel env add JWT_SECRET production
vercel env add ENCRYPTION_KEY production
vercel env add DATABASE_URL production
vercel env add DATABASE_URL_DIRECT production
# ... 나머지 환경 변수
```

또는 Vercel 대시보드 → Settings → Environment Variables에서 설정

### 4. 마이그레이션 실행
```bash
# 로컬에서 Supabase direct connection으로
export DATABASE_URL="<direct connection string>"
flask db upgrade

# 또는 Vercel Function으로 실행 (한 번만)
vercel env pull .env.production
flask db upgrade
```

### 5. 배포
```bash
# 미리보기 배포
vercel

# 운영 배포
vercel --prod
```

### 6. 초기 관리자 생성
```bash
# 로컬에서 DATABASE_URL 설정 후
flask create-admin --tid wecar --name "관리자 이름"
# 비밀번호 입력

# 또는 Vercel SSH로 접속 (불가능하면 로컬에서 원격 DB로)
```

## Docker 배포 (자체 호스팅)

### 1. 이미지 빌드
```bash
SHA=$(git rev-parse --short HEAD)
docker build --target prod --build-arg APP_VERSION=2.0.0+$SHA \
  -t wecarmobility/scantest:latest \
  -t wecarmobility/scantest:$SHA .
```

### 2. Docker Hub/GHCR에 푸시
```bash
docker push wecarmobility/scantest:latest
docker push wecarmobility/scantest:$SHA

# 또는 GHCR
docker tag wecarmobility/scantest:latest ghcr.io/jty9410/scantest:latest
docker push ghcr.io/jty9410/scantest:latest
```

### 3. 운영 서버에서 실행
```bash
# .env.production 파일 생성 (위 환경 변수 포함)

# Compose로 실행
docker compose -f compose.prod.yaml up -d

# 마이그레이션
docker compose -f compose.prod.yaml exec web flask db upgrade

# 초기 관리자
docker compose -f compose.prod.yaml exec web flask create-admin --tid wecar --name "관리자"
```

## Supabase 설정(중단됨, 보관)

### 1. Row Level Security (RLS)
마이그레이션에 포함되어 있지만, 수동 확인:

```sql
-- 모든 테이블에 RLS 활성화 확인
SELECT tablename 
FROM pg_tables 
WHERE schemaname = 'public' 
  AND rowsecurity = false;

-- RLS가 비활성화된 테이블이 있으면
ALTER TABLE table_name ENABLE ROW LEVEL SECURITY;
```

### 2. 인덱스 확인
대용량 데이터에 대비:

```sql
-- 스캔 기록 인덱스
CREATE INDEX IF NOT EXISTS ix_scans_created_at_id ON scans(created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS ix_scans_tester_owner ON scans(tester_id, owner_id);

-- DTC 삭제 이력 인덱스
CREATE INDEX IF NOT EXISTS ix_dtc_clear_logs_scan_created ON dtc_clear_logs(scan_id, created_at DESC);
```

### 3. 백업 정책
Supabase 대시보드 → Database → Backups:
- 일일 자동 백업 활성화
- 보관 기간 설정 (최소 7일 권장)

## 배포 후 확인

### 1. 헬스체크
```bash
curl https://your-domain.vercel.app/up
# Expected: {"status":"ok"}
```

### 2. 관리자 로그인
1. https://your-domain.vercel.app/admin/ 접속
2. 초기 관리자 계정으로 로그인
3. MFA 설정 (Settings → 보안)
4. 다른 관리자 계정 생성 및 권한 부여

### 3. 기능 테스트
- [ ] 차량번호 조회
- [ ] 진단기 연결 (Web Bluetooth)
- [ ] 스캔 실행
- [ ] 고장코드 지우기 (권한 있는 관리자)
- [ ] PDF 다운로드
- [ ] API 호출 (`/api/auth/login`, `/api/scanPlan`)

### 4. 모니터링 설정
- Vercel: Analytics 탭에서 성능 확인
- Supabase: Dashboard → Database → Query Performance
- 에러 추적: Sentry 등 서비스 연동 권장

## 업데이트 배포

### 1. 코드 변경 후
```bash
git commit -m "feat: 새 기능"
git push origin main

# Vercel이 자동 배포 (GitHub 연동 시)
# 또는 수동 배포
vercel --prod
```

### 2. DB 마이그레이션이 있으면
```bash
# 1. 마이그레이션 먼저 실행 (다운타임 최소화)
flask db upgrade

# 2. 애플리케이션 배포
vercel --prod
```

### 3. 롤백이 필요하면
```bash
# Vercel 대시보드 → Deployments → 이전 배포 선택 → Promote to Production
# 또는
vercel rollback

# DB 롤백 (주의: 데이터 손실 가능)
flask db downgrade -1
```

## 문제 해결

### 마이그레이션 실패
```bash
# 현재 리비전 확인
flask db current

# 충돌 해결
flask db stamp head  # 주의: 수동 SQL 적용 후에만

# 마이그레이션 재실행
flask db upgrade
```

### "Pooled connection" 오류
- `DATABASE_URL`에 pooled connection string 사용
- `DATABASE_URL_DIRECT`에 direct connection string 사용
- 마이그레이션은 항상 direct로

### CSRF 토큰 오류
- `SESSION_COOKIE_SECURE=true` 확인
- `PROXY_FIX_HOPS=1` 설정 (Vercel 뒤에서)
- 쿠키 SameSite 설정 확인

### Web Bluetooth 연결 실패
- HTTPS 필수 (Vercel은 자동)
- Chrome/Edge 브라우저만 지원
- 로컬호스트에서는 HTTP도 가능

## 보안 체크리스트

- [ ] 모든 비밀값이 환경 변수로 설정됨 (코드에 하드코딩 없음)
- [ ] `SECRET_KEY`, `JWT_SECRET`, `ENCRYPTION_KEY`가 각각 다름
- [ ] `SESSION_COOKIE_SECURE=true` (HTTPS)
- [ ] RLS 활성화됨
- [ ] 관리자 MFA 활성화
- [ ] API rate limiting 설정 (Redis)
- [ ] 정기 백업 활성화
- [ ] 로그 모니터링 설정

## 연락처

배포 중 문제가 있으면:
- GitHub Issues: https://github.com/JTY9410/scantest/issues
- 개발팀 이메일: [연락처]
