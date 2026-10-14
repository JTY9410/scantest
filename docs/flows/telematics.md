# LTE OBD2 단말기

차량에 꽂아 두는 LTE 단말기는 사람이 화면을 누르지 않고 서버의 스캔 계획대로 명령을 보내고, ELM327 응답 문자열을 그대로 올립니다. 해석·저장은 웹 스캔하기와 같은 `scanner/service.run_scan`을 씁니다(`docs/flows/scanner.md`).

| 사용자 행동 | route | service (`obd/telematics.py`) | 저장 | 결과 |
| --- | --- | --- | --- | --- |
| 단말기 등록 | `POST /admin/obd/devices` | `register` | 단말기(토큰 해시), 감사기록 | 토큰을 이 화면에서 한 번만 보여 줌. 같은 일련번호는 409 |
| 토큰 재발급 | `POST /admin/obd/devices/<id>/token` | `rotate_token` | 새 해시, 감사기록 | 새 토큰을 한 번만 보여 줌. 이전 토큰은 바로 무효 |
| 사용·중지 | `POST /admin/obd/devices/<id>/toggle` | `set_enabled` | 감사기록 | 중지된 단말기는 401 |
| 단말기가 계획 받기 | `GET /api/telematics/plan?carNo=` | `authenticate`, `plan_for` | 마지막 접속 시각 | `carNo`, `car`(조회 결과), `lookupError`, `steps`, `notes` |
| 단말기가 결과 올리기 | `POST /api/telematics/captures` | `authenticate`, `receive` | 통신 기록(source `lte`), 결과지, 스캔 | 201 `{id, status, errors}` |

## 인증

- 헤더 `Authorization: Device <토큰>`. 토큰은 `secrets.token_urlsafe(32)`이고 서버에는 SHA-256 해시와 끝 4자리만 남습니다.
- 토큰이 없거나 틀리거나 단말기가 중지되면 401 `{"message": "단말기 인증에 실패했습니다."}`.
- 모바일 앱 API(`Bearer`)와 섞지 않습니다. 단말기 API는 Laravel 원본에 없던 새 API입니다.

## 결과 올리기 형식

```json
{
  "carNo": "12가3456",
  "steps": [
    {"id": 1, "command": "ATRV", "reply": "12.4V", "tMs": 0},
    {"id": 2, "command": "0100", "reply": "7E8 06 41 00 98 3B 80 13", "tMs": 820},
    {"id": 9, "command": "03", "reply": null, "error": "timeout", "tMs": 5100},
    {"id": 40, "command": "22F190", "header": "7E1", "error": "skipped", "reason": "응답 없는 제어기"}
  ]
}
```

- 계획에서 받은 `id`, `group`, `label`, `header`, `optional`, `probe`, `bus`를 그대로 돌려보내면 결과 화면의 단계 이름과 지원 여부 판단이 정확해집니다.
- `error`: `timeout`(응답 없음), `disconnected`(차량·단말기 연결 끊김), `skipped`(건너뜀, `reason`에 이유), 그 밖의 문자열은 단말기 오류로 기록합니다.
- 응답은 `ATH1`(헤더 표시) 상태의 원문을 보냅니다. CAN은 `7E8 06 41 ...`, K-Line·J1850은 `48 6B 10 41 ...` 형식입니다.
- 단계는 400개, 응답 하나는 4,000자까지 받습니다.

## 차량 정보와 검사자

- 차량정보 조회는 저장된 결과를 먼저 씁니다. 조회에 실패해도 스캔은 저장하고, 실패 안내를 오류 기록 첫 줄에 남깁니다.
- 스캔의 검사자(`tester_id`)는 단말기를 등록한 관리자, 회사는 단말기에 지정한 회사입니다.
