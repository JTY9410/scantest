# CAN / UDS / BMS Reverse Engineering 통합 개별 요구사항

> **대상 개발환경:** Cursor\
> **목적:** BMS CAN TRC, G-Scan 통신 TRC, G-Scan 결과 및 선택적 CAN/BMS
> 소스코드를 교차 분석하여 CAN/UDS 신호 정의와 변환식을 역산하고 재사용
> 가능한 Decoder를 구축한다.

------------------------------------------------------------------------

## 0. 프로젝트 공통 원칙

-   본 프로젝트는 단순히 CAN Payload에서 우연히 동일한 숫자를 찾는
    프로그램이 아니다.
-   다음 독립 증거를 결합한다.
    -   **Evidence A:** 실제 BMS CAN TRC
    -   **Evidence B:** G-Scan 사용 중 수집한 CAN TRC
    -   **Evidence C:** G-Scan 최종 표시값
    -   **Evidence D:** CAN/BMS/진단 관련 소스코드(존재하는 경우)
-   최종적으로 다음 흐름을 재현해야 한다.

``` text
RAW CAN / Diagnostic CAN
        ↓
CAN ID / Request / Response
        ↓
ISO-TP Reassembly
        ↓
UDS Service / DID / PID
        ↓
Payload / Byte / Bit Position
        ↓
Endian / Signed
        ↓
Raw Value
        ↓
Scale / Offset / Formula
        ↓
Physical Value
        ↓
G-Scan Ground Truth 비교
        ↓
Cross Validation
        ↓
Reusable Decoder
```

-   확인된 사실과 가설을 반드시 분리한다.
-   기존 현대/기아 CAN 정의, DBC, DID 정보를 사전 정답으로 가정하지
    않는다.
-   단일 값 일치만으로 신호를 확정하지 않는다.
-   `UNKNOWN`을 추측으로 채우지 않는다.
-   각 단계는 **구현 → 실제 데이터 실행 → 검증 → 결과 저장** 후 다음
    단계로 진행한다.
-   각 요구사항 완료 후 임의로 다음 요구사항까지 진행하지 않는다.
-   중간 결과는 `output/`에 저장하여 다음 단계에서 재사용한다.

------------------------------------------------------------------------

# 요구사항 01 --- 프로젝트 초기화 및 입력 데이터 Inventory

## Define

Automotive CAN/UDS/BMS Reverse Engineering 전문 시니어 Python 개발자의
관점으로 수행한다.

## Intend

입력 데이터의 실제 형식과 프로젝트 구조를 먼저 확정한다.

## Rule

-   파일명을 코드에 고정하지 않는다.
-   입력 디렉터리를 탐색하여 자동 분류한다.
-   TRC 형식을 추측하지 않는다.

## 작업

-   다음 확장자를 탐색한다.
    -   `.trc`, `.pdf`
    -   `.c`, `.h`, `.cpp`, `.hpp`, `.py`
    -   `.dbc`, `.arxml`, `.xml`, `.a2l`
    -   `.json`, `.yaml`, `.yml`, `.csv`, `.txt`
-   각 파일의 filename, extension, size, encoding, 예상 용도를 기록한다.
-   TRC header와 초기 30\~50개 메시지를 분석한다.
-   PDF 페이지 구조를 확인한다.
-   소스코드가 있으면 프로젝트 디렉터리 구조를 매핑한다.

## 프로젝트 구조

``` text
can_reverse_engineer/
    main.py
    parsers/
    can/
    diagnostic/
    reverse/
    source_analysis/
    validation/
    database/
    reports/
    config/
    output/
    tests/
```

## 산출물

-   `output/file_inventory.json`
-   `output/file_analysis.md`

## 완료 보고

`[FILES FOUND] [TRC STRUCTURE] [PDF STRUCTURE] [SOURCE CODE FOUND] [ISSUES] [NEXT STEP]`

------------------------------------------------------------------------

# 요구사항 02 --- 범용 TRC Parser

## 목표

두 TRC를 동일한 내부 모델로 정규화한다.

## 데이터 모델

