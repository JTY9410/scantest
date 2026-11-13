# 차량 정의파일 DB 및 분석 시스템

2026-11-13 작성

## 개요

scantest는 차량 OBD2 진단 데이터를 수집·분석하여 WESCAN 스타일의 진단 결과를 생성하는 프로그램입니다. 이 문서는 2026-11-13에 추가된 차량 정의파일(DBC, OBDb, WiCAN, Torque, CanZE) 데이터베이스 통합 및 분석·학습 기능을 설명합니다.

## 프로그램 내용

### 기존 기능
- OBD2/CAN 스캔 실행 및 저장
- 고장코드(DTC) 조회 및 삭제 (권한/감사기록)
- 스캔 이력 관리 및 PDF 보고서 생성
- 지식베이스 (knowledge_*): 검증된 명령·수식·DTC·용어
- 역분석 (canlab): 위스캔·리버스 통신기록 비교

### 신규 추가 (2026-11-13)
- **정의파일 DB 저장**: DBC(477개), OBDb(512개), WiCAN(89개), Torque(48개), CanZE(51개) 파일을 정규화된 DB 테이블에 저장
- **차량별 정의 매핑**: 제조사·모델·연도별로 적용 가능한 정의 자동 검색
- **분석 파이프라인**: 스캔 로그 → 차량 매핑 → 신호 디코딩 → 결과 생성
- **학습 시스템**: 실제 스캔 결과를 누적하여 정의 검증 상태 자동 승격 ('needs_verification' → 'verified')
- **DBC 브로드캐스트 디코딩** (2026-11-13 추가): 주기적 CAN 프레임을 DBC 정의로 디코딩 (비트 추출, 스케일, 타당성 검증)
- **WESCAN 등급 자동 생성** (2026-11-13 추가): 기존 threshold 로직 재사용하여 배터리 수명, 절연, 편차, DTC 등급 자동 계산
- **Verification Metrics 자동 업데이트** (2026-11-13 추가): 분석 저장 시 명령 검증 상태 자동 승격/강등 (10회 이상, 80%/20% 기준)
- **다양한 차종 지원** (2026-11-13 추가): Hyundai/Kia E-GMP (Ioniq 5/6, EV6, GV60), Kona EV, Niro EV, 범용 ICE (J1979 Mode 01)

## DB 스키마

### definition_sources
정의파일 출처 메타데이터 (SHA-256, 라이선스, 출처 저장소)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INTEGER | PK |
| source_type | VARCHAR(20) | dbc\|obdb\|wican\|torque\|canze |
| file_path | VARCHAR(500) | 원본 파일 경로 |
| sha256 | VARCHAR(64) | 파일 해시 (중복 방지) |
| file_size | INTEGER | 파일 크기 |
| origin_repo | VARCHAR(200) | 출처 저장소 |
| origin_commit | VARCHAR(40) | 커밋 SHA |
| license | VARCHAR(100) | 라이선스 (예: CC BY-SA 4.0) |
| license_text | TEXT | 라이선스 전문 |
| attribution | TEXT | 저작권 고지 |
| imported_at | DATETIME | import 시각 |
| notes | TEXT | 비고 |

### vehicle_definitions
차량-정의파일 매핑

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INTEGER | PK |
| source_id | INTEGER | FK → definition_sources.id |
| maker | VARCHAR(50) | 제조사 (정규화) |
| model | VARCHAR(100) | 모델 |
| submodel | VARCHAR(100) | 서브모델 |
| year_from | INTEGER | 적용 시작 연도 |
| year_to | INTEGER | 적용 종료 연도 |
| powertrain | VARCHAR(20) | ev\|hev\|ice |
| notes | TEXT | 비고 |
| created_at | DATETIME | 생성 시각 |

### dbc_messages
DBC CAN 메시지 정의

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INTEGER | PK |
| source_id | INTEGER | FK → definition_sources.id |
| can_id | INTEGER | CAN ID (0x7E4 등) |
| message_name | VARCHAR(100) | 메시지 이름 |
| dlc | INTEGER | Data Length Code |
| sender | VARCHAR(50) | 송신 ECU |
| comment | TEXT | 설명 |

### dbc_signals
DBC CAN 신호 (메시지 내 개별 신호)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INTEGER | PK |
| message_id | INTEGER | FK → dbc_messages.id |
| signal_name | VARCHAR(100) | 신호 이름 |
| start_bit | INTEGER | 시작 비트 |
| bit_length | INTEGER | 비트 길이 |
| byte_order | VARCHAR(10) | little\|big |
| value_type | VARCHAR(10) | signed\|unsigned |
| factor | FLOAT | 스케일 계수 |
| offset | FLOAT | 오프셋 |
| min_value | FLOAT | 최소값 |
| max_value | FLOAT | 최대값 |
| unit | VARCHAR(20) | 단위 |
| comment | TEXT | 설명 |
| receivers | VARCHAR(200) | 수신 ECU 목록 |

