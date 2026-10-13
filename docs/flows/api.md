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

- 목록 API는 `search`(`필드:값||필드:연산자:값`), `order`(`필드:asc|desc`), `with`, `page`, `per_page` 파라미터를 이전과 같이 받습니다(`app/modules/api/listing.py`).
- 가입 시 회원 유형으로 관리자를 고를 수 없습니다(이전 서버의 권한 상승 허점 수정).
- 진단서 PDF(`/api/scans/<id>/pdf`)와 이메일(`/api/scans/<id>/email`)은 이전 서버처럼 성공 응답만 돌려줍니다.
