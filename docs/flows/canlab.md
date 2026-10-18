# CAN 역분석과 운영 결과지

차량번호로 차종을 정하고, 위스캔(기준 진단기)으로 스캔한 통신기록·최종값과 리버스한 TRC를 비교해 위스캔 결과를 내는 명령·수식·분석 코드를 찾습니다. 관리자가 고른 항목만 "디코딩 규칙"(스캔 로직 + 규칙 버전)으로 그 차종에 적용하고, 같은 제조사로 확대할 수 있습니다. 적용된 규칙은 스캔하기와 운영 결과지(웹 블루투스·모바일 앱 수집 데이터)에도 쓰입니다. 화면은 관리자 메뉴 "CAN 분석"(`/admin/canlab/`)이고, 탭은 개요 · 데이터입력분석 · 스캔·위스캔 비교 · 디코딩 규칙입니다.

## 흐름

| 사용자 행동 | route | service (`canlab/service.py`) | 저장 | 결과 |
| --- | --- | --- | --- | --- |
| 차량 조회 | `POST /admin/scan/lookup` | `scanner.lookup_car` (`car_info.lookup`) | 차량정보 캐시 | 차량검색과 같은 조회. 화면에 차량번호·제조사·모델·세부모델·등급·세부등급(연식)·최초등록일을 보여 줌. 차대번호는 보여 주지 않음 |
| 올리고 추출하기 | `POST /admin/canlab/analysis` | `ingest` (`lookup_vehicle`, `upload_wescan`, `upload_dataset`) | 데이터셋(`wecan_trc`, `gscan_trc`, 범위 `maker`·`model`, 요약 `car`), 최종값, 감사기록 | 차량번호 조회 실패·제조사/모델 없음이면 오류. 리버스 파일을 먼저 검사해 일부만 저장되는 일을 줄임. 이미 올린 파일은 그 데이터를 다시 씀. 최종값은 붙여넣기, .txt/.csv/.tsv, 결과지 PDF(글자 → 없으면 AI 판독) |
| 최종값 확인 | `GET/POST /admin/canlab/analysis/pending/<위스캔 id>?reverse=…` | `update_truths` → `run_analysis` | 최종값 | PDF에서 읽은 미확인 값이 있으면 이 화면을 거침. "확정하고 분석"은 체크한 값만 씀 |
| 분석(3단계) | (추출하기·확정 뒤 자동) | `run_analysis` (`references.hypotheses`, `interpret_reverse`, `compare_commands`, `search`, `judge`) | 분석 기록(범위, 차량, 해석) | 1) 리버스 명령·결과를 참고자료로 해석 2) 위스캔 통신기록과 명령·응답 구조 대조 3) 위스캔 최종값과 일치하는 수식·명령. 규칙은 바뀌지 않음 |
| 디코딩 규칙 후보 만들기 | `POST /admin/canlab/analysis/<id>/apply` | `draft_logic` (`backtest`) | 스캔 로직(적용 전, 차종 범위) | 항목마다 변경 전/후, 같은 차종 과거 데이터 비교. 후보가 더 나쁘면 기본안을 "변경 전 유지"로 |
| 스캔·위스캔 비교 | `GET/POST /admin/canlab/compare` | `start_compare` → `compare_scan_wescan` (`_compare_diff`, `run_scan_truth_analysis`, `draft_logic`, `advise_logic`) | 비교 기록(`scan_wescan_compares`), 분석 기록, 스캔 로직(DRAFT) | 저장된 스캔 통신기록 또는 파일 + 위스캔 결과치. PDF에서 읽은 미확인 값이 있으면 데이터 화면에서 확인한 값만으로 비교를 이어 감. 적용 규칙으로 읽은 값과 결과치를 신호별로 비교하고 AI 최적안 DRAFT를 만듦. 규칙은 적용 확정 전까지 바뀌지 않음. 데이터입력분석(위스캔 통신 vs 리버스)과 역할이 다름. `?dataset_id=`·`scan_id`로 프리셀렉트 |
| 비교 상세 | `GET /admin/canlab/compare/<id>` | `get_compare` | - | 차이표, AI 요약, 통신기록·역산·규칙 후보 링크 |
| AI 최적안 | `POST /admin/canlab/logics/<id>/advise` | `advise_logic` | 스캔 로직 `ai_advice` | 추천만. AI가 없으면 규칙 기반 기본안 |
| 적용 확정 | `POST /admin/canlab/logics/<id>/confirm` | `confirm_logic` | 스캔 로직(적용 중), 규칙(그 범위), 변경 이력, 감사기록 | 고른 항목만 그 범위에 적용. 버전이 다르면 409 |
| 같은 제조사로 확대 | `POST /admin/canlab/logics/<id>/expand` | `draft_expansion` | 스캔 로직(적용 전, 제조사 범위) | 적용 중 차종 로직만. 그 제조사 데이터로 과거 비교 |
| 되돌리기 | `POST /admin/canlab/changes/<id>/rollback` | `rollback_change` | 규칙, 스캔 로직, 변경 이력 | 그 범위만 변경 전 상태로. 이미 되돌린 변경은 409 |
| 규칙 적용·해제 | `POST /admin/canlab/rules/<id>/activate`, `/retire` | `activate_rule`, `retire_rule` | 규칙, 변경 이력, 감사기록 | 같은 범위 안에서만 바뀜. 버전이 다르면 409 |
| 참고자료 OBDb 동기화 | `POST /admin/canlab/references/sync` | `references.sync_obdb` | 참고자료(승인) | OBDb 공개 저장소(CC BY-SA 4.0) 차종 정의. 추가 저장소는 이름·모델 키워드 필요 |
| 참고자료 주소 등록 | `POST /admin/canlab/references/url` | `references.register_url` (`ai.extract_references`) | 참고자료(검토 대기) | https 공개 주소만(내부·사설 IP, 계정, 다른 포트 거부, 이동할 때마다 다시 검사), 1MB·10초, 글자 자료만. AI 초안은 코드에서 검사(신호 키, 16진수 주소·DID, 바이트 0~255, 폭 1·2·4, 유한한 배율) |
| 참고자료 승인·반려·다시 정리 | `POST /admin/canlab/references/<id>/approve`, `/reject`, `/retry` | `references.review`, `reextract` | 참고자료 | 승인한 자료만 분석에 씀. 버전이 다르면 409 |
| 기타 데이터 등록 | `POST /admin/canlab/datasets` | `upload_dataset` | 데이터셋, 감사기록 | 결과지 PDF 등. 같은 파일은 409, 4MB 초과는 413 |
| 결과지 값 읽기·정답값 입력 | `POST .../pages/<n>/ocr`, `.../truths/add`, `.../truths` | `ocr_page`, `add_truths`, `update_truths` | 정답값 | 데이터 화면 |
| 결과지 만들기 | `POST /admin/canlab/reports` | `create_report` | 결과지 | 데이터셋 범위(차종)의 규칙으로 값·DTC 해석 |
| AI 요약 | `POST /admin/canlab/reports/<id>/ai` | `summarize_with_ai` | 결과지 요약 | AI가 없으면 규칙 기반 요약 |
| 웹 블루투스 수집 | `GET/POST /admin/canlab/live` | `obd_config`, `upload_dataset`, `create_report` | 데이터셋(live_capture), 결과지(`report=1`) | 차량 구분 없는 요청 목록 |
| 대시보드 빠른 점검 | `POST /admin/canlab/live/preview` | `preview_capture` | - | 저장 없이 해석 |
| 앱 수집 | `GET /api/canCaptureRequests[?carNo=]`, `POST /api/canCaptures` | `capture_requests(car)`, `store_app_capture` | 데이터셋, 결과지 | `carNo`를 주면 그 차종 규칙. 조회 실패면 차량 구분 없이. 응답 형식은 같음 |
| 스캔하기·LTE 단말기 | `/admin/scan/run`, `/api/telematics/captures` | `scanner.run_scan` | 데이터셋, 결과지, 스캔, 문제 로그 | `docs/flows/scanner.md`, `docs/flows/telematics.md` |

