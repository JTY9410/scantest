# Tesla 지원 기능

## 개요

scantest v2.2.0부터 Tesla Model 3/Y 차량의 CAN 로그 분석을 지원합니다.

## 지원 기능

### 1. 차량 판별

- **VIN 디코딩**: 0x405 멀티플렉스에서 VIN 추출 및 해석
  - WMI (5YJ, 7SA, LRW, XP7 등) 검증
  - 모델 코드 (4번째 자리: 3/Y/S/X)
  - 연식 코드 (10번째 자리)
  
- **CAN ID 패턴**: Tesla 고유 ID (0x405, 0x7FF, 0x401, 0x352, 0x332) 존재 확인

- **Model 3/Y vs S/X 구분**: VIN 및 CAN ID 패턴 분석

### 2. 신호 해석

#### 핵심 신호

| CAN ID | 신호 | 설명 |
|--------|------|------|
| 0x352 | BMS 에너지 상태 | 공칭 만충/잔여 에너지, 버퍼 (신형 펌웨어 다중화) |
| 0x292 | SOC | 최소/표시/최대/평균 SOC, BOL 에너지 |
| 0x401 | 브릭 전압 | 96개 브릭 전압 (mux 0-31 × 3) |
| 0x332 | 요약 | 셀 온도/전압 최고/최저 (신형 펌웨어) |
| 0x132 | 팩 전압/전류 | HV 배터리 전압, 전류 |
| 0x2B4 | 12V/DC-DC | LV 전압, HV 버스, DC-DC 전류 |
| 0x3D2 | 누적 에너지 | 충전/방전 누적 kWh |
| 0x3B6 | 주행거리 | 오도미터 (주행 시) |
| 0x257 | 속도 | 차속 (주행 시) |
| 0x212 | BMS 상태 | 접촉기, HVIL, 절연저항 |
| 0x320 | BMS 알람 | 경보 매트릭스 |

#### 신형 펌웨어 지원

- 0x352: 구형 vs 신형 다중화 자동 판별
- 0x332: newer firmware layout (byte[3] <= byte[4] <= byte[2])
- 0x401: flag 0x2A (3개) / 0x02 (1개)

### 3. SOH (State of Health) 산정

#### 계산식

```
SOH = (현재 공칭 만충 에너지 / 기준 공칭 만충 에너지) × 100
```

#### 기준 용량 우선순위

1. **차량 신호 BOL**: 0x292 BOL 에너지가 정상 범위(40-120 kWh)이면 우선 사용
2. **기준 용량 테이블**: `battery_reference_capacity` 테이블 조회
   - `official` / `government`: 공식 SOH로 판정에 사용
   - `community`: 참고치로만 표시 (판정보류)
3. **기준 없음**: SOH 산정불가 → 판정보류

#### 교차 검증

- 잔여 에너지 ÷ SOC로 만충 추정
- 편차 5% 초과 시 경고

### 4. 측정불가 처리

다음 신호는 차량 상태에 따라 미송출:

- **주행거리/속도**: 드라이브 인버터 비활성 시
- **절연저항**: SUPPORT 모드에서 0 고정
- **모듈별 온도**: 브로드캐스트 없음 (UDS 필요)
- **DTC**: 진단 요청 없음

원인을 보고서에 명시하고 판정보류 처리.

### 5. 정의 불일치 차단

펌웨어 변경으로 DBC와 다른 신호는 자동 차단:

- 0x312, 0x2D2, 0x212 minPackT, 0x261, 0x2E1 등
- 이상값을 결과에 쓰지 않고 "정의 불일치" 표시

## 출처 및 라이선스

### DBC 정의

- **joshwardell/model3dbc** (commit c56c113)
  - Repository: https://github.com/joshwardell/model3dbc
  - License: MIT
  - Files: Model3CAN.dbc

- **commaai/opendbc** (commit 27fa1c5)
  - Repository: https://github.com/commaai/opendbc/tree/master/opendbc/dbc
  - License: MIT
  - Files: tesla_model3_party.dbc, tesla_model3_vehicle.dbc, tesla_can.dbc, tesla_powertrain.dbc

### 신형 펌웨어 정의

- **dalathegreat/Battery-Emulator** (commit 0808398)
  - Repository: https://github.com/dalathegreat/Battery-Emulator
  - License: GPL-3.0
  - File: Software/src/battery/TESLA-BATTERY.cpp
  - Signals: 0x352, 0x332, 0x401, 0x132, 0x2B4, 0x292, 0x320, 0x3A4, 0x31E, 0x7AA

### VIN 디코더

- **NHTSA vPIC**: https://vpic.nhtsa.dot.gov/api/ (공식)

## 기준 용량 데이터

현재 등록된 기준값 (모두 커뮤니티 출처):

| 모델 | 연식 | 트림 | 기준 (kWh) | 출처 |
|------|------|------|------------|------|
| Model 3 | 2018-2021 | Long Range | 74.0 | commaai/opendbc DBC 라벨 |
| Model 3 | 2019-2021 | Standard Range Plus | 54.0 | commaai/opendbc 참고 |
| Model Y | 2020-2023 | Long Range | 75.0 | commaai/opendbc 참고 |

**주의**: 
- 공식 1차 문서 미확인으로 모두 `community` 타입
- 이 값으로는 SOH를 확정하지 않고 참고치로만 표시
- 판정은 보류 처리

## 사용 예시

### 업로드

```python
# PCAN CSV 업로드
POST /admin/scan/upload
Content-Type: multipart/form-data

file: tesla_log.csv
car_no: 12가3456
```

### 판별 및 해석

```python
from app.modules.tesla.detect import is_tesla, detect_model, extract_vin_from_frames
from app.modules.tesla.decode import decode_0x352_energy, decode_0x401_brick_voltages
from app.modules.tesla.soh import calculate_soh

# 프레임 로드
frames = load_can_frames('tesla_log.csv')

# 판별
if is_tesla(frames):
    vin = extract_vin_from_frames(frames)
    model = detect_model(frames, vin)
    
    # 신호 해석
    energy = decode_0x352_energy(filter_frames(frames, 0x352))
    bricks = decode_0x401_brick_voltages(filter_frames(frames, 0x401))
    
    # SOH 계산
    soh = calculate_soh(
        current_nominal_full=energy['nominal_full_pack_energy'],
        manufacturer='Tesla',
        model=model,
        year=2020
    )
```

## 테스트

```bash
# Tesla 테스트 실행
pytest tests/tesla/ -v

# 전체 테스트
pytest
```

## 제한사항

- **지원 모델**: Model 3/Y (S/X는 ID 패턴이 다름, 향후 추가 예정)
- **로그 형식**: PCAN CSV, 11bit 표준 ID
- **펌웨어**: 신형 펌웨어 정의 (2021년 이후 BMS)
- **기준 용량**: 공식 출처 미확보로 현재 판정보류

## 참고

- Tesla는 공식 CAN 사양을 공개하지 않음
- DBC는 커뮤니티 역공학 자료 (비공식)
- 펌웨어별로 배치가 달라질 수 있음
- 교차 검증이 된 값만 판정에 사용
