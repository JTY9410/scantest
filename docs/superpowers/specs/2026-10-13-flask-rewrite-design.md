# WecarScan Flask 전환 설계

- 작성일: 2026-10-13
- 기준: `pro.md`(기술개발 정의서), 사용자 결정 사항(아래)
- 대상: 기존 Laravel 11 + Filament 백엔드(`main` 브랜치, 커밋 `fdc73f8`)를 Flask로 대체

## 1. 확정된 결정

| 항목 | 결정 |
|---|---|
| 모바일 API | 21개 엔드포인트의 주소·요청·응답 형식 유지. 앱 수정 없이 동작 |
| DB | PostgreSQL 16 (Alembic 관리) |
| 화면 CSS | Tailwind CSS (ADR 0001) |
| 관리자 계정 | 코드에 넣지 않음. `flask create-admin`으로 일회성 등록 (로컬: `wecar`) |
| 회원관리 | 목록·검색·필터, 상세, 정보 수정 |
| 기타 관리 화면 | 회사·진단코드 등록/수정, 스캔·활동기록·앱로그·불일치신고 조회 |
| 데이터 범위 | 불일치신고·앱로그 API는 일반 회원은 본인 것만, 관리자는 전체 |
| MFA | TOTP 선택 등록. 등록한 관리자는 로그인 시 OTP 필수 |
| AI | 'AI 연결' 관리 화면까지 (RAG 제외) |
| Laravel 코드 | 저장소에서 제거 (Git 이력에 보존) |

## 2. 기존 시스템 오류와 처리

| 문제 | 처리 |
|---|---|
| `ManufacturersController` 미존재 라우트 | 구현이 없어 제외 |
| `Code` 모델 fillable(`cause`,`action`)과 컬럼(`root_cause`,`howto_fix1~3`) 불일치 | 실제 컬럼 기준으로 통일 |
| 로그에 비밀번호 길이·SMS 코드·전화번호 기록 | 기록하지 않음 |
| 차량정보 API 키·개발 URL 하드코딩 | `CAR_INFO_API_URL`, `CAR_INFO_API_KEY` 환경설정 |
| 관리자 화면이 `APP_KEY`·`JWT_SECRET`을 `.env`에 기록 | 제거. 비밀값은 배포 환경변수로만 주입 |
| SMS 인증번호 `1111` 고정 | `SMS_DEV_CODE` 설정 시에만 사용(운영 기본 비활성). 미설정 시 503 |
| 불일치신고·앱로그 전체 공개 | 본인 데이터만 (관리자 제외) |
| 목록 `per_page` 무제한 | 상한 100 |
| 검색·정렬 필드 무제한 | 모델 컬럼 화이트리스트 |

미구현이던 PDF 생성·이메일 전송은 기존 응답을 그대로 유지한다(실제 발송은 별도 요구사항).

## 3. 구조

```
app/
  __init__.py          create_app, 보안 헤더, 오류 처리
  config.py            환경 설정 (Dev/Test/Prod)
  extensions.py        db, migrate, login_manager, csrf, limiter
  cli.py               create-admin
  core/                공용: 시간 직렬화, 암호화, 감사기록, 페이지네이션
  modules/
    auth/              관리자 로그인·MFA (route/service/forms)
    accounts/          User·Company·RefreshToken·SmsVerification 모델, 비밀번호·토큰 서비스
    api/               모바일 API: JWT, camelCase 변환, 공통 목록 질의, 엔드포인트
    scans/             Scan·ScanCode·Code 모델, 권한 범위 서비스
    reports/           CarMismatchReport·Applog 모델
    members/           관리자 회원관리
    catalog/           관리자 회사·진단코드
    monitoring/        관리자 스캔·활동·앱로그·불일치신고 조회
    admin/             대시보드, AI 연결
  templates/ static/
migrations/ tests/ docs/flows/ docs/adr/
```

## 4. 데이터 모델

시각 컬럼은 `TIMESTAMPTZ`(UTC 저장). API 직렬화는 Laravel과 같은 `YYYY-MM-DDTHH:MM:SS.ffffffZ`.

