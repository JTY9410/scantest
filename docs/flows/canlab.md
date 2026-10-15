# CAN 역분석과 운영 결과지

위스캔(기준 진단기)으로 스캔한 통신 기록과 최종값, 리버스한 TRC를 비교해 위스캔 결과를 내는 명령·수식·분석 코드를 찾고, 관리자가 고른 항목을 "스캔 로직"으로 스캔하기에 적용합니다. 적용된 수식(디코딩 규칙)은 운영 결과지(웹 블루투스·모바일 앱 수집 데이터)에도 쓰입니다. 화면은 관리자 메뉴 "CAN 분석"(`/admin/canlab/`)이고, 탭은 개요 · 위스캔값 입력 · 리버스데이터 입력 · 역산 분석 · 디코딩 규칙입니다.

## 흐름

| 사용자 행동 | route | service (`canlab/service.py`) | 저장 | 결과 |
| --- | --- | --- | --- | --- |
| 위스캔값 입력 | `POST /admin/canlab/wescan` | `upload_wescan` (`values_file_text`) | 데이터셋(`wecan_trc`), 최종값(정답값), 감사기록 | 통신 기록(.trc/.txt/.log)과 최종값(붙여넣기 또는 .txt/.csv/.tsv, "항목 \| 값 \| 단위"). 숫자 최종값이 없으면 400. 명령·응답 추출 |
| 리버스데이터 입력 | `POST /admin/canlab/reverse` | `upload_dataset` | 데이터셋(`gscan_trc`) | PCAN TRC. 명령·응답 추출 |
| 명령·산출 결과 추출 | (등록할 때) | `extract_commands` | 데이터셋 요약 `commands` | 명령(주소+요청)마다 서비스, DID, 횟수, 긍정·부정 응답, 응답 예시, 스캔 로직에 넣을 수 있는지(`sendable`: 읽기 서비스, 11비트 주소) |
| 기타 데이터 등록 | `POST /admin/canlab/datasets` | `upload_dataset` | 데이터셋, 감사기록 | 결과지 PDF 등. 같은 파일은 409, 4MB 초과는 413 |
| 결과지 값 읽기 | `POST .../pages/<n>/ocr` | `ocr_page` (`canlab/ai.py`) | 정답값(미확정) | AI 연결의 "CAN 분석" 기능이 켜져 있어야 함 |
| 정답값 직접 입력·확정 | `POST .../truths/add`, `.../truths` | `add_truths`, `update_truths` | 정답값 | "항목 \| 값 \| 단위" 한 줄씩 |
| 역산 분석 | `POST /admin/canlab/analysis` | `run_analysis`, `compare_commands`, `decoder_code` | 분석 기록 | 명령 비교(공통·위스캔에만·리버스에만), 신호별 확정/가설/UNKNOWN, 수식, Python 디코더 코드(보여 주기만 함). 규칙은 바뀌지 않음 |
| 적용(변경 전후 비교) | `POST /admin/canlab/analysis/<id>/apply` | `draft_logic` | 스캔 로직(적용 전) | 명령·수식 항목마다 변경 전/변경 후/변화와 기본안 |
| AI 최적안 | `POST /admin/canlab/logics/<id>/advise` | `advise_logic` (`ai.advise_logic`) | 스캔 로직 `ai_advice` | 항목별 추천과 이유. AI가 없거나 실패하면 규칙 기반 기본안 |
| 적용 확정 | `POST /admin/canlab/logics/<id>/confirm` | `confirm_logic` | 스캔 로직(적용 중), 규칙, 감사기록 | 고른 항목만 적용. 이전 로직은 "이전 버전". 버전이 다르면 409 |
| 로직 되돌리기 | `POST /admin/canlab/logics/<id>/restore` | `restore_logic` | 스캔 로직, 규칙 | 그 버전의 명령과 수식(규칙 버전)으로 되돌림 |
| 규칙 적용·해제·되돌리기 | `POST /admin/canlab/rules/<id>/activate`, `/retire` | `activate_rule`, `retire_rule` | 규칙, 감사기록 | 버전이 다르면 409 |
| 결과지 만들기 | `POST /admin/canlab/reports` | `create_report` | 결과지 | 적용 규칙으로 값·DTC 해석, 그래프 |
| AI 요약 | `POST /admin/canlab/reports/<id>/ai` | `summarize_with_ai` | 결과지 요약 | AI가 없으면 규칙 기반 요약 |
| 웹 블루투스 수집 | `GET/POST /admin/canlab/live` | `obd_config`, `upload_dataset`, `create_report` | 데이터셋(live_capture), 결과지(`report=1`) | 이 페이지에서 진단기 연결 → 여러 회 수집 → 저장 |
| 대시보드 빠른 점검 | `POST /admin/canlab/live/preview` | `preview_capture` | - | 1회 수집을 저장 없이 해석(VIN, ECU, DTC, 값). "결과지로 저장"은 `live`에 `report=1` |
| 앱 수집 | `GET /api/canCaptureRequests`, `POST /api/canCaptures` | `capture_requests`, `store_app_capture` | 데이터셋, 결과지 | `docs/flows/api.md` |
| 스캔하기·LTE 단말기 | `/admin/scan/run`, `/api/telematics/captures` | `scanner.run_scan` | 데이터셋(`live_capture`, `lte`), 결과지, 스캔 | `docs/flows/scanner.md`, `docs/flows/telematics.md` |