``` python
@dataclass
class CanFrame:
    timestamp: float
    channel: int | str
    can_id: int
    extended: bool
    direction: str | None
    dlc: int
    data: bytes
    source: str
```

## 요구

-   실제 TRC header/version에 맞춰 Parser를 구현한다.
-   Classical CAN / CAN-FD 여부를 가능한 범위에서 식별한다.
-   Standard / Extended ID를 구분한다.
-   파싱 오류 라인을 버리지 말고 기록한다.
-   전체 frame 수, timestamp 범위, CAN ID 수, DLC 분포, 성공률을
    검증한다.

## 산출물

-   `output/bms_can_normalized.csv`
-   `output/gscan_can_normalized.csv`
-   `output/trc_parse_errors.csv`
-   `tests/test_trc_parser.py`

------------------------------------------------------------------------

# 요구사항 03 --- CAN ID Profiling Engine

## 목표

각 CAN ID의 통신 특성을 정량화한다.

## 계산

-   frame_count, frequency
-   average/min/max period
-   DLC
-   unique payload count
-   byte별 min/max/mean/std/entropy/change rate
-   bit별 change rate
-   payload entropy

## 후보 분류

`STATIC`, `PERIODIC`, `SLOW_CHANGING`, `FAST_CHANGING`, `STATE`,
`COUNTER`, `CHECKSUM`, `DIAGNOSTIC_CANDIDATE`, `UNKNOWN`

## 추가

-   Alive/Rolling Counter 후보 탐지
-   Checksum/CRC 후보 Byte 탐지
-   센서 검색 시 counter/checksum 후보를 별도 표시

## 산출물

-   `output/bms_can_profile.csv`
-   `output/gscan_can_profile.csv`
-   `output/can_profile_report.md`

------------------------------------------------------------------------

# 요구사항 04 --- BMS ↔ G-Scan Differential Analysis

## 목표

G-Scan 연결로 추가된 통신을 식별한다.

``` text
COMMON_IDS = BMS_IDS ∩ GSCAN_IDS
BMS_ONLY_IDS = BMS_IDS - GSCAN_IDS
GSCAN_ONLY_IDS = GSCAN_IDS - BMS_IDS
```

## 분석

특히 `GSCAN_ONLY_IDS`에서: - 발생 주기 - payload pattern - Request
가능성 - Response 가능성 - 상대 CAN ID - timestamp 관계 - 반복 polling
여부

를 분석한다.

## 산출물

-   `output/can_id_difference.csv`
-   `output/differential_analysis.md`

------------------------------------------------------------------------

# 요구사항 05 --- Diagnostic / UDS 자동 탐지

## 목표

G-Scan TRC의 진단 통신 구조를 찾는다.

## 후보 서비스

-   `0x10`, `0x11`, `0x14`, `0x19`
-   `0x22`, `0x23`, `0x27`
-   `0x2E`, `0x2F`, `0x31`, `0x3E`

UDS라고 선확정하지 않는다.

## 검증

-   Positive Response `request_service + 0x40`
-   Negative Response `7F SERVICE NRC`
-   timestamp 기반 Request → Response
-   반복되는 CAN ID pair
-   DID 일관성
-   polling consistency

## 산출물

-   `output/diagnostic_transactions.csv`
-   `output/diagnostic_candidates.md`

------------------------------------------------------------------------

# 요구사항 06 --- ISO-TP Reconstruction

## 목표

진단 Multi-frame 응답을 원본 Payload로 재구성한다.

## 지원

-   Single Frame
-   First Frame
-   Consecutive Frame
-   Flow Control

## 검증

-   Sequence Number
-   Payload Length
-   누락 Frame
-   비정상 순서

## 집중 분석

셀 전압 1\~72와 같은 대용량 데이터가 ISO-TP 응답에 존재하는지 조사한다.

## 산출물

-   `output/isotp_transactions.csv`
-   `output/isotp_report.md`
-   ISO-TP unit tests

------------------------------------------------------------------------

# 요구사항 07 --- G-Scan Ground Truth Database

## 목표

G-Scan PDF를 Reverse Engineering의 정답 데이터로 구조화한다.

