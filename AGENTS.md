# AGENTS

작업 전에 `pro.md`(기술개발 정의서)와 `docs/superpowers/specs/`의 요구사항을 읽는다.

- 모바일 앱 API(`/api/*`)는 `docs/legacy/laravel-api.json`과 응답 형식이 같아야 한다. 변경 시 `tests/api/` 호환 테스트를 먼저 고친다.
- 화면 CSS는 Tailwind(`docs/adr/0001`), 색·간격은 `app/static/css/tokens.css`에서만 정의한다.
- DB 변경은 `flask db migrate` → 스크립트 검토 → `flask db upgrade` 순서를 지킨다.
- 차량 통신(2026-10-18 대표 결정): 읽기 계획(`scanner/plan.py`)은 기본 세션 읽기만(`10`·`27`·`2E`·`31`·`04`·`14` 금지). 제어기 순회(`SWEEP_COMMON`·`SWEEP_EV`)는 기본 스캔에 포함. 고장코드 지우기는 `scanner/clear.py` 흐름(권한·확인·1회용 토큰·감사기록·`dtc_clear_logs`)으로만 하고, `10 03`은 그 흐름에서 NRC 7F를 받은 제어기에만 쓴다.