### diagnostic_commands
진단 명령 (OBDb, WiCAN, Torque, CanZE 통합)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INTEGER | PK |
| source_id | INTEGER | FK → definition_sources.id |
| source_type | VARCHAR(20) | obdb\|wican\|torque\|canze |
| maker | VARCHAR(50) | 제조사 (optional scoping) |
| model | VARCHAR(100) | 모델 |
| year_from | INTEGER | 적용 시작 연도 |
| year_to | INTEGER | 적용 종료 연도 |
| ecu_address | VARCHAR(10) | ECU 주소 (7E4, 7E0 등) |
| ecu_name | VARCHAR(100) | ECU 이름 |
| service | VARCHAR(10) | UDS/OBD 서비스 (22, 01 등) |
| pid | VARCHAR(20) | PID/DID |
| command_bytes | VARCHAR(100) | 전체 명령 (예: 22 1050) |
| label | VARCHAR(200) | 신호 이름 |
| formula | TEXT | 계산식 (value 치환) |
| unit | VARCHAR(20) | 단위 |
| response_start_byte | INTEGER | 응답 시작 바이트 |
| response_bit_offset | INTEGER | 비트 오프셋 |
| response_length | INTEGER | 응답 길이 (bits or bytes) |
| frequency | FLOAT | 조회 빈도 (Hz) |
| min_value | FLOAT | 최소값 |
| max_value | FLOAT | 최대값 |
| notes | TEXT | 비고 |
| verification_status | VARCHAR(20) | needs_verification\|verified\|failed |
| verification_count | INTEGER | 검증 시도 횟수 |
| success_count | INTEGER | 성공 횟수 |
| failure_count | INTEGER | 실패 횟수 |
| created_at | DATETIME | 생성 시각 |
| updated_at | DATETIME | 갱신 시각 |

### scan_observations
스캔별 정의 적용 관찰 결과 (학습용)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INTEGER | PK |
| scan_id | INTEGER | FK → scans.id |
| definition_type | VARCHAR(20) | dbc\|diagnostic |
| definition_id | INTEGER | DbcSignal.id or DiagnosticCommand.id |
| applied | BOOLEAN | 적용 여부 |
| success | BOOLEAN | 성공 여부 (NULL = 시도 안 함) |
| raw_request | VARCHAR(200) | 원시 요청 |
| raw_response | TEXT | 원시 응답 |
| decoded_value | VARCHAR(200) | 디코딩된 값 |
| mismatch_reason | TEXT | 불일치 사유 |
| observed_at | DATETIME | 관찰 시각 |

## Import 방법

### 1. 마이그레이션 실행
```bash
docker compose -f compose.prod.yaml exec web flask db upgrade
```

또는 로컬:
```bash
flask db upgrade
```

### 2. 정의파일 import
```bash
flask definitions import /path/to/차량측정용_정의파일
```

옵션:
- `--exclude-file <제외목록.json>`: 제외할 파일 목록 JSON

### 3. Import 통계 확인
```bash
flask definitions stats
```

출력 예시:
```
=== Vehicle Definitions Statistics ===

Definition Sources: 1177
  dbc: 477
  obdb: 512
  wican: 89
  torque: 48
  canze: 51

Vehicle Mappings: 1050
DBC Messages: 12500
DBC Signals: 85000
Diagnostic Commands: 45000

Diagnostic Commands Verification:
  Verified: 1200
  Needs Verification: 43800
```

## 스캔 분석 흐름 (업데이트: 2026-11-13)

### 1. 차량 매핑
```python
from app.modules.definitions.service import find_applicable_definitions

definitions = find_applicable_definitions(scan)
# → {'dbc_signals': [...], 'diagnostic_commands': [...]}
```

스캔의 제조사·모델·연도에 맞는 정의를 자동 검색합니다.

### 2. 신호 디코딩 (DBC)
```python
from app.modules.definitions.service import decode_signal

for dbc_data in definitions['dbc_signals']:
    signal = dbc_data['signal']
    can_id = dbc_data['can_id']
    
    # CAN 프레임 매칭
    if can_frame['id'] == can_id:
        value = decode_signal(signal, can_frame['data'])
        # value는 factor/offset 적용된 실제 값
```