## 적용 범위

규칙(`decode_rules`)과 스캔 로직(`scan_logics`)에는 범위(`maker`, `model`)가 있습니다. 둘 다 있으면 차종, 제조사만 있으면 제조사, 둘 다 없으면 공통입니다. 범위마다 신호별 적용 규칙과 적용 로직은 하나입니다(부분 고유 인덱스).

- 차량이 있을 때: 신호마다 차종 규칙 → 제조사 규칙 → 공통 규칙 순서로 고르고(`rules_for`), 로직도 같은 순서(`active_logic`). 비교는 공백을 빼고 대문자로 합니다.
- 차량 정보가 없을 때(실시간 수집, 대시보드, `carNo` 없는 앱 요청): 공통 규칙을 먼저, 공통이 없는 신호는 가장 최근에 적용한 범위 규칙을 씁니다.
- 분석·후보는 차종 범위로 만들고, "같은 제조사로 확대"로 제조사 범위 후보를 만듭니다. 확대해도 차종 규칙이 있는 차종은 차종 규칙을 먼저 씁니다.

## 분석 3단계

1. 리버스 해석: 리버스 기록의 22 DID 응답을 참고 색인(`references.hypotheses(car)`: 기본 참고 해석 `references.json` + 이 차종 OBDb 정의 + 차량에 맞는 승인 참고자료)으로 해석합니다. 물리 범위 밖 값은 뺍니다.
2. 통신기록 대조: 위스캔·리버스 명령을 공통/위스캔에만/리버스에만으로 나누고, 공통 22 명령은 응답 길이와 값이 바뀌는 바이트를 나란히 보여 줍니다.
3. 최종값 일치: 위스캔 최종값과 오차 안에서 맞는 바이트·수식을 찾고(참고 색인과 같으면 가산점), 검증으로 확정/가설/UNKNOWN을 정합니다. 그 수식과 명령이 규칙 후보가 됩니다.

