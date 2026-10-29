# 0002. Compose web 기동 전 선택적 DB 이전을 실행한다

- 상태: 채택 (2026-10-29)

## 배경

`pro.md`는 운영 시작 때 무조건 자동 이전을 금지한다. 이 원칙은 일반 배포에서 의도하지 않은 스키마 변경을 막기 위한 기준이다.

이번 Mac/prod Docker Compose 전환은 빈 PostgreSQL 볼륨 최초 기동과 저장소 시드 복원 직후 웹 컨테이너가 바로 실행되어야 한다. 이때 Alembic head까지 맞추는 `flask db upgrade`가 빠지면 첫 기동 절차가 수동 단계에 의존한다.

## 결정

- `AUTO_DB_UPGRADE=1`일 때만 web 엔트리포인트가 애플리케이션 실행 전에 `flask db upgrade`를 실행한다.
- Mac/prod Compose 파일은 최초 기동 편의를 위해 `AUTO_DB_UPGRADE: "1"`을 기본값으로 둔다.
- `flask db upgrade` 실패 시 컨테이너 시작을 중단해 잘못된 스키마로 서비스를 열지 않는다.
- 엔트리포인트는 비루트 `app` 사용자로 실행되며, 앱 의존성과 `flask` 명령은 이미지 빌드 단계의 `pip install` 결과를 사용한다.

## 영향

- 이 결정은 Compose 기반 Mac/prod 운영의 예외이며, 모든 환경에서 무조건 자동 이전을 허용한다는 의미가 아니다.
- 자동 이전을 원하지 않는 환경은 `AUTO_DB_UPGRADE`를 비우거나 `0`으로 둔다.