## 데이터 모델

``` text
sensor_name
normalized_name
value
unit
category
page
tolerance
```

## Category

`BATTERY`, `CELL_VOLTAGE`, `TEMPERATURE`, `RESISTANCE`, `POWER`, `SOC`,
`SOH`, `LIFETIME`, `12V`, `STATE`, `RELAY`, `OTHER`

## 현재 주요 Anchor 예

-   Battery SOC: 53.5 %
-   Battery Pack Current: 5.5 A
-   Battery Pack Voltage: 263.2 V
-   Battery Max Temperature: 28 °C
-   Battery Min Temperature: 27 °C
-   Battery Ambient Temperature: 26 °C
-   Cell Voltage 1\~72: 약 3.64 V
-   SOH: 100 %
-   Max Charge Power: 49 kW
-   Max Discharge Power: 64 kW

표시값의 반올림을 고려해 tolerance를 둔다.

## 산출물

-   `output/gscan_ground_truth.csv`
-   `output/gscan_ground_truth.json`

------------------------------------------------------------------------

# 요구사항 08 --- Raw Byte Reverse Search Engine

## 목표

Ground Truth와 CAN/ISO-TP Payload의 가능한 수치 관계를 전수 탐색한다.

## Byte Width

1 / 2 / 3 / 4 byte

## 표현

-   Big Endian / Little Endian
-   Unsigned / Signed Two's Complement

## 공식 후보

``` text
physical = raw * scale + offset
physical = raw / divisor
physical = (raw + offset) * scale
physical = (raw - offset) * scale
physical = A * raw + B
```

## 대표 Scale

`1, 0.5, 0.25, 0.125, 0.1, 0.05, 0.02, 0.01, 0.005, 0.001`

목록에 제한하지 않는다.

## 산출물 필드

sensor, can_id, did, byte_start, byte_length, endian, signed, raw,
scale, offset, decoded, target, error, score

## 산출물

-   `output/raw_signal_candidates.csv`

모든 결과는 이 단계에서는 `CANDIDATE`다.

------------------------------------------------------------------------

# 요구사항 09 --- Anchor Signal Reverse Engineering

## 우선순위

1.  Battery SOC
2.  Pack Voltage
3.  Pack Current
4.  Temperature
5.  Cell Voltage
6.  SOH
7.  Charge/Discharge Power
8.  Accumulated Ah/kWh

## Signal별 확인

-   CAN ID
-   Broadcast / Diagnostic
-   Request ID / Response ID
-   Service / DID
-   ISO-TP 여부
-   Byte / Bit Position
-   Endian
-   Signed
-   Raw
-   Scale / Offset
-   Formula
-   Decoded Value
-   G-Scan Value
-   Error
-   Confidence

Anchor 발견 시 동일 DID/Payload의 주변 ±32 byte를 기본 범위로 조사하여
관련 신호 군집을 찾는다.

## 산출물

-   `output/anchor_analysis.csv`
-   `output/anchor_analysis.md`

------------------------------------------------------------------------

# 요구사항 10 --- Cell Voltage 1\~72 반복 구조 탐지

## 목표

72개 셀 데이터의 반복 배열 구조를 역산한다.

## 후보

-   1-byte array
-   16-bit BE / LE
-   24-bit
-   packed array
-   multiple DID
-   multiple ISO-TP responses

## 원칙

셀 하나가 우연히 일치하는 후보보다 **72개 전체를 동일 공식으로 설명하는
후보**에 높은 점수를 부여한다.

각 셀의 물리 범위, 평균, 최소/최대, 순서 및 G-Scan 결과를 비교한다.

## 산출물

-   `output/cell_voltage_candidates.csv`
-   `output/cell_array_analysis.md`

------------------------------------------------------------------------

# 요구사항 11 --- CAN Source Code Static Analysis

## 목표

소스코드가 제공되면 Trace 분석과 독립적으로 CAN 정의를 역추적한다.

소스가 없으면 `SKIPPED`로 기록하고 프로젝트를 중단하지 않는다.

## 탐색

