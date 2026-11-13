# 차량 정의파일 Import 가이드

## 사전 준비

### 1. 환경 설정
```bash
# .env 파일에 DB 비밀번호 설정
cp .env.example .env
# POSTGRES_PASSWORD를 설정하세요
```

### 2. Docker Compose 시작
```bash
docker compose up -d
```

## Import 실행

### 1. 마이그레이션 (최초 1회)
```bash
docker compose exec web flask db upgrade
```

### 2. 정의파일 Import
정의파일 폴더를 컨테이너에 마운트하거나 복사한 후:

```bash
# 방법 1: 볼륨 마운트 (compose.yaml에 추가)
# volumes:
#   - /path/to/차량측정용_정의파일:/definitions:ro

# 방법 2: 컨테이너에 복사
docker cp 차량측정용_정의파일 scantest-web-1:/tmp/

# Import 실행
docker compose exec web flask definitions import /tmp/차량측정용_정의파일

# 또는 제외목록 사용
docker compose exec web flask definitions import /tmp/차량측정용_정의파일 --exclude-file /tmp/제외목록.json
```

### 3. Import 통계 확인
```bash
docker compose exec web flask definitions stats
```

예상 출력:
```
=== Vehicle Definitions Statistics ===

Definition Sources: 1,177
  canze: 51
  dbc: 477
  obdb: 512
  torque: 48
  wican: 89

Vehicle Mappings: 1,050+
DBC Messages: 12,500+
DBC Signals: 85,000+
Diagnostic Commands: 45,000+

Diagnostic Commands Verification:
  Verified: 0 (import 직후)
  Needs Verification: 45,000+
```

## Import 시간 예상

- **DBC** (477개, ~77MB): 5-10분
- **OBDb** (512개): 3-5분
- **WiCAN** (89개): 1-2분
- **Torque** (48개): 1분 미만
- **CanZE** (51개): 1분 미만

**총 예상 시간**: 10-20분

## Import 후 DB 용량

- **definition_sources**: ~1MB (파일 메타데이터)
- **vehicle_definitions**: ~1MB (차량 매핑)
- **dbc_messages**: ~50MB (CAN 메시지)
- **dbc_signals**: ~500MB-1GB (신호 정의)
- **diagnostic_commands**: ~200-500MB (진단 명령)

**총 예상 용량**: ~1-2GB

## 제외목록 형식

`제외목록.json`:
```json
{
  "files": [
    "broken_file.dbc",
    "test_only.json"
  ]
}
```

## Troubleshooting

### Import 실패 시
```bash
# 로그 확인
docker compose logs web

# 특정 파일 오류 시 제외목록에 추가하고 재실행
```

### DB 용량 부족 시
```bash
# Docker 볼륨 정리
docker volume prune

# 또는 pgdata 볼륨 재생성
docker compose down -v
docker compose up -d
```

### 중복 Import 방지
- SHA-256으로 중복 체크하므로 재실행해도 안전합니다
- 기존 데이터는 스킵되고 새 파일만 추가됩니다

## Production 환경 (Mac 서버)

`compose.prod.yaml` 사용 시:

```bash
# 마이그레이션 자동 실행 (AUTO_DB_UPGRADE=1)
docker compose -f compose.prod.yaml up -d

# Import
docker compose -f compose.prod.yaml exec web flask definitions import /data/definitions
```

`compose.prod.yaml`의 `AUTO_DB_UPGRADE=1` 설정으로 컨테이너 시작 시 자동으로 `flask db upgrade`가 실행됩니다.

## 학습 시스템

Import 후 정의는 `needs_verification` 상태입니다. 실제 스캔을 실행하면:

1. 각 정의를 적용하여 응답 디코딩 시도
2. 성공/실패를 `scan_observations`에 기록
3. 10회 이상 시도, 성공률 80% 이상 → `verified` 자동 승격
4. 성공률 20% 미만 → `failed` 표시

학습 진행 확인:
```bash
docker compose exec web flask definitions stats
```

## 분석 사용

```python
from app.modules.definitions.analyzer import analyze_scan_with_definitions

# 스캔 분석
result = analyze_scan_with_definitions(scan)

# 결과:
# {
#   'vehicle': {...},
#   'battery': {'SOC': {'value': 85.5, 'unit': '%', 'verified': True}, ...},
#   'powertrain': {'Motor RPM': {'value': 2500, 'unit': 'rpm', 'verified': True}, ...},
#   'dtcs': [...],
#   'definitions_applied': {
#     'total_commands': 150,
#     'verified_commands': 20,
#     'successful_decodes': 120,
#     'failed_decodes': 30
#   }
# }
```

## 보안 주의사항

- **개인정보 제외**: VIN, 차량번호가 포함된 정의파일은 import하지 마세요
- **Formula 안전성**: 모든 formula는 안전한 AST evaluator로 실행됩니다 (eval() 사용 안 함)
- **원본 보존**: import는 원본 파일을 수정하지 않습니다
