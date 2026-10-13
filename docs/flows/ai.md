# AI 연결 관리

AI 기능 자체(RAG 등)는 아직 없고, 공급자별 연결 정보만 관리합니다.

| 사용자 행동 | route | service (`admin/ai_service.py`) | 저장 | 결과 |
| --- | --- | --- | --- | --- |
| 공급자 목록 | `GET /admin/ai` | `connections_by_provider` | - | OpenAI·Anthropic·Gemini 상태 |
| 모델·기능·예산 저장 | `POST /admin/ai/<provider>` | `save_settings` | 연결 설정, 감사기록 | 완료 안내. 버전이 다르면 409 |
| 키 등록·교체 | `POST /admin/ai/<provider>/key` | `replace_key` | 암호화된 키, 끝 4자리, 상태 "미검사" | 화면에는 끝 4자리만 표시 |
| 연결 테스트 | `POST /admin/ai/<provider>/test` | `test_connection` | 상태(정상/실패), 검사 시각, 메시지 | 결과 안내 |
| 키 폐기 | `POST /admin/ai/<provider>/revoke` | `revoke_key` | 키 삭제, 상태 "폐기", 기능 모두 끔 | 완료 안내 |

- 키는 `ENCRYPTION_KEY`(Fernet)로 암호화해 저장하고, 감사기록과 로그에는 끝 4자리만 남깁니다.
- 연결 테스트는 공급자의 모델 조회 API를 호출합니다. 테스트 코드에서는 `_probe`를 대체합니다.