-   CAN ID / TX / RX
-   CAN Driver / Interface
-   ISO-TP / UDS
-   DID / PID
-   BMS
-   Encoder / Decoder
-   Packing / Unpacking

## 코드 요소

`data[x]`, `<<`, `>>`, `&`, `|`, `memcpy`, `struct`, `union`, `enum`,
signed/unsigned integer types

## 함수 후보

`can_send`, `can_write`, `can_transmit`, `can_receive`, `CanIf`,
`CanTp`, `PduR`, `Com_SendSignal`, `Com_ReceiveSignal` 및 의미상 유사
함수.

가능하면 clang AST 또는 tree-sitter를 사용하고 불가능하면 정적
parser/regex로 fallback한다.

## 산출물

-   `output/source_code_map.md`
-   `output/code_can_ids.csv`
-   `output/code_signal_candidates.csv`

------------------------------------------------------------------------

# 요구사항 12 --- Source Code Packing / Formula Reconstruction

## 목표

코드에서 실제 Byte Mapping과 물리 변환식을 추출한다.

예:

``` c
raw = (data[4] << 8) | data[5];
voltage = raw * 0.1;
```

다음으로 정규화:

``` text
byte_start = 4
byte_length = 2
endian = BIG
signed = FALSE
scale = 0.1
offset = 0
```

## 추적

-   Bit Shift / Mask
-   Endian
-   Signed Cast
-   Scale / Offset
-   Division
-   Macro / Constant
-   Struct / Union / Enum
-   `memcpy`
-   함수 간 데이터 흐름

## Constant Propagation

`#define SCALE 10` 후 `value = raw / SCALE`이면 `scale=0.1`로
정규화한다.

## Inter-procedural

`parse → decode → convert → set_value`처럼 함수 경계를 넘어 추적한다.

## 산출물

-   `output/code_signal_definitions.csv`

------------------------------------------------------------------------

# 요구사항 13 --- UDS / DID Source Code Analysis

## 탐색

-   `case 0x22`
-   `ReadDataByIdentifier`
-   `switch(did)`
-   `case DID_*`
-   `Diag_ReadData`
-   `UDS_ReadDID`
-   `response[]`
-   `tx_buffer[]`

## 목표 Call Flow

``` text
CAN RX
 ↓
ISO-TP
 ↓
UDS
 ↓
Service
 ↓
DID Handler
 ↓
BMS Function
 ↓
Signal Conversion
 ↓
Response Buffer
 ↓
ISO-TP
 ↓
CAN TX
```

## DID DB

DID, Service, Function, Response Length, Signal, Byte, Endian, Signed,
Scale, Offset, Formula

## 산출물

-   `output/code_did_database.csv`
-   `output/uds_call_graph.md`

------------------------------------------------------------------------

# 요구사항 14 --- Trace ↔ Code ↔ G-Scan 3중 교차검증

## 목표

세 독립 분석 결과를 Signal 단위로 비교한다.

``` text
                     TRACE   CODE   GSCAN
CAN ID
DID
Byte / Bit
Endian
Signed
Scale
Offset
Formula
Physical Value
```

## 판정

-   Trace + Code + G-Scan 일치 → 최고 수준 증거
-   Trace + G-Scan 일치 → 높은 후보
-   Code + Trace 일치 → 높은 후보
-   단일 숫자 일치 → 낮은 증거
-   서로 충돌 → `CONFLICT`

## 충돌 조사

-   SW/ECU Version
-   CAN Channel
-   Transport Header
-   Byte Offset
-   코드 버전
-   Parser 오류

한쪽을 임의로 선택하지 않는다.

## 산출물

-   `output/evidence_matrix.csv`
-   `output/conflicts.csv`
-   `output/cross_validation_report.md`

------------------------------------------------------------------------

# 요구사항 15 --- Confidence Scoring Engine

## 기본 모델

``` text
confidence =
0.20 * physical_value_match +
0.15 * temporal_consistency +
0.15 * diagnostic_structure +
0.15 * source_code_match +
0.10 * formula_consistency +
0.10 * neighboring_signal_consistency +
0.10 * multi_dataset_validation +
0.05 * physical_plausibility
```