| 테이블 | 주요 컬럼 | 제약·삭제 정책 |
|---|---|---|
| companies | code(UQ), name, deleted_at | soft delete |
| users | company_id, type(admin/tester/owner), mobile(숫자만), biz_no(숫자만), tid(UQ), name, email(UQ, null 허용), password, token_version, api_key(UQ), api_host, api_expires_at, totp_secret_enc, version, deleted_at | company FK SET NULL, soft delete, `version` 낙관적 잠금 |
| refresh_tokens | user_id, token(UQ 64), expires_at, deleted_at | user FK CASCADE |
| jwt_blocklist | jti(PK), expires_at | 로그아웃한 액세스 토큰 |
| sms_verifications | mobile, sms_code, sms_code_key, expires_at, is_verified | (mobile, sms_code_key) 인덱스 |
| codes | type(ev/ice), code, unit_name, unit_type, desc, detail_desc, root_cause, howto_fix1~3, deleted_at | (type, code) 인덱스 |
| scans | type, device_type, device_uid, owner_id, tester_id, company_id, scan_vin, car_no, car_vin, car_maker, car_model, car_submodel, car_cc, car_year, car_fuel, car_distance, car_battery_capacity/discharge/charge(NUMERIC 10,2), raw(JSON), bms_data(JSON), deleted_at | owner·company FK SET NULL, tester FK RESTRICT (이력 보존) |
| scan_codes | type, scan_id, code_id, deleted_at | scan FK CASCADE, code FK RESTRICT |
| car_mismatch_reports | user_id, car_no, api_vin, scan_vin, deleted_at | user FK RESTRICT |
| applogs | timestamp(µs), user_id, type, message(2000), desc | user FK SET NULL |
| activities | user_id, ip, relation, relation_type, relation_id, changes(JSON), message | 감사기록. 비밀값 제외. user FK SET NULL |
| ai_connections | provider(UQ), model, features(JSON), monthly_budget(NUMERIC 12,2), monthly_token_limit, key_enc, key_last4, status, last_tested_at, last_test_message, version | 키는 Fernet 암호화 |

## 5. 모바일 API 호환 규칙

- 요청: 쿼리·본문 키를 snake_case로 변환(Laravel `Str::snake`와 동일, 중첩 포함). 응답: 모든 키를 camelCase로 변환(`Str::camel`과 동일, 중첩 포함).
- 인증: `Authorization: Bearer <JWT>`(또는 `token` 파라미터). HS256, `sub`=회원 id, `token_version` 클레임, 만료 `JWT_TTL`분(기본 60). 실패 시 `api_key` 파라미터 → 만료 401, IP 불허 403. 둘 다 실패 401 `인증이 필요합니다.`
- 리프레시 토큰: 64자 난수, `JWT_REFRESH_TTL`분(기본 20160). 갱신 시 기존 토큰 soft delete.
- 목록: `page`, `per_page`(기본 15, 상한 100), `search=field:value||field:op:value`(op: `=,!=,<>,>,>=,<,<=,like,in`), `order=field:asc|desc||...`, `with=관계,...`. 응답 `{data, meta:{currentPage,lastPage,perPage,total}}`. 사용자 정렬 뒤에 `created_at desc`.
- 오류: 검증 422 `{message: 첫 오류 [(and N more error(s))], errors:{field:[...]}}`, 404 `해당 항목을 찾을 수 없습니다.`, 403 `권한이 없습니다.`
- 스캔 권한: admin 전체, owner는 `owner_id`=본인, tester는 `tester_id`=본인. owner 생성 403, tester 생성 시 tester_id=본인·owner_id=null. 삭제는 admin 또는 본인 tester.
- 기존 bcrypt(`$2y$`) 해시를 검증하고, 로그인 성공 시 scrypt로 재해시.

## 6. 관리자 웹