### 3. 진단 명령 응답 해석
```python
from app.modules.definitions.service import decode_diagnostic_response

for cmd in definitions['diagnostic_commands']:
    # ECU에 명령 전송
    response = send_command(cmd.ecu_address, cmd.command_bytes)
    
    # 응답 디코딩
    decoded_value = decode_diagnostic_response(cmd, response)
```

### 4. DBC 브로드캐스트 프레임 디코딩 (신규: 2026-11-13)
```python
from app.modules.definitions.dbc_decoder import decode_broadcast_frames

# 요청-응답이 아닌 주기적 CAN 프레임 디코딩
can_frames = [
    {'can_id': '0x100', 'data': '01 02 03 04 05 06 07 08', 'timestamp': 1.0},
    # ...
]

decoded = decode_broadcast_frames(can_frames, maker='Kia', model='EV6')
# → {0x100: {'Battery_Voltage': {'value': 704.2, 'unit': 'V', 'valid': True}}}
```

비트 추출 및 변환:
- `start_bit`, `bit_length`로 정확한 위치 추출
- `byte_order` (little/big endian) 지원
- `value_type` (signed/unsigned) 지원
- `factor`, `offset` 적용
- 물리적 타당성 검증 (범위, 센티널 필터링)

### 5. WESCAN 등급 자동 계산 (신규: 2026-11-13)
```python
from app.modules.definitions.wescan_grades import compute_wescan_grades

grades = compute_wescan_grades(analyzer_result)
# [
#   {'item': '배터리 수명 (SOH)', 'standard': 'SOH 80% 이상 시 양호', 
#    'value': 96.7, 'unit': '%', 'result': '양호'},
#   {'item': '셀 전압 편차', 'standard': '셀 전압 최대-최소 차이 1.0V 이하 시 양호',
#    'value': 0.0, 'unit': 'V', 'result': '양호'},
#   ...
# ]
```

기존 threshold 재사용 (scanner/report.py):
- SOH >= 80%: 양호
- 절연 저항 >= 500 kΩ: 양호
- 셀 전압 편차 <= 1.0V: 양호
- 모듈 온도 편차 <= 20°C: 양호
- DTC 0개: 양호

### 6. Verification Metrics 자동 업데이트 (신규: 2026-11-13)
```python
from app.modules.definitions.verification import update_verification_metrics

stats = update_verification_metrics(scan_id)
# → {'promoted': 3, 'demoted': 0, 'unchanged': 10}
```

자동 승격/강등 규칙:
- **10회 이상 시도, 성공률 >= 80%**: `verified`
- **성공률 < 20%**: `failed`
- **그 외**: `experimental`

### 7. 관찰 기록 (학습)
```python
from app.modules.definitions.service import record_observation, update_command_stats

record_observation(
    scan_id=scan.id,
    definition_type='diagnostic',
    definition_id=cmd.id,
    applied=True,
    success=(decoded_value is not None),
    raw_request=cmd.command_bytes,
    raw_response=response.hex(),
    decoded_value=decoded_value,
)

update_command_stats(cmd.id, success=(decoded_value is not None))
```

## 학습 시스템 동작 (업데이트: 2026-11-13)

### 자동 검증 승격 (실시간)
분석 저장 시 `update_verification_metrics(scan_id)` 자동 호출:
- **needs_verification → verified**: 10회 이상 시도, 성공률 >= 80%
- **needs_verification → failed**: 성공률 < 20%
- **needs_verification → experimental**: 그 외

`verification_metrics` JSON 필드 자동 업데이트:
```json
{
  "total_tries": 15,
  "successful_tries": 14,
  "success_rate": 0.933,
  "last_updated": "2026-11-13T12:00:00"
}
```

### 학습 요약 조회
```python
from app.modules.definitions.service import get_learning_summary

summary = get_learning_summary(command_id)
# → {'total_observations': 15, 'successful': 14, 'failed': 1, 
#     'verification_status': 'verified', 'success_rate': 0.93}
```

### 수동 검증 승격
관리자가 실차 테스트 후 직접 상태 변경:
```python
cmd = DiagnosticCommand.query.get(command_id)
cmd.verification_status = 'verified'
db.session.commit()
```

## WESCAN 스타일 결과 생성 (업데이트: 2026-11-13)

WESCAN 앱과 유사한 진단 결과 구조 및 등급을 자동 생성합니다:

```python
def analyze_scan(scan: Scan) -> dict:
    """WESCAN 스타일 분석 결과 생성."""
    definitions = find_applicable_definitions(scan)
    
    result = {
        'vehicle': {
            'maker': scan.car_maker,
            'model': scan.car_model,
            'year': scan.car_year,
            'vin': scan.car_vin,
        },
        'battery': {},
        'powertrain': {},
        'dtcs': [],
        'raw_definitions': {
            'applied_count': len(definitions['diagnostic_commands']),
            'verified_count': sum(1 for c in definitions['diagnostic_commands'] 
                                if c.verification_status == 'verified'),
        }
    }
    
    # 배터리 신호 디코딩
    for cmd in definitions['diagnostic_commands']:
        if 'battery' in cmd.label.lower() or 'soc' in cmd.label.lower():
            # ... 응답 수신 및 디코딩
            result['battery'][cmd.label] = decoded_value
    
    # 파워트레인 신호
    for cmd in definitions['diagnostic_commands']:
        if 'motor' in cmd.label.lower() or 'speed' in cmd.label.lower():
            result['powertrain'][cmd.label] = decoded_value
    
    # 고장코드 (기존 로직 유지)
    result['dtcs'] = scan.scan_codes
    
    # DBC 브로드캐스트 신호 (신규: 2026-11-13)
    result['broadcast_signals'] = decode_broadcast_frames(
        can_frames, scan.car_maker, scan.car_model
    )
    
    # WESCAN 등급 자동 생성 (신규: 2026-11-13)
    result['wescan_grades'] = compute_wescan_grades(result)
    
    # Verification metrics 자동 업데이트 (신규: 2026-11-13)
    update_verification_metrics(scan.id)
    
    return result
```

**실제 출력 예시 (EV6 File B, 2026-11-13 테스트)**:
```python
{
  'vehicle': {'maker': 'Kia', 'model': 'EV6', 'year': 2022},
  'battery': {
    'soc_pct': 45.5,
    'soh_pct': 96.7,
    'pack_voltage_v': 704.2,
    'pack_current_a': 0.0,
    'max_temp_c': 19,
    'min_temp_c': 19,
    'max_cell_voltage_v': 3.66,
    'min_cell_voltage_v': 3.66,
    'cum_charge_kwh': 2703.6,
    'cum_discharge_kwh': 2230.4,
  },
  'broadcast_signals': {},  # (테스트 fixture에 DBC 정의 없음)
  'wescan_grades': [
    {'item': '배터리 수명 (SOH)', 'value': 96.7, 'unit': '%', 'result': '양호'},
    {'item': '셀 전압 편차', 'value': 0.0, 'unit': 'V', 'result': '양호'},
    {'item': '모듈 온도 편차', 'value': 0, 'unit': '°C', 'result': '양호'},
    {'item': '고장 코드 (DTC)', 'value': 0, 'unit': '개', 'result': '양호'},
  ],
  'dtcs': [],
}
```

## 남은 갭 (Known Limitations)

### 1. DBC 파서 (2026-11-13: 개선)
- ✅ 비트 추출, byte order, signedness, scale/offset 지원
- ✅ 물리적 타당성 검증 및 센티널 필터링
- ❌ Multiplexed signal 미지원
- ❌ Value table (enum mapping) 미지원

### 2. 진단 명령 formula 보안
- eval() 사용으로 임의 코드 실행 가능성
- 프로덕션 환경에서는 safe_eval 또는 AST 파서 필요
- 현재는 formula 입력을 신뢰할 수 있는 정의파일로 제한

### 3. 실시간 스캔 통합
- 현재는 분석 함수만 제공, 실시간 스캔 흐름에 미통합
- scanner/plan.py, scanner/interpret.py와 연계 필요
- 다음 단계: 스캔 계획 생성 시 verified 정의 자동 포함

### 4. 대용량 데이터 성능
- 85,000개 신호를 매번 쿼리하면 느림
- 인덱스 최적화 완료, 추가 캐싱 고려 필요
- 차량별 정의는 첫 스캔 시 캐시하는 전략 권장

### 5. 충돌 해결
- 같은 ECU/서비스/PID에 여러 정의가 있을 수 있음
- 현재는 모두 반환, 우선순위 정책 없음
- 향후: source_type 우선순위 (obdb > wican > torque > canze)

### 6. 정의파일 갱신
- import는 SHA-256 중복 체크로 멱등성 보장
- 정의 내용 변경 시 기존 데이터 migration 없음
- 향후: version 관리 및 변경 이력 추적

## API 엔드포인트 (예정)

현재는 CLI만 제공, 향후 추가 예정:

```
GET  /api/definitions/search?maker=<maker>&model=<model>&year=<year>
  → 차량에 맞는 정의 목록

GET  /api/definitions/diagnostic/<id>
  → 특정 진단 명령 상세

POST /api/definitions/diagnostic/<id>/verify
  → 수동 검증 상태 변경 (관리자만)

GET  /api/definitions/learning/<id>
  → 학습 요약 조회

POST /api/scans/<id>/analyze
  → 저장된 스캔 재분석 (새 정의 적용)
```

## 참고 자료

- `AGENTS.md`: 작업 규칙
- `pro.md`: 기술개발 정의서
- `DEPLOY.md`: 배포 가이드
- `GAPS.md`: 알려진 제약과 남은 작업
- `docs/flows/scanner.md`: 스캔 흐름
- `app/modules/knowledge/`: 기존 지식베이스 (knowledge_*)
- `app/modules/canlab/`: CAN 역분석

## 라이선스 고지

이 프로그램에 포함된 정의파일은 다음 출처의 2차 저작물입니다:

- **OBDb** (https://github.com/OBDb): CC BY-SA 4.0
- **WiCAN** 등 오픈소스 커뮤니티: 각 파일의 라이선스 참조
- DBC 파일: 출처별 라이선스 (definition_sources.license에 저장)

자세한 라이선스 정보는 `출처목록.json`, `저작권고지` 파일 및 DB의 definition_sources 테이블을 참조하세요.

## 문의

- GitHub Issues: https://github.com/JTY9410/scantest/issues
- 개발팀: 위카모빌리티

---

## SOH (State of Health) 계산 방법

배터리 상태 추정을 위해 다음 7가지 방법을 우선순위 순으로 적용합니다.

### Method 0: BMS 직접 읽기 (bms_direct)
- **설명**: BMS가 제공하는 SOH 값을 직접 읽기
- **데이터**: `7E4 22 0105` 응답의 byte 25-26, scale 0.1
- **신뢰도**: 0.95 (가장 높음)
- **전제조건**: BMS가 SOH를 계산하고 제공해야 함
- **제약**: 일부 구형 차량은 미지원

### Method 1: 현재 용량 기반 (capacity_based_ah / capacity_based_kwh)
- **설명**: 현재 용량 / 원래 용량 × 100
- **데이터**: BMS 현재 용량 (Ah/kWh) + DB battery_specs 원래 용량
- **신뢰도**: 0.90
- **전제조건**: BMS 현재 용량 + 해당 차종 사양 DB 등록
- **제약**: 완충 상태 측정 시 정확도 향상

### Method 2: Coulomb Counting (coulomb_counting)
- **설명**: 누적 충·방전 Ah로부터 열화 추정
- **공식**: `SOH = 100 - (degradation × (cum_charge + cum_discharge) / (2 × original_capacity))`
- **degradation 계수**: NMC: 0.10, LFP: 0.05, NCA: 0.12 (% / 1000 사이클)
- **신뢰도**: 0.75
- **제약**: 온도, 충전 속도 영향 미반영

### Method 3: Energy Counting (energy_counting)
- **설명**: 누적 kWh로부터 열화 추정
- **신뢰도**: 0.70
- **제약**: Method 2와 유사

### Method 4: OCV-SOC 일관성 (ocv_soc_consistency)
- **설명**: 휴지 기간 OCV와 SOC 관계로부터 열화 판단
- **신뢰도**: unrated (전제조건 충족 시에만 의미)
- **전제조건**: 30분 이상 휴지, SOC-OCV 기준 커브
- **제약**: 휴지 조건 충족 어려움, 온도 보정 필요

### Method 5: 내부 저항 기반 (resistance_based)
- **설명**: 전류 스텝 시 ΔV/ΔI로 내부 저항 계산
- **신뢰도**: unrated
- **전제조건**: 충분한 전류 변화 (>10A), 동기화 샘플링
- **제약**: 동적 데이터 필요, 정적 스캔 부적합

### Method 6: 누적 처리량 휴리스틱 (throughput_heuristic)
- **설명**: 누적 처리량/주행 시간 기반 단순 추정
- **신뢰도**: 0.50 (폴백)
- **제약**: 사용 패턴 차이 미반영, 정확도 낮음

### 연속 학습 (Continuous Learning)
- 모든 SOH 결과를 `soh_results` 테이블에 저장
- BMS SOH를 ground truth로 사용하여 오차 학습
- `LearnedFormula`에 방법별 보정 공식 저장 (Ridge Regression)
- 자동 재훈련 임계값: Method 0: 50개, Method 1: 30개, Method 2-3: 40개, Method 4-5: 20개, Method 6: 10개

