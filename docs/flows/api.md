# 모바일 앱 API

이전 Laravel 서버와 같은 경로·필드명(camelCase)·응답 형식을 유지합니다. 기준 문서는 `docs/legacy/laravel-api.json`, 호환 검사는 `tests/api/`입니다.

## 인증

- `POST /api/auth/login`이 액세스 토큰(JWT)과 리프레시 토큰을 돌려줍니다. 요청에는 `Authorization: Bearer <토큰>`(또는 `token` 파라미터)을 붙입니다.
- JWT가 없거나 맞지 않으면 `api_key` 파라미터로 인증합니다. 만료일·허용 IP를 검사합니다.
- `POST /api/auth/invalidateAllTokens`는 회원의 토큰 버전을 올려 이전 토큰을 모두 무효로 만듭니다.

## 흐름

| 앱 동작 | route | service | 저장 | 결과 |
| --- | --- | --- | --- | --- |
| 가입·SMS 인증·아이디 찾기·비밀번호 재설정 | `/api/auth/*` (`routes_auth.py`) | `accounts` | 회원, SMS 인증 기록 | 이전과 같은 JSON |
| 스캔 목록·등록·수정·삭제 | `/api/scans` | `scans.service` | 스캔, 스캔 코드 | 일반 회원은 본인 것만, 관리자는 전체 |
| 차량 정보 조회 | `POST /api/scans/getCarInfo` | `fetch_car_info` | - | 외부 API 결과 |
| 진단 코드 조회 | `/api/codes` | - | - | 검색·정렬·페이지 |
| 차량 불일치 신고 | `/api/carMismatchReports` | `reports` | 신고 | 본인 것만(관리자는 전체) |
| 앱 로그 | `/api/applogs` | `reports` | 앱 로그 | 본인 것만(관리자는 전체) |
| 블루투스 OBD2 설정 받기 (신규) | `GET /api/obdProfiles` | `obd.enabled_profiles` | - | 사용 중인 프로필 목록 (`docs/flows/obd.md`) |
| 연결한 진단기 받기·남기기·지우기 (신규) | `GET`·`POST /api/obdDevices`, `DELETE /api/obdDevices/<id>` | `obd.devices.list_for`·`remember`·`forget` | 진단기 기억 | 본인 것만. POST는 같은 연결 방식·이름이면 고쳐 200, 새로 만들면 201 `{message, data}` |
| CAN 수집 명령 받기 (신규) | `GET /api/canCaptureRequests` | `canlab.capture_requests` | - | 적용 규칙의 `{header, command}` 목록과 DTC·VIN 조회 명령 |
| CAN 수집 올리기 (신규) | `POST /api/canCaptures` | `canlab.store_app_capture` | 데이터셋, 결과지 | 201과 해석 값·DTC (`docs/flows/canlab.md`) |
| 앱 스캔 계획 (신규) | `GET /api/scanPlan?carNo=` | `scanner.lookup_car`, `build_plan(expand=True)` | 조회 캐시 | `{carNo, car, lookupError, steps, notes}`. 조회에 실패해도 공통 계획과 `lookupError` (`docs/flows/scanner.md`) |
| 앱 스캔 결과 올리기 (신규) | `POST /api/scanRuns` | `scanner.run_scan` | 통신 기록, 결과지, 스캔, 결과 PDF | 201 `{id, status, errors, pdfUrl}` |
| 고장코드 지우기 계획 발급 (신규) | `POST /api/scans/<id>/clearPlan` | `clear_service.issue` | dtc_clear_logs(issued), 감사기록 | 200 `{logId, token, expiresAt, targets, steps}`. 권한 없음 403, 차량번호 불일치·조건 미확인 400, 스캔 30분 지남 409 |
| 고장코드 지우기 실행 (신규) | `POST /api/scans/<id>/clear` | `clear_service.save` | dtc_clear_logs(결과), 감사기록 | 201 `{id, status, result}`. 토큰 없음/만료 401, 권한 없음 403, 허용되지 않은 명령 400 |
| LTE 단말기 스캔 계획 (신규) | `GET /api/telematics/plan` | `obd.telematics.plan_for` | 마지막 접속 시각 | 단말기 토큰(`Device`) 인증 (`docs/flows/telematics.md`) |
| LTE 단말기 결과 올리기 (신규) | `POST /api/telematics/captures` | `obd.telematics.receive` | 통신 기록, 결과지, 스캔 | 201 `{id, status, errors}` |

- 목록 API는 `search`(`필드:값||필드:연산자:값`), `order`(`필드:asc|desc`), `with`, `page`, `per_page` 파라미터를 이전과 같이 받습니다(`app/modules/api/listing.py`).
- 가입 시 회원 유형으로 관리자를 고를 수 없습니다(이전 서버의 권한 상승 허점 수정).
- 진단서 PDF(`/api/scans/<id>/pdf`)와 이메일(`/api/scans/<id>/email`)은 이전 서버처럼 성공 응답만 돌려줍니다. `?download=1`을 붙이면 PDF 파일을 내려받습니다(본인 스캔만, `scanRuns`의 `pdfUrl`).
- `POST /api/scanRuns` 본문: `carNo`, `car`(scanPlan이 준 값), `steps`(계획 단계 + `reply`·`error`·`tMs`), `transport`(`ble`·`serial`·`wifi`), `device`, `dialect`(`elm327`·`stn`·`slcan`, 그 밖의 값은 비움), `lookupError`, `clientError`.
- `POST /api/obdDevices` 본문: `transport`(`ble`·`classic`·`wifi`, 필수), `name`(필수, 100자 이하), `dialect`, `chip`, `version`, `serviceUuid`·`writeUuid`·`notifyUuid`(4자리 또는 128비트), `protocol`(ATDPN 번호 한 글자), `settings`(`bitrate`·`baud`·`host`·`port`만 저장). 맞지 않으면 422.
- `POST /api/canCaptures` 본문: `vehicle`(필수, 100자 이하), `deviceName`(선택), `exchanges`(필수, 1~2000개의 `{header, command, reply}`; header·command는 16진수, reply는 진단기가 돌려준 줄 그대로). 응답이 하나도 없으면 400입니다.
- 앱 저장소(`evolsraet/wecar_scan`)가 실제로 호출하는 경로는 모두 이 서버에 있습니다. 앱 저장소의 `API_SPECIFICATION.md`는 앱이 쓰지 않는 다른 경로를 적고 있으니 기준으로 삼지 않습니다.