## 블루투스 진단기 연결 (웹)

관리자 대시보드의 "블루투스 진단기" 카드와 수집 페이지가 같은 모듈(`static/js/components/obd-link.js`)을 씁니다. 페이지마다 연결이 따로이므로 각 페이지에서 연결합니다.

- 찾기: 이름(OBD, ELM327, Vlink, vLinker, Veepeak, KONNWEI, Viecar, OBDLink, Carista, iCar, Vgate, LELink, BlueDriver 등) 또는 서비스(FFF0, FFE0, 18F0, AE30, BEEF, Nordic UART, OBDLink)로 거릅니다. 목록에 없으면 "모든 기기 보기"로 전체 기기를 고릅니다.
- 블루투스 클래식·USB: "블루투스 클래식·USB" 버튼은 Web Serial로 페어링된 SPP 포트나 USB 진단기에 연결합니다(`SerialLink`).
- 통신 채널: 프로필이나 기억한 진단기의 UUID를 먼저 쓰고, "자동 감지"면 쓰기·알림 특성 쌍마다 `ATI`(slcan은 `V`)를 보내 응답하는 채널을 씁니다. OBD 프로필이 없어도 연결됩니다.
- 명령 체계: ELM327·STN·slcan을 가려 드라이버(`obd-driver.js`)를 고릅니다(`docs/flows/obd.md`의 "진단기 명령 체계"). 패널에 명령 체계를 표시합니다.
- 초기화: ELM327·STN은 `ATZ ATE0 ATL0 ATSP0`(또는 프로필 초기화 명령, 기억한 `ATSPA<n>`) 뒤 `ATH1 ATS1 ATCAF1 ATAT1`, slcan은 `C V Z0` 뒤 첫 요청 때 `S<속도> O`. 연결되면 진단기 이름, 펌웨어(`ATI`·`STDI`·`V`), 차량 전압(`ATRV`, slcan은 없음)을 표시합니다.
- 기억: 연결한 진단기는 이 브라우저와 서버 계정에 남고, 패널의 "기억한 진단기"에서 지웁니다(`docs/flows/obd.md`의 "진단기 기억").
- 다시 연결: 연결이 끊기면 5초마다 다시 붙고, 수집 중이면 연결 후 같은 요청부터 이어 갑니다. "연결 끊기"를 누르면 멈춥니다.
- 자동 연결: 브라우저 보안상 처음 한 번은 버튼을 눌러 기기를 골라야 합니다. 이후 Chrome의 `getDevices`가 켜진 환경에서는 페이지를 열면 기억한 진단기에 자동으로 연결합니다.
- 수집 요청: 적용 중 스캔 로직의 명령과 적용 규칙의 요청, 둘 다 없으면 첫 프로필의 조회 명령. 둘 다 없으면 연결만 되고 수집 버튼은 안내 문구를 보여 줍니다.
- 지원 브라우저: Chrome·Edge(데스크톱·Android). iPhone Safari, Firefox는 웹 블루투스가 없어 앱을 씁니다.

