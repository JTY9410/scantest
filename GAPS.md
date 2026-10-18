# 알려진 제약과 남은 작업

이 문서는 2026-10-18 기준으로 구현된 기능과 남은 작업을 요약합니다.

## 완료된 기능

### (1) DTC 삭제 기능
- ✅ 실시간 스캔 결과 및 저장된 스캔 상세에서 DTC 삭제 버튼 및 확인 대화상자
- ✅ 대상 ECU 목록, 예상 시간, 차량번호 확인, 엔진 OFF 체크박스
- ✅ n/N 진행률 표시, 전후 DTC 비교
- ✅ 권한(`can_clear_dtc`), MFA, 1회용 토큰, 감사 기록
- ✅ Rate limiting (시간당 5회)
- ✅ 회원 관리에서 `can_clear_dtc` 권한 토글

### (2) 스캔 이력
- ✅ 목록 페이지: VIN, 제조사/모델 필터, 고장코드 수, 배터리 SOH, 주행거리 표시
- ✅ 검색 및 필터링: 차량번호, VIN, 제조사, 모델, 날짜 범위
- ✅ 페이지네이션
- ✅ 상세 페이지: 원시 응답, 해석 값, DTC, 주행거리, 배터리, DTC 삭제 이력

### (4) 지식베이스
- ✅ DB 모델: `KnowledgeCommand`, `KnowledgeFormula`, `KnowledgeDTC`, `KnowledgeTerm`
- ✅ 제조사/모델/연도/ECU별 scoping, draft/verified/deprecated 상태 관리
- ✅ 관리 UI: 명령어/공식/DTC 목록, 검증 버튼
- ✅ Alembic 마이그레이션 (`87819b247758_add_knowledge_base_tables.py`)
- ✅ 역분석 모듈과 통계 연동 (대시보드에 지식베이스 항목 수 표시)
- ✅ Service 함수: `list_commands`, `list_formulas`, `list_dtcs`, `verify_*`, `import_from_commands_json`

### (5) 보안 개선
- ✅ DTC 삭제 API rate limiting (시간당 5회)
- ✅ 하드코딩된 비밀번호 없음 (테스트 코드 제외)
- ✅ 로그인 rate limiting 기존 존재

## 남은 작업 (미구현 또는 부분 구현)

### (3) 역분석 모듈 고도화 (부분)
**현재 상태**: 기존 역분석 모듈(`/admin/canlab/`)은 완전히 작동하며, WESCAN 통신기록과 리버스 데이터를 비교하여 디코딩 규칙을 생성하고 검증하는 전체 워크플로우가 구현되어 있습니다.

**미구현 기능**:
- [ ] 다양한 입력 형식 지원 개선
  - 현재: TRC, ELM AT 로그, PDF, 텍스트
  - 추가 필요: G-Scan 텍스트 출력, 추가 CSV 형식
- [ ] 알려진 명령어와의 자동 diff 및 갭 하이라이트 UI
- [ ] 후보 PID/디코드 공식 자동 제안 UI에 증거(evidence) 표시
- [ ] 검증된 역분석 결과를 지식베이스로 자동 export
  - 현재: 수동으로 `DecodeRule`에서 `KnowledgeFormula`로 복사해야 함
  - 필요: "지식베이스로 내보내기" 버튼

### (4) 지식베이스 완성
**현재 상태**: DB 스키마, 마이그레이션, 기본 CRUD UI는 완성

**미구현 기능**:
- [ ] commands.json import 스크립트/UI
  - Service 함수 `import_from_commands_json`은 구현됨
  - CLI 또는 Admin UI에서 호출하는 인터페이스 없음
- [ ] OBDb 데이터 import
  - canlab/references에 OBDb 동기화 기능이 있으나 지식베이스와 연동 안 됨
  - `CanReference` → `KnowledgeCommand/DTC` 변환 필요
- [ ] CSV import UI (bulk upload)
- [ ] AI/web-research hook
  - DRAFT 항목만 생성, `KNOWLEDGE_AI_KEY` 환경변수로 enable/disable
  - 예: OpenAI API로 DTC 설명 생성
