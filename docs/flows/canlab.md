# CAN 역분석과 운영 결과지

관리자가 진단기 트레이스(TRC)와 G-Scan 결과지(PDF)를 올리면, 결과지 값과 맞는 바이트·수식을 찾아 검증하고 디코딩 규칙으로 저장합니다. 적용된 규칙은 즉시 운영 결과지(웹 블루투스·모바일 앱 수집 데이터)에 쓰입니다. 화면은 관리자 메뉴 "CAN 분석"(`/admin/canlab/`)입니다.

## 흐름

| 사용자 행동 | route | service (`canlab/service.py`) | 저장 | 결과 |
| --- | --- | --- | --- | --- |
| 데이터 등록 | `POST /admin/canlab/datasets` | `upload_dataset` | 데이터셋, 감사기록 | 요약(형식, 요청·응답 수, DID, ECU, VIN 일부 가림). 같은 파일은 409, 4MB 초과는 413 |
| 결과지 값 읽기 | `POST .../pages/<n>/ocr` | `ocr_page` (`canlab/ai.py`) | 정답값(미확정) | AI 연결의 "CAN 분석" 기능이 켜져 있어야 함 |
| 결과지 값 직접 입력·확정 | `POST .../truths/add`, `.../truths` | `add_truths`, `update_truths` | 정답값 | "항목 \| 값 \| 단위" 한 줄씩 |
| 역산 실행 | `POST /admin/canlab/analysis` | `run_analysis` | 분석 기록, 규칙 | 신호별 확정/가설/UNKNOWN과 후보 5개 |
| 규칙 적용·해제·되돌리기 | `POST /admin/canlab/rules/<id>/activate`, `/retire` | `activate_rule`, `retire_rule` | 규칙, 감사기록 | 버전이 다르면 409 |
| 결과지 만들기 | `POST /admin/canlab/reports` | `create_report` | 결과지 | 적용 규칙으로 값·DTC 해석, 그래프 |
| AI 요약 | `POST /admin/canlab/reports/<id>/ai` | `summarize_with_ai` | 결과지 요약 | AI가 없으면 규칙 기반 요약 |
| 웹 블루투스 수집 | `GET/POST /admin/canlab/live` | `obd_config`, `upload_dataset`, `create_report` | 데이터셋(live_capture), 결과지(`report=1`) | 이 페이지에서 진단기 연결 → 여러 회 수집 → 저장 |
| 대시보드 빠른 점검 | `POST /admin/canlab/live/preview` | `preview_capture` | - | 1회 수집을 저장 없이 해석(VIN, ECU, DTC, 값). "결과지로 저장"은 `live`에 `report=1` |
| 앱 수집 | `GET /api/canCaptureRequests`, `POST /api/canCaptures` | `capture_requests`, `store_app_capture` | 데이터셋, 결과지 | `docs/flows/api.md` |

## 블루투스 진단기 연결 (웹)

관리자 대시보드의 "블루투스 진단기" 카드와 수집 페이지가 같은 모듈(`static/js/components/obd-link.js`)을 씁니다. 페이지마다 연결이 따로이므로 각 페이지에서 연결합니다.

- 찾기: 이름(OBD, ELM327, Vlink, vLinker, Veepeak, KONNWEI, Viecar, OBDLink 등) 또는 서비스(FFF0, FFE0, 18F0, OBDLink)로 거릅니다. 목록에 없으면 "모든 기기 보기"로 전체 기기를 고릅니다.
- 통신 채널: 프로필을 고르면 그 UUID를 먼저 쓰고, "자동 감지"면 쓰기·알림 특성 쌍마다 `ATI`를 보내 응답하는 채널을 씁니다. OBD 프로필이 없어도 연결됩니다.
- 초기화: `ATZ ATE0 ATL0 ATSP0`(또는 프로필 초기화 명령) 뒤 `ATH1 ATS1 ATCAF1`. 연결되면 진단기 이름, 펌웨어(`ATI`), 차량 전압(`ATRV`)을 표시합니다.
- 다시 연결: 연결이 끊기면 5초마다 다시 붙고, 수집 중이면 연결 후 같은 요청부터 이어 갑니다. "연결 끊기"를 누르면 멈춥니다.
- 자동 연결: 브라우저 보안상 처음 한 번은 버튼을 눌러 기기를 골라야 합니다. 이후 Chrome의 `getDevices`가 켜진 환경에서는 페이지를 열면 기억한 진단기에 자동으로 연결합니다.
- 수집 요청: 적용 규칙의 요청, 규칙이 없으면 첫 프로필의 조회 명령. 둘 다 없으면 연결만 되고 수집 버튼은 안내 문구를 보여 줍니다.
- 지원 브라우저: Chrome·Edge(데스크톱·Android). iPhone Safari, Firefox는 웹 블루투스가 없어 앱을 씁니다.

