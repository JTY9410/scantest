# BWSI BLE · 스캔↔위스캔 비교 · 이력 열람 설계

날짜: 2026-10-16. 위스캔 전용 BLE 단말기 인식, 스캔 통신기록과 위스캔 결과치 비교(AI 규칙 후보 초안), 스캔 이력 열람 UX.

## 결정

- 순서: A(BLE) → B(비교+AI) → C(이력)
- BWSI 광고 예: `bwsia846749d8a76` → 이름 접두사 `bwsi`(대소문자 무시)
- 기존 scantest Web Bluetooth·스캔·canlab 스택 확장. 레거시 Flutter의 write AND writeWithoutResponse 필수 조건은 이식하지 않음
- 비교 입력: 파일 업로드 또는 저장된 스캔(dataset) 선택 + 위스캔 결과치
- AI는 차이 분석 후 디코딩 규칙 후보(ScanLogic DRAFT)까지 만들고, DB 적용은 관리자 확정만

## A. BWSI BLE

- `obd-link.js` `NAME_PREFIXES`에 `bwsi`, `BWSI` 추가
- OBD 프로필 «위스캔 BLE(BWSI)» `namePrefix=bwsi`. UUID는 실기 전 비우거나 범용 힌트 — ATI 자동 탐색 우선
- 프로토콜: ELM327 호환 가정. ATI 실패 시 «모든 기기» 안내

## B. 스캔·위스캔 비교

- CAN 분석 탭 «스캔·위스캔 비교»(데이터입력분석과 분리)
- 스캔 기록을 적용 규칙으로 해석 → 위스캔 결과치와 신호별 차이 → AI 문제점 + ScanLogic DRAFT
- 비교 실행 기록 테이블에 dataset·diff·ai·logic_id 저장

## C. 이력

- `/admin/scans` 필터(차량·기간·bwsi 기기·테스터)
- 상세에서 PDF·결과·통신기록·비교 페이지 프리셀렉트

## 범위 밖

- 비-ELM BWSI 전용 프로토콜, Flutter 앱 BLE 변경, 스캔 직후 자동 비교 UX