- [ ] 스캔 planning/interpretation에서 지식베이스 읽기
  - 현재: `scanner/plan.py`, `scanner/interpret.py`는 하드코딩된 로직만 사용
  - 필요: `knowledge_service.list_commands(maker=...)`, `list_formulas(maker=...)`를 참조하도록 수정

### (6) 테스트 및 빌드 검증
**환경 제약**: Cloud Agent VM에 Docker와 Python 패키지가 설치되지 않음

**수행 불가 작업**:
- [ ] `docker build -t scantest .` 실행 및 결과 확인
- [ ] `docker compose up` 실행 및 앱 작동 확인
- [ ] `python -m pytest` 실행 및 235개 테스트 통과 확인
- [ ] `node --test tests/js` 실행 및 25개 테스트 통과 확인
- [ ] 스크린샷 생성:
  - DTC 삭제 dialog (scan result page)
  - 스캔 이력 목록 (/admin/scans)
  - 역분석 대시보드 (/admin/canlab/)
  - 지식베이스 명령어 목록 (/admin/knowledge/commands)

**권장 조치**: 로컬 또는 CI 환경에서 실행하거나, Docker가 설치된 환경에서 Cloud Agent 재실행

## 보안

### 완료
- ✅ Rate limiting: 로그인, MFA, DTC 삭제
- ✅ CSRF 토큰: 모든 POST/DELETE/PUT 요청 (Flask-WTF)
- ✅ 하드코딩된 비밀번호 없음 (운영 코드)

### 권장 추가
- [ ] MFA seed 및 API 키 암호화는 `SECRET_KEY` 환경변수 의존
  - 운영 환경에서 `SECRET_KEY`를 안전하게 관리하고 주기적으로 rotation
- [ ] CSP nonce 사용 (현재는 inline script 일부 허용)
- [ ] Content-Security-Policy 강화 (script-src, connect-src)
- [ ] 추가 엔드포인트 rate limiting (예: 스캔 결과 조회, PDF 생성)

## DTC 삭제 정책 (2026-10-18 대표 결정)

### 허용 조건
- 저장된 스캔에서만 (30분 이내)
- 웹 관리자: `can_clear_dtc` 권한 + MFA
- 앱 사용자: 소유자(owner) 불가, 전문가(expert) 이상
- 차량번호 타이핑 확인
- 정차(`010D` 속도 = 0) 확인

### 기술 흐름
1. 1회용 토큰 발급 (SHA-256, 20분 만료, DB 저장)
2. 응답한 모든 ECU + 6개 기본 ECU 대상
3. `14 FF FF FF` 전송 (UDS Service $14)
4. NRC 78 → 최대 6회 재시도 (2초 간격)
5. NRC 7F → `10 03` → `14` → `10 01` fallback
6. 결과를 `dtc_clear_logs` 테이블에 저장 (감사기록)

## 배포 전 체크리스트

### 필수
- [ ] 마이그레이션 실행: `flask db upgrade`
- [ ] 테스트 통과: `python -m pytest -q`
- [ ] JavaScript 테스트: `node --test tests/js`
- [ ] Docker 빌드: `docker build -t scantest .`
- [ ] Vercel 환경 변수 설정 (DEPLOY.md 참조)
- [ ] Supabase PostgreSQL 연결 확인 (pooled URL for web, direct URL for migrations)

### 권장
- [ ] 관리자 계정에 `can_clear_dtc` 권한 부여
- [ ] 관리자 MFA 활성화
- [ ] 초기 데이터 시딩 (commands.json import)
- [ ] 백업 정책 수립
- [ ] 모니터링 설정 (Sentry, Datadog 등)

## 참고 자료

- `pro.md`: 기술개발 정의서
- `AGENTS.md`: 작업 규칙
- `DEPLOY.md`: Vercel + Supabase 배포 가이드
- `docs/flows/scanner.md`: 스캔 흐름
- `docs/flows/canlab.md`: CAN 역분석
- `uploads/wecar_scan_analysis.zip`: WESCAN 앱 분석 보고서 및 commands.json