## 디코딩 규칙 후보와 과거 데이터 비교

- 변경 전: 이 차종에 지금 쓰는 로직 명령과 규칙(`rules_for`). 변경 후: 위스캔 기록의 `sendable` 명령과 수식이 쓰는 22 DID 요청, 분석 수식.
- 기본안: 같으면 유지, "확정" 수식은 변경 후, "가설"은 변경 전 유지(없으면 빼기). 리버스에만 있는 명령은 넣지 않습니다.
- 과거 비교(`backtest`): 같은 범위의 통신기록(최대 30개)을 변경 전·후 수식으로 다시 읽어, 최종값이 있으면 일치 건수, 없으면 물리 범위 안에서 읽힌 건수를 비교합니다(개선/악화/같음/과거 데이터 없음).
- AI에는 항목·수식·상태만 보내고 바이트 배치·근거·VIN은 보내지 않습니다. 확정은 관리자가 합니다.

## 변경 이력·문제 로그·되돌리기

- 변경 이력(`rule_changes`): 적용·확대·규칙 적용·해제·되돌리기마다 그 범위의 변경 전·후 상태(로직 id·버전, 규칙 id·버전·수식)와 과거 비교 결과를 남깁니다. 다른 기록이 지워져도 함께 지워지지 않습니다.
- 되돌리기: 변경 전 상태와 다른 그 범위의 적용 규칙·로직을 내리고 변경 전 규칙·로직을 다시 적용합니다. 다른 범위는 그대로이며, 되돌린 일도 이력에 남습니다.
- 문제 로그(`rule_incidents`): 스캔에서 적용 로직의 명령이 응답하지 않았거나 수식으로 값을 읽지 못하면 스캔 id·범위·로직·명령·내용을 남깁니다. 디코딩 규칙 화면에서 봅니다.

## 참고자료 DB (`can_references`)

- OBDb: `engine/obdb.py`의 `convert`(스크립트 `scripts/import_obdb.py`와 같음)로 BMS(7E4) 22 DID 바이트 단위 신호만 옮겨 승인 상태로 저장합니다. 출처·라이선스(CC-BY-SA-4.0)를 함께 남깁니다.
- URL: 본문 글자만 저장(최대 200,000자)하고 AI가 해석 항목 초안을 만듭니다. AI 연결이 없거나 실패하면 이유를 남기고 "AI로 다시 정리"할 수 있습니다.
- 차량 맞춤: 키워드가 있으면 모델·세부모델에 키워드가 있어야, 없으면 제조사·모델이 맞아야 그 차량 분석에 씁니다. 제조사·모델·키워드가 모두 없으면 모든 차량에 씁니다.

## 분석 엔진 (`canlab/engine/`)

1. `frames.py`: PCAN TRC와 앱·웹 수집 형식(`# WECAR-ELM 1`)을 CAN 프레임으로 읽습니다.
2. `isotp.py`, `uds.py`: 여러 프레임 응답을 합치고 요청(서비스 21/22, DTC 19)과 응답을 짝짓습니다.
3. `search.py`: 바이트 위치·길이·부호·엔디언·배율·오프셋 조합 중 정답값과 오차 안에서 맞는 해석을 찾습니다. 참고 색인과 같으면 가산점을 줍니다.
4. `validate.py`: 물리 범위, 시간에 따른 변화, 같은 점수의 경쟁 해석을 검사해 확정/가설/UNKNOWN을 정합니다.
5. `decode.py`: 적용된 규칙으로 값을 계산합니다.

## 블루투스 진단기 연결 (웹)

관리자 대시보드의 "블루투스 진단기" 카드와 수집 페이지가 같은 모듈(`static/js/components/obd-link.js`)을 씁니다. 연결·명령 체계·기억·다시 연결은 `docs/flows/obd.md`를 봅니다. 수집 요청은 적용 로직의 명령과 적용 규칙의 요청(차량 구분 없음), 둘 다 없으면 첫 프로필의 조회 명령입니다. 지원 브라우저는 Chrome·Edge(데스크톱·Android)입니다.

## 초기화

`flask canlab reset`은 CAN 분석 데이터(비교 기록, 데이터셋, 정답값, 분석 기록, 규칙, 스캔 로직, 변경 이력, 문제 로그, 운영 결과지) 건수만 보여 주고, `--yes`를 붙이면 모두 지웁니다. 참고자료 DB와 스캔 기록은 남습니다.

## 남은 일

- 운영 결과지 PDF 내보내기(현재는 브라우저 인쇄).
