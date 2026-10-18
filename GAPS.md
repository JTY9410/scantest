# 남은 제약과 개선 사항

2026-10-18 작업 완료 후 남은 항목들입니다.

## 완료된 작업

### 1. DTC 삭제 버튼과 확인 대화상자
- ✅ `app/templates/scanner/result.html`: 고장코드 지우기 버튼 추가
  - 권한(`can_clear_dtc`) 및 MFA 확인
  - 고장코드가 있고 스캔이 성공/일부 성공인 경우만 활성화
- ✅ `app/static/js/components/obd-clear.js`: 확인 모달 및 실행 로직
  - 차량번호 입력 확인
  - 정차/시동 OFF/IG ON 체크박스
  - 계획 발급 → 진단기 실행 → 결과 저장 흐름
  - 제어기별 상태, 지운/남은/새 코드 표시

### 2. 회원 관리 권한 토글
- ✅ `app/modules/members/forms.py`: `can_clear_dtc` 필드 추가
- ✅ `app/modules/members/service.py`: 소유자 권한 부여 금지 검증
- ✅ `app/templates/members/edit.html`: 권한 설정 섹션
- ✅ `app/templates/members/show.html`: 권한 표시
- ✅ 감사기록에 권한 변경 기록

### 3. 저장된 스캔 기록
- ✅ 이미 구현됨: `/admin/scans`, `/admin/scans/<id>`
- ✅ `app/templates/monitoring/scan_show.html`: DTC 삭제 이력 섹션 추가
- ✅ `app/modules/monitoring/service.py`: `get_scan_clear_logs` 함수

### 4. 역분석 모듈
- ✅ 이미 완전히 구현됨 (`app/modules/canlab/`, `docs/flows/canlab.md`)
  - 위스캔 통신기록 + 리버스 데이터 비교
  - 3단계 분석 (리버스 해석 → 통신기록 대조 → 최종값 일치)
  - 디코딩 규칙 후보 생성 및 과거 데이터 비교
  - 변경 이력, 문제 로그, 되돌리기

### 5. 지식베이스
- ✅ 이미 완전히 구현됨 (`app/modules/canlab/references.py`, `can_references` 테이블)
  - 제조사/모델/년식별 참고자료 DB
  - OBDb 동기화 (CC BY-SA 4.0)
  - URL 기반 참고자료 등록 및 AI 추출
  - 승인/반려 워크플로우
  - 스캔 계획과 해석에 검증된 항목만 사용

### 6. 문서 업데이트
- ✅ `docs/flows/api.md`: DTC 삭제 API 추가
- ✅ `docs/flows/members.md`: 권한 설명 추가

### 7. 테스트
- ✅ `tests/admin/test_dtc_clear_ui.py`: UI 권한 및 이력 테스트
- ✅ 기존 테스트: `tests/scanner/test_clear_flow.py` (백엔드 로직 235개 + JS 25개)

## 남은 작업 (선택적)

### 1. 추가 테스트
- [ ] 회원 관리 권한 토글 통합 테스트
- [ ] JavaScript E2E 테스트 (DTC 삭제 흐름)
- [ ] API 호환성 테스트 (`/api/scans/<id>/clearPlan`, `/api/scans/<id>/clear`)

### 2. 앱(wecar_scan) 연동
- [ ] `lib/services/obd/obd_plan.dart`: 서버와 같은 규칙 적용
  - 응답 주소 예외표 (`REPLY_OVERRIDE = {"717": "71D"}`)
  - `st` 필드 처리 (`ATST19`, STN `STPX t:`)
  - `pendingRetries` 처리 (NRC 78 재시도)
  - `sessionFallback` 처리 (NRC 7F → `10 03` → `14` → `10 01`)
  - `skip` 규칙 (`010D` 차속, `when.clearFallback`)
- [ ] 앱 화면: 확인 창, 진행 표시, 결과 화면
- [ ] dev 브랜치 기능 병합 (주행거리, 0105, 고장코드 유형)

### 3. 실차 검증
- [ ] 실주행거리 바이트 배치 검증 (`22 B002`, `B004`, `B001`, `B003`, `22 1050`)
  - 5개 차종: 아반떼 CN7, 쏘렌토 MQ4 HEV, EV6, 아이오닉5, 코나 EV
  - TRC + 계기판 사진 비교
- [ ] 제어기 순회 시간 실측 (추정 내연 +8~15초, 전동 +15~25초)
- [ ] DTC 삭제 시간 실측 (추정 내연 10~25초, 전동 15~45초)

### 4. UI/UX 개선
- [ ] 역분석 화면 간소화 (현재는 복잡)
- [ ] 지식베이스 검색 및 필터
- [ ] DTC 삭제 진행 상태를 더 자세히 표시 (현재 제어기 주소, NRC 내용 등)
- [ ] 모바일 화면 최적화 확인

### 5. 보안 강화
- [ ] DTC 삭제 rate limiting (사용자당 일일 제한)
- [ ] 추가 감사 로그 (실패한 시도, 권한 거부 등)
- [ ] IP 주소 기록 및 추적

### 6. 성능 개선
- [ ] DTC 삭제 이력 페이지네이션 (많을 경우)
- [ ] 스캔 기록 인덱스 최적화
- [ ] 대용량 통신 기록 처리 (현재는 JSON으로 저장)

## 알려진 버그/제약

### 1. 하드코딩된 값
- ⚠️ 위카 앱 dev에 하드코딩된 전문가 모드 비밀번호 (서버 권한으로 대체 필요)
- ⚠️ 일부 ELM327 어댑터에서 `NO DATA` 없이 멈춤 (1초 제한으로 우회)

### 2. 실차 미검증
- ⚠️ 실주행거리 바이트 배치가 추정치 (65,535 km 이상에서 틀릴 수 있음)
- ⚠️ `22 1050`이 주행가능거리인 차종 존재 가능성 (계기판과 5% 차이 시 경고)

### 3. 브라우저 제한
- ⚠️ Web Bluetooth는 Chrome/Edge만 지원 (Firefox, Safari 불가)
- ⚠️ 인앱 브라우저(카카오톡, 네이버)에서 BLE 연결 불가

### 4. DB 제약
- ⚠️ SQLite는 동시 쓰기 제한 → 운영은 PostgreSQL 필수
- ⚠️ `dtc_clear_logs.steps` JSON이 클 수 있음 (수백 제어기)

## 배포 전 체크리스트

### 필수
- [ ] 마이그레이션 실행: `flask db upgrade`
- [ ] 테스트 통과: `python -m pytest -q`
- [ ] JavaScript 테스트: `node --test tests/js`
- [ ] Docker 이미지 빌드 성공
- [ ] Vercel 환경 변수 설정
- [ ] Supabase PostgreSQL 연결 확인

### 권장
- [ ] 관리자 계정에 `can_clear_dtc` 권한 부여
- [ ] 관리자 MFA 활성화
- [ ] 초기 데이터 시딩 (진단 코드 DB 등)
- [ ] 백업 정책 수립
- [ ] 모니터링 설정 (오류 추적, 성능)

## 참고 자료

- `pro.md`: 기술개발 정의서
- `AGENTS.md`: 작업 규칙
- `docs/flows/scanner.md`: 스캔 흐름
- `docs/flows/canlab.md`: CAN 역분석
- `분석보고서.md`: wecar_scan 명령 분석
- `commands.json`: 46개 명령 목록