## 분석 엔진 (`canlab/engine/`)

1. `frames.py`: PCAN TRC와 앱·웹 수집 형식(`# WECAR-ELM 1`)을 CAN 프레임으로 읽습니다.
2. `isotp.py`, `uds.py`: 여러 프레임 응답을 합치고 요청(서비스 21/22, DTC 19)과 응답을 짝짓습니다.
3. `search.py`: 바이트 위치·길이·부호·엔디언·배율·오프셋 조합 중 정답값과 오차 안에서 맞는 해석을 찾습니다. 공개 참고 자료(`references.json`)와 같으면 가산점을 줍니다.
4. `validate.py`: 물리 범위, 시간에 따른 변화, 같은 점수의 경쟁 해석을 검사해 확정/가설/UNKNOWN을 정합니다.
5. `decode.py`: 적용된 규칙으로 값을 계산합니다.

## 자동 적용 규칙

규칙은 신호마다 하나만 적용되고 모든 차량 결과지에 함께 쓰입니다. 그래서 자동 적용은 보수적으로 합니다.

- "확정"이고 그 신호에 적용 중인 규칙이 없을 때만 새로 적용합니다.
- 적용 중인 규칙과 같은 수식이면 근거만 갱신합니다("유지").
- 적용 중인 규칙과 다른 수식은 자동으로 바꾸지 않고 "가설"로 남깁니다. 관리자가 규칙 화면에서 확인 후 적용합니다.
- 다른 신호에 적용 중인 바이트와 겹치는 수식은 적용하지 않습니다.
- 정답값(결과지)과 트레이스가 다른 시점에 기록됐다면 "검증만"으로 실행합니다. 규칙은 바뀌지 않습니다.
- 모든 버전은 남아 있어 이전 버전으로 되돌릴 수 있습니다.

## 실제 데이터 결과 (1차)

| 데이터 | 실행 | 결과 |
| --- | --- | --- |
| 기아 EV6 G-Scan TRC + 같은 시점 결과지 | 자동 적용 | 23개 중 21개 확정·적용(모두 `7E4 22 0101`). 모듈 온도 5, 외기 온도는 경쟁 해석이 있어 가설 |
| 그랜저 HEV G-Scan TRC + 다른 날짜 결과지 | 검증만 | 팩 전압·누적값·동작 시간은 UNKNOWN(값이 바뀜). 우연히 맞은 해석은 가설로 남음. SOH(`0105` b25~b26 × 0.1)는 참고 자료와 같지만 미적용 |
| 그랜저 HEV 위스캔 TRC | 결과지 | SOC, 팩 전압·전류, 셀 전압, 온도, 누적값, 동작 시간, 인버터 전압, 절연 저항 등 21개 값. 7개 ECU DTC 없음 |

## 남은 일 (2차)

- 차종별 규칙(현재는 모든 차량 공통). 그랜저 HEV의 셀 수·DID 구성은 EV6와 다를 수 있습니다.
- SOH, 표시 SOC: 같은 시점의 TRC와 결과지를 받거나 관리자가 규칙 화면에서 적용합니다.
- 결과지 PDF 내보내기(현재는 브라우저 인쇄).