가중치는 YAML에서 변경 가능하게 한다.

## Status

-   `CONFIRMED`
-   `HIGH_CONFIDENCE`
-   `MEDIUM_CONFIDENCE`
-   `LOW_CONFIDENCE`
-   `CONFLICT`
-   `UNKNOWN`

`CONFIRMED`는 숫자 threshold만으로 자동 부여하지 않고 충분한 독립 증거를
요구한다.

## 산출물

-   `output/scored_signals.csv`

------------------------------------------------------------------------

# 요구사항 16 --- Physical Consistency Validator

## 검증 예

-   Pack Voltage ↔ Cell Voltage 관계
-   Max Cell ≥ Min Cell
-   Max Temperature ≥ Min Temperature
-   SOC 합리적 범위
-   SOH 합리적 범위
-   Power ↔ Voltage × Current 관계
-   Charge/Discharge 부호
-   누적 Ah/kWh의 시간적 일관성

## 판정

`PASS`, `WARNING`, `FAIL`, `INSUFFICIENT_DATA`

물리적 타당성은 **보조 증거**이며 CAN 정의의 직접 증거로 사용하지
않는다.

## 산출물

-   `output/physical_validation.csv`

------------------------------------------------------------------------

# 요구사항 17 --- Multi-Dataset Validation / Hold-out

## 목표

추가 데이터가 들어올수록 Signal 정의의 정합도를 높인다.

## Dataset 구조

``` text
dataset/
    capture_001/
    capture_002/
    capture_003/
```

각 capture는 가능한 경우 BMS TRC, G-Scan TRC, G-Scan Ground Truth를
포함한다.

## 검증

여러 Dataset에서 동일한: - CAN ID - DID - Byte - Endian - Signed -
Scale - Offset

이 유지되는지 검사한다.

## 분리

-   Training: 공식 발견
-   Validation: 후보 선택
-   Hold-out: 최종 검증

Hold-out 데이터는 공식 탐색에 사용하지 않는다.

## 산출물

-   `output/multi_dataset_validation.csv`

------------------------------------------------------------------------

# 요구사항 18 --- Active Reverse Engineering / 추가 캡처 계획

## 목표

현재 데이터만으로 확정할 수 없는 항목에 대해 가장 정보량이 높은 추가
캡처 조건을 제안한다.

예: - Current signed 여부 → 충전(+), 정차(0), 방전(-) 데이터 - SOC scale
→ 서로 다른 SOC 구간 - Temperature → cold / normal / hot - Voltage →
READY OFF / READY ON / 충전 상태

## Signal별 기록

-   현재 후보
-   불확실한 요소
-   추가 데이터
-   추천 차량 조건
-   해당 캡처가 구분할 가설

## 산출물

-   `output/additional_capture_plan.md`

------------------------------------------------------------------------

# 요구사항 19 --- Signal / Diagnostic Database 및 Decoder 생성

## 목표

충분히 검증된 정의를 재사용 가능한 Decoder로 변환한다.

## API

``` python
decode_can_frame(
    can_id,
    payload
)

decode_diagnostic_response(
    request_id,
    response_id,
    service,
    did,
    payload
)
```

## 반환 예

``` json
{
  "BatterySOC": {
    "value": 53.5,
    "unit": "%",
    "confidence": 0.98
  }
}
```

## 원칙

-   UNKNOWN을 확정 Signal처럼 Decode하지 않는다.
-   신호 정의와 confidence/evidence를 함께 저장한다.

## 산출물

-   `output/signal_database.json`
-   `output/diagnostic_database.json`
-   검증된 Broadcast Signal이 충분하면 `output/candidate.dbc`
-   추론된 DBC 항목에는 inference/confidence metadata를 남긴다.

------------------------------------------------------------------------

# 요구사항 20 --- End-to-End Validation

## Pipeline

``` text
NEW TRC
 ↓
Parser
 ↓
CAN / Diagnostic Detection
 ↓
ISO-TP
 ↓
DID
 ↓
Signal Database
 ↓
Decoder
 ↓
Physical Values
 ↓
G-Scan Ground Truth Comparison
```

