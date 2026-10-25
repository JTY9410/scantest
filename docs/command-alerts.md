# 검증 명령 삭제 여부 알림

검증(verified) 명령이 실제 스캔에서 동작하지 않으면 관리자에게 **삭제/유지**를 묻는 알림을 만든다. 자동 삭제는 하지 않는다.

## 집계 (app/modules/knowledge/alerts.py)
스캔을 저장할 때(`run_scan`) 단계 결과마다, 같은 명령·주소(헤더)·제조사(또는 공통) 범위의 검증 명령에 누적한다(`command_health`).

| 단계 상태 | 처리 |
|---|---|
| ok | 성공. 연속 실패를 0으로 |
| no_data, negative, timeout, unsupported | 실패 |
| device_error, disconnected, skipped, pending | 세지 않음(단말기·연결 문제) |

## 알림 기준 (환경변수, 기본값)
- `COMMAND_ALERT_CONSECUTIVE=5` : 연속 실패 5회 이상, 또는
- `COMMAND_ALERT_MIN_ATTEMPTS=20` 이상 시도했고 실패율이 `COMMAND_ALERT_FAILURE_RATE=0.8` 이상

같은 명령에 대기(pending) 알림이 있으면 새로 만들지 않는다.

## 처리 화면
- 관리자 화면 상단에 빨간 배너가 뜨고, `/admin/knowledge/commands` 맨 위 "삭제 여부 확인 필요" 목록에서 처리한다.
- **삭제**: 명령을 지우고 `promotion_log`에 `new_status=deleted`로 남긴다.
- **유지**: 명령을 그대로 두고 누적을 0으로 돌린다. 새 실패가 다시 기준을 넘을 때만 다시 알린다.
- 관리자만, CSRF 토큰이 있어야 처리된다.

이메일·Slack·웹훅 알림 기능은 이 앱에 없어서 화면 알림만 제공한다.

## 제조사 표기
`app/core/makers.py`가 같은 제조사의 여러 표기를 하나로 맞춘다. Nissan/NISSAN/nissan/닛산 → **닛산**. 저장(모델 `validates`), 조회, DTC 문서 가져오기가 모두 이 함수를 쓴다.