## 분석 엔진 (`canlab/engine/`)

1. `frames.py`: PCAN TRC와 앱·웹 수집 형식(`# WECAR-ELM 1`)을 CAN 프레임으로 읽습니다.
2. `isotp.py`, `uds.py`: 여러 프레임 응답을 합치고 요청(서비스 21/22, DTC 19)과 응답을 짝짓습니다.
3. `search.py`: 바이트 위치·길이·부호·엔디언·배율·오프셋 조합 중 정답값과 오차 안에서 맞는 해석을 찾습니다. 공개 참고 자료(`references.json`)와 같으면 가산점을 줍니다.
4. `validate.py`: 물리 범위, 시간에 따른 변화, 같은 점수의 경쟁 해석을 검사해 확정/가설/UNKNOWN을 정합니다.
5. `decode.py`: 적용된 규칙으로 값을 계산합니다.

## 스캔 로직 적용

스캔 로직은 스캔하기에 보낼 명령(`commands`)과 값을 계산할 수식(`rules`, 디코딩 규칙 버전)의 묶음입니다(`scan_logics`). 적용 중 로직은 하나이고, 역산 분석은 규칙을 바꾸지 않습니다. 관리자가 "적용"에서 확인한 항목만 바뀝니다. AI는 추천만 하고 확정은 관리자가 합니다.

- 변경 전: 적용 중 로직의 명령과 적용 중 규칙. 변경 후: 위스캔 기록의 `sendable` 명령(공통·위스캔에만)과 수식이 쓰는 `22 DID` 요청, 분석에서 찾은 수식.
- 기본안: 같으면 변경 전 유지, "확정" 수식은 변경 후, "가설" 수식은 변경 전 유지(없으면 빼기), 사라진 항목은 변경 전 유지. 리버스에만 있는 명령은 넣지 않습니다.
- 다른 신호에 적용 중인 바이트와 겹치는 수식은 "가설"로 남습니다.
- 같은 수식이면 기존 규칙 버전을 그대로 쓰고, 다른 수식이면 새 버전을 만들어 적용합니다. 모든 버전은 남아 되돌릴 수 있습니다.
- AI에는 항목·수식·상태만 보내고 바이트 배치(layout)·근거·VIN은 보내지 않습니다.
- 스캔하기는 적용 중 로직의 명령을 "스캔 로직: …" 단계로 보내고, 결과에서 로직 명령이 성공하지 않았거나 로직 수식으로 값을 읽지 못하면 "로직 문제"로 기록하고 결과 화면에 팝업으로 보여 줍니다(`docs/flows/scanner.md`).

## 초기화

`flask canlab reset`은 CAN 분석 데이터(데이터셋, 정답값, 분석 기록, 규칙, 스캔 로직, 운영 결과지) 건수만 보여 주고, `--yes`를 붙이면 모두 지웁니다. 스캔 기록은 남고, 스캔 결과 화면의 결과지 링크는 "결과지 삭제됨"으로 바뀝니다.

## 남은 일

- 차종별 규칙(현재는 모든 차량 공통). 차종마다 셀 수·DID 구성이 다를 수 있습니다.
- 운영 결과지 PDF 내보내기(현재는 브라우저 인쇄).