- 로그인: `tid`+비밀번호, type=admin만. 성공 시 세션 재발급. 속도 제한 5회/분(IP+아이디). MFA 등록자는 OTP 단계 추가.
- 회원관리: 검색(아이디·이름·휴대전화·이메일), 필터(유형·회사·탈퇴 포함), 정렬, 페이지(상한 100). 상세: 기본 정보와 관련 기록 건수. 수정: 이름·유형·회사·휴대전화·이메일·사업자번호, `version` 충돌 시 재시도 안내, 감사기록.
- AI 연결: 공급자(openai/anthropic/gemini)별 1건. 모델·기능 토글(설명/검색/초안)·월 예산·월 토큰 상한. 키 저장 시 Fernet 암호화(`ENCRYPTION_KEY`, DB와 분리), 화면에는 끝 4자리. 연결 테스트(모델 조회 API, 10초 타임아웃), 키 교체·폐기. 모든 변경·테스트 감사기록(키 제외).
- 보안: CSRF, HttpOnly·SameSite=Lax·(운영)Secure 쿠키, CSP·X-Frame-Options·nosniff·Referrer-Policy·(운영)HSTS, 관리자·API 응답 `Cache-Control: no-store`.

## 7. UI

- Tailwind v4 + `tokens.css`(색·서체·간격·radius·shadow·motion CSS 변수) → Tailwind `@theme` 연결. 밝은 화면 기본.
- 공식 로고 `static/brand/wecar-logo.png`(wecarmobility.com), PWA 아이콘은 로고 기반 정사각 PNG.
- 공통 푸터(`components/footer.html` 한 곳): 상호 위카모빌리티, 대표이사, 사업자번호, 주소, 진단 대표번호, 개인정보 처리방침 링크. 고정 위치 사용 안 함.
- 표는 `md` 미만에서 카드 목록으로 전환. 터치 영역 44px, focus 표시, `prefers-reduced-motion` 준수. 글래스 효과는 로그인 환영 패널에만(대체 불투명 스타일 포함).
- 툴팁: hover·click·focus·touch로 열림, Escape로 닫힘.

## 8. PWA·인앱 브라우저

- `/manifest.webmanifest`(scope `/admin/`, start_url `/admin/`, standalone), `/service-worker.js`(공개 정적 파일만 버전별 캐시).
- 로그인 후 `beforeinstallprompt` 발생 시 비차단 배너. 거절/나중에는 localStorage에 기억, 메뉴 "앱 설치 안내"로 재표시. iOS는 홈 화면 추가 안내.
- 카카오톡·네이버·인스타그램·페이스북·라인 인앱 감지 시 "기본 브라우저로 열기"(Android intent + HTTPS fallback, 사용자 클릭 시) · "URL 복사".

## 9. 배포

- `Dockerfile`: node 단계(Tailwind 빌드) → python 3.12-slim 단계, 비루트 `app` 사용자, gunicorn. 이미지에 `.env` 미포함. 시작 시 자동 마이그레이션 안 함.
- `compose.yaml`(개발): web(소스 마운트, flask debug), assets(Tailwind watch), postgres. 포트 18080.
- `compose.prod.yaml`(운영): 이미지 `wecarmobility/scantest`, postgres, redis(속도 제한 저장소).

## 10. 검증

- pytest(Postgres): API 호환(로그인·갱신·로그아웃·무효화·스캔 권한·목록 형식·camelCase·검증 오류), 관리자 로그인·MFA·CSRF·회원 수정 충돌, AI 키 암호화·마스킹.
- 브라우저: 320/390px·데스크톱에서 로그인·회원관리·AI 연결.
- 컨테이너: 로컬 교체 후 `/up`, 관리자 로그인.

## 11. 남은 제약

- 실제 SMS 발송, PDF 생성, 이메일 전송은 미구현(기존과 동일).
- 운영 MariaDB에 데이터가 있다면 PostgreSQL 이전 스크립트가 별도로 필요.
- 보험 사이트 시각 참고, 실제 기기 PWA 검증, 공식 홈페이지 표기 최종 대조는 담당자 확인 필요.