## Signal별 결과

-   Sensor
-   Decoded
-   G-Scan
-   Absolute Error
-   Relative Error
-   Confidence
-   Status

## 전체 지표

-   Signal Detection Rate
-   Decode Success Rate
-   MAE
-   RMSE
-   Confirmed Signal Count
-   Unknown Signal Count
-   Conflict Count

## 역검증

가능하면:

``` text
Physical Value
 ↓
Inverse Formula
 ↓
Raw
 ↓
Byte Packing
 ↓
Payload
```

도 수행하여 실제 Payload와 비교한다.

## 산출물

-   `output/final_validation.csv`
-   `output/final_validation_report.md`

------------------------------------------------------------------------

# 요구사항 21 --- 최종 프로그램 통합

## CLI 예

``` bash
python main.py analyze ./dataset/capture_001
python main.py reverse ./dataset/capture_001
python main.py validate ./dataset/capture_002
python main.py decode new_trace.trc
python main.py report
```

## 최종 Workflow

``` text
INPUT
 ↓
FILE DETECTION
 ↓
TRC PARSER
 ↓
CAN PROFILER
 ↓
DIFFERENTIAL ANALYSIS
 ↓
DIAGNOSTIC DETECTOR
 ↓
ISO-TP
 ↓
G-SCAN GROUND TRUTH
 ↓
RAW REVERSE SEARCH
 ↓
SOURCE CODE ANALYSIS
 ↓
CROSS VALIDATION
 ↓
CONFIDENCE SCORING
 ↓
SIGNAL DATABASE
 ↓
DECODER
 ↓
VALIDATION
 ↓
REPORT
```

## 통합 요구

-   단계별 logging
-   중간 결과 보존
-   일부 단계 실패 시 가능한 분석은 계속
-   모든 UNKNOWN 기록
-   모든 unit/integration test 실행
-   README 작성

README: - 설치 - 사용법 - 입력 데이터 구조 - Pipeline - 결과 해석 -
Confidence 의미 - 추가 Dataset 등록법 - 새로운 차량 적용법 - 알려진 한계

------------------------------------------------------------------------

# 요구사항 22 --- 공통 False Positive 방지 규칙

모든 단계에 다음 규칙을 적용한다.

1.  단일 숫자 일치만으로 확정 금지.
2.  여러 timestamp에서 공식 재현 여부 확인.
3.  Request/Response 구조 검증.
4.  동일 DID의 주변 Signal 일관성 검증.
5.  Endian/Scale이 관련 Signal에서도 합리적인지 검증.
6.  Counter/Checksum Byte를 센서로 오인하지 않도록 검증.
7.  코드가 존재하면 packing/unpacking 로직과 비교.
8.  코드 정의만 존재하고 Trace에서 관측되지 않으면 사용 중인 Signal로
    확정 금지.
9.  물리적으로 그럴듯하다는 이유만으로 확정 금지.
10. 여러 Dataset에서 동일 공식이 유지되는지 검증.
11. Hold-out Trace에서 재현되면 Confidence를 상승.
12. 충돌하는 증거를 숨기지 말고 `CONFLICT`로 기록.

------------------------------------------------------------------------

# 요구사항 23 --- 공통 분석 기록 형식

각 Reverse Engineering 작업은 내부 장문의 사고과정 대신 다음의 **재현
가능한 기술 근거**를 기록한다.

``` text
[OBSERVATION]
실제 데이터/코드에서 확인된 내용

[HYPOTHESIS]
현재 후보 해석

[TEST]
가설 검증 방법

[EVIDENCE]
Trace / Code / G-Scan 중 어떤 증거를 사용했는지

[RESULT]
검증 결과

[CONFIDENCE]
0.0 ~ 1.0

[STATUS]
CONFIRMED / HIGH_CONFIDENCE / MEDIUM_CONFIDENCE /
LOW_CONFIDENCE / CONFLICT / UNKNOWN

[NEXT ACTION]
다음 검증 방법
```

------------------------------------------------------------------------

# 요구사항 24 --- 최종 Signal 정의 형식

