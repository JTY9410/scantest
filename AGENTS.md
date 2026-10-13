# AGENTS

작업 전에 `pro.md`(기술개발 정의서)와 `docs/superpowers/specs/`의 요구사항을 읽는다.

- 모바일 앱 API(`/api/*`)는 `docs/legacy/laravel-api.json`과 응답 형식이 같아야 한다. 변경 시 `tests/api/` 호환 테스트를 먼저 고친다.
- 화면 CSS는 Tailwind(`docs/adr/0001`), 색·간격은 `app/static/css/tokens.css`에서만 정의한다.
- DB 변경은 `flask db migrate` → 스크립트 검토 → `flask db upgrade` 순서를 지킨다.
