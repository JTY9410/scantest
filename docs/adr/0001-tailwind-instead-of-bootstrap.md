# 0001. 관리자 화면 CSS는 Bootstrap 대신 Tailwind CSS를 쓴다

- 상태: 채택 (2026-10-13)

## 배경

기술개발 정의서의 기본 스택은 Bootstrap 5이지만, 이번 재구축 요청에서 Tailwind CSS 적용을 명시했다.

## 결정

- Tailwind CSS 4 CLI로 `app/static/css/app.css`를 `app/static/dist/app.css`로 빌드한다. 빌드 결과는 저장소에 올리지 않고 Docker `assets` 단계에서 만든다.
- 색·글꼴·간격·반경·그림자는 `tokens.css`의 `--wc-*` 변수에서만 정의하고, `@theme inline`으로 Tailwind 유틸리티에 연결한다.
- 버튼·입력·표·배지처럼 여러 화면이 쓰는 모양은 `components.css`의 `@layer components` 클래스로 한 번만 만든다. 화면 템플릿에는 배치용 유틸리티만 쓴다.
- CSP가 `'self'`만 허용하므로 인라인 스타일·스크립트는 쓰지 않는다.

## 영향

- 개발 시 Node가 필요하다(`compose.yaml`의 `assets` 서비스가 감시 빌드).
- 컴포넌트 클래스로 숨긴 요소(예: 설치 안내 변형, 툴팁 본문)에 `hidden`/`flex` 같은 표시 유틸리티를 붙이면 유틸리티가 이긴다. 표시 여부는 컴포넌트 CSS나 `hidden` 속성으로만 바꾼다.
- 정적 파일 URL의 `?v=`와 서비스 워커 캐시 이름은 CSS·JS 내용 해시(`app/core/assets.py`)라서 CSS를 다시 빌드하면 자동으로 새 파일을 받는다.