각 Signal은 최종적으로 가능한 범위에서 다음 정보를 가진다.

``` text
sensor_name
unit

communication_type
can_id

request_can_id
response_can_id

service
did

isotp

byte_start
byte_end

bit_start
bit_length

endian
signed

raw_example

scale
offset
formula

decoded_example
gscan_target

absolute_error
relative_error

trace_evidence
code_evidence
gscan_evidence
multi_dataset_evidence

source_file
source_function
source_line

confidence
status
notes
```

------------------------------------------------------------------------

# 요구사항 25 --- 최종 성공 조건

프로젝트 성공은 특정 값 하나를 맞히는 것이 아니다.

다음 전체 Pipeline이 새로운 데이터에서도 재현되어야 한다.

``` text
TRC RAW DATA
      ↓
Request / Response Detection
      ↓
ISO-TP Reassembly
      ↓
DID Identification
      ↓
Byte / Bit Mapping
      ↓
Endian / Signed Detection
      ↓
Scale / Offset Inference
      ↓
Physical Value
      ↓
G-Scan Ground Truth Comparison
      ↓
Source Code Cross Validation
      ↓
Multi-Dataset / Hold-out Validation
      ↓
Reusable Decoder
```

최종적으로 새로운 TRC 파일을 입력했을 때 G-Scan 없이도 **검증된 범위의
BMS 센서값을 계산**할 수 있어야 한다.

------------------------------------------------------------------------

# Cursor 실행 순서

``` text
REQ-01  입력 분석
  ↓
REQ-02  TRC Parser
  ↓
REQ-03  CAN Profiling
  ↓
REQ-04  Differential Analysis
  ↓
REQ-05  Diagnostic Detection
  ↓
REQ-06  ISO-TP
  ↓
REQ-07  G-Scan Ground Truth
  ↓
REQ-08  Raw Reverse Search
  ↓
REQ-09  Anchor Reverse Engineering
  ↓
REQ-10  Cell Array Detection
  ↓
REQ-11  Source Code Analysis
  ↓
REQ-12  Code Formula Reconstruction
  ↓
REQ-13  UDS/DID Code Analysis
  ↓
REQ-14  3-Way Cross Validation
  ↓
REQ-15  Confidence
  ↓
REQ-16  Physical Validation
  ↓
REQ-17  Multi-Dataset / Hold-out
  ↓
REQ-18  Additional Capture Plan
  ↓
REQ-19  Decoder / DB
  ↓
REQ-20  End-to-End Validation
  ↓
REQ-21  Application Integration
```

------------------------------------------------------------------------

# Cursor 작업 제어 규칙

-   처음 실행 시 **REQ-01만 수행한다.**
-   사용자가 다음 요구사항 진행을 지시하기 전까지 다음 단계로 넘어가지
    않는다.
-   이전 단계 산출물을 삭제하거나 무시하지 않는다.
-   각 단계 시작 전에 필요한 이전 산출물이 존재하는지 확인한다.
-   이전 결과가 잘못된 것으로 확인되면 해당 단계부터 재실행하고 영향받는
    후속 산출물을 invalid 처리한다.
-   실제 실행 결과가 없는 구현을 `완료`라고 보고하지 않는다.
-   확인되지 않은 CAN ID/DID/Scale/Offset을 임의 확정하지 않는다.
-   발견하지 못한 것은 명확하게 `UNKNOWN`으로 남긴다.
-   모든 분석 결과는 나중에 사람이 근거를 재검토할 수 있도록 Evidence를
    보존한다.

------------------------------------------------------------------------

# 최초 실행 지시

현재는 **REQ-01 --- 프로젝트 초기화 및 입력 데이터 Inventory만
수행한다.**

완료 후 아래 형식으로 보고하고 정지한다.

``` text
[REQ-01 STATUS]

[FILES FOUND]

[TRC STRUCTURE]

[PDF STRUCTURE]

[SOURCE CODE FOUND]

[GENERATED FILES]

[ISSUES]

[VALIDATION RESULT]

[NEXT RECOMMENDED REQUIREMENT]
```

사용자의 승인 없이 REQ-02로 진행하지 않는다.
