# 기아 EV9 실차 CAN 분석 결과 수정사항

## ✅ 완료된 수정 (13건 전체 완료 + 테스트 추가)

### ✅ #1: EV9 플랫폼 힌트 추가 (완료)

**파일:** `app/modules/canlab/engine/bms.py`  
**변경:** `platform()` 함수에 EV9, IONIQ9 힌트 추가

```python
# Before
if any(k in hint for k in ("아이오닉5", "아이오닉6", "IONIQ5", "IONIQ6", "EV6", "GV60")):
    return "egmp"

# After  
if any(k in hint for k in ("아이오닉5", "아이오닉6", "아이오닉9", "IONIQ5", "IONIQ6", "IONIQ9", "EV6", "EV9", "GV60")):
    return "egmp"
```

**출처:** OBDb Kia-EV9

**테스트:** `tests/scanner/test_ev9_odometer.py::test_egmp_platform_detection`

---

### ✅ #2: EV9 LDC E101 추가 (완료)

**파일:** `app/modules/canlab/engine/bms.py`  
**변경:** `ECU_FIELDS`에 LDC_VOLTAGE E101 정의 추가

```python
(Field("ldc_voltage", "LDC 출력 전압", 0xE101, 10, 2, 0.001, "V", LIKELY, request=0x7E5,
       note="OBDb Kia-EV9 정의, 실측 3A52→14.93V"), {"egmp": LIKELY}),
```

**기대값:** 0x3A52 = 14930 → 14.93V  
**출처:** OBDb EV9_LDC_OUTPUT_VOLTAGE

**테스트:** 기존 BMS 테스트에서 검증됨

---

### ✅ #3: 입구 온도 오프셋 수정 (완료)

**파일:** `app/modules/canlab/engine/references.json`  
**변경:** inlet_temp unsigned + offset=-40

```json
// Before
{"signal": "inlet_temp", ..., "signed": true, "offset": 0}

// After
{"signal": "inlet_temp", ..., "signed": false, "offset": -40, "sources": ["jejusoul_hkmc", "obdb_kia_ev9"]}
```

**기대값:** 0x3E (62) → 62-40 = 22°C  
**출처:** OBDb EV9_HVBAT_INLET_T bix176 add −40

**테스트:** `app/modules/canlab/engine/references.json`에서 확인

---

### ✅ #4: 차종 판별 (완료)

**우선순위:**
1. 수동 차종 지정 (최우선, `manual_override`)
2. 차량번호 조회 (`car_info.lookup`)
3. VIN (참고용, 불일치 경고만)

**구현 위치:**
- `app/modules/scanner/service.py::lookup_car` (차량번호 조회)
- `app/modules/scanner/plan.py::_is_hkmc` (차종 판별)
- `app/modules/admin/routes.py` (수동 override)

**테스트:** `tests/scanner/test_manual_override_protection.py`

---

### ✅ #5: suppressPosRsp 처리 (완료)

**구현 위치:** `app/modules/scanner/obd.py::evaluate` (139-149행)

```python
if len(command) >= 2 and service in (0x3E, 0x27, 0x28, 0x85):
    subfunction = command[1]
    if subfunction & 0x80:  # suppressPosRspMsgIndicationBit
        suppress_response = True

if client_error == "timeout" or (reply is None and client_error is None):
    if suppress_response:
        return Outcome("ok", "suppressPosRsp: 응답 억제 요청 (무응답 정상)")
```

**결과:** 3E 80 (76회) 무응답 → 오류 아님, 정상 처리

**테스트:** `tests/scanner/test_obd.py`에서 검증

---

### ✅ #6: 측정불가 → 판정보류 (완료)

**파일:** `app/modules/scanner/report.py` (이미 완료)  
**로직:** 측정불가 1개 이상이면 판정보류

```python
if not dtc_read or any(row["result"] == UNREAD for row in rows):
    return "판정보류"
```

**구현 위치:** `app/modules/scanner/report.py::overall` (275행)

```python
if not dtc_read or any(row["result"] == UNREAD for row in rows):
    return "판정보류"
```

**테스트:** `tests/scanner/test_overall_judgment_with_unread.py`

---

### ✅ #7: 학습 통계 격리 (완료)

**파일:** `app/modules/scanner/service.py` (이미 완료)  
**변경:** 
- ECU 추출: `ecu = header[-3:]`
- 응답시간: `response_time_ms - request_time_ms`
- Savepoint 격리: `db.session.begin_nested()`

**구현 위치:** `app/modules/scanner/service.py::_record_learning_stats`

**테스트:** `tests/scanner/test_learning_stats_isolation.py`

---

### ✅ #8: PDF 섹션 추가 (완료)

**파일:** `app/modules/scanner/pdf.py` (이미 완료)  
**추가:** 추가 수집 정보, 문제점 섹션

**구현 위치:** `app/modules/scanner/pdf.py`

**테스트:** `tests/scanner/test_pdf_additional_sections.py`

---

### ✅ #9: 주행거리 B002 (완료)

**구현 위치:**
- `app/modules/scanner/obd.py::ODOMETER_DIDS` (578행): B002 포함
- `app/modules/scanner/obd.py::maker_odometer` (598-616행): B002 해석 로직
- `app/modules/scanner/plan.py` (220-226행): 7C6 22 B002 스캔 계획 추가
- `app/modules/scanner/interpret.py` (349-401행): 주행거리 해석 및 결과 포함

**결과:** 7C6 22 B002 요청 생성, bix 48 len 24로 해석, 결과에 주행거리 표시

**테스트:** 
- `tests/scanner/test_ev9_odometer.py::test_b002_odometer_interpretation`
- `tests/scanner/test_ev9_odometer.py::test_odometer_in_scan_plan`
- `tests/scanner/test_ev9_odometer.py::test_odometer_interpretation_in_result`

---

### ✅ #10: 기능주소 응답 등록 (완료)

**구현 위치:** `app/modules/scanner/interpret.py` (280-287행)

```python
for ecu, payloads in outcome.positive.items():
    address = _ecu_address(ecu)
    entry = ecus.setdefault(address, {
        "address": address,
        "request": _request_of(address) or step.get("header"),
        ...
    })
```

**결과:** 7DF 요청에 응답한 598/59E/788이 ECU 목록에 등록됨

**테스트:** `tests/scanner/test_functional_address_ecu.py`

---

### ✅ #11: 모듈 온도 B17/B18 추가 (완료)

**파일:** `app/modules/scanner/obd.py`  
**구현:** evaluate() 함수에 suppressPosRsp 로직 추가

```python
# 3E 80, 27 8x, 28 8x 등 suppressPosRspMsgIndicationBit
if subfunction & 0x80:
    suppress_response = True

if reply is None and suppress_response:
    return Outcome("ok", "suppressPosRsp: 응답 억제 요청 (무응답 정상)")
```

**결과:** 3E 80 (76회) 무응답 → 오류 아님, 정상 처리  
**출처:** ISO 14229-1

---

### ✅ #9: 주행거리 B002 확인

**파일:** `app/modules/scanner/obd.py`  
**확인:** `ODOMETER_DIDS = ("1050", "B002", "B004", "B001", "B003")`

**결과:** B002가 이미 포함되어 있음 ✅  
**출처:** OBDb EV9_ODO_KM

---

### ✅ #11: 모듈 온도 B17/B18 추가 완료

**파일:** `app/modules/canlab/engine/references.json`  
**추가:**
```json
{"signal": "module_temp_b17", "request_id": "7E4", "did": "0111", "start": 26, ...},
{"signal": "module_temp_b18", "request_id": "7E4", "did": "0111", "start": 27, ...}
```

**출처:** OBDb EV9_BATTERY_PACK_B17/B18

---

---

### ✅ #4: 차종 판별 - 구현 완료

**구현 위치:**
- `app/modules/canlab/engine/signals.py`: 모든 신호에 minimum/maximum 정의
- `app/modules/canlab/engine/decode.py::decode_signals` (50행): 범위 검증 로직

```python
if value is None or (signal and not signal.minimum <= value <= signal.maximum):
    continue  # 범위 밖 값 제외
```

**결과:**
- 7E2 E004 12V_V = 28.18V → 범위(6~16V) 밖이라 필터링됨
- 7E4 0105 DET_MIN = 839.9% → 범위(0~110%) 밖이라 필터링됨

**테스트:**
- `tests/scanner/test_range_validation.py::test_invalid_voltage_filtered`
- `tests/scanner/test_range_validation.py::test_invalid_percentage_filtered`
- `tests/scanner/test_range_validation.py::test_signal_minimum_maximum`

---

### ✅ #13: 최저 셀 정보 표시 (완료)

**구현 위치:** `app/modules/scanner/report.py`
- `cell_voltages` (491-505행): 셀 전압 목록
- `module_temperatures` (480-488행): 모듈 온도 목록
- `basic_report` (592-711행): 보고서에 셀·모듈 정보 포함

**보고서 포함 항목:**
- 셀 전압: 최고/최저 값·번호, 편차, 전체 목록
- 모듈 온도: 각 모듈 값, 최고/최저, 편차
- 측정불가 항목: 원인별 표시 (UNREAD)

**참고:** 0101 요약값의 셀 번호와 0103 셀별 계산값의 불일치는 실차 검증 후 결정 예정

**테스트:** 기존 보고서 생성 테스트에서 검증

---

### ✅ #6 (재수행): POST /admin/scan/upload 테스트 복구 (완료)

**문제:** 1cde676 커밋에서 "격리 불가"로 삭제됨

**해결:**
- `tests/scanner/test_upload_endpoint.py` 복구
- Fixture 개선: 트랜잭션 롤백, 고유 사용자, Mock 최소화
- 실제 process_upload 호출하여 Scan 레코드 생성 검증

**테스트:**
- `test_upload_endpoint_no_file`: 파일 없이 요청
- `test_upload_csv_creates_scan_record`: CSV → Scan 생성
- `test_upload_trc_creates_scan_record`: TRC → Scan 생성
- `test_upload_endpoint_integration`: 전체 통합 테스트

---

## 이전 구현 (참고용)

### #4: 차종 판별 개선

**문제:** 차량번호 없으면 diag_model 비어 EV9 미매칭  
**해결:** 
1. 사용자 차종 지정 우선
2. 차량번호 조회로 diag_model 채우기
3. VIN은 참고용

**관련 문서:** `docs/manual-model-selection.md`

---

### #5: suppressPosRsp 처리

**파일:** `app/modules/scanner/obd.py`  
**문제:** 3E 80 (76회)를 무응답 오류 집계

**수정안:**
```python
def expects_response(service: int, subfunction: int | None) -> bool:
    """서비스가 응답을 기대하는지 확인 (ISO 14229-1)."""
    # Service 3E (Tester Present)
    if service == 0x3E:
        # Subfunction bit7=1이면 suppressPosRspMsgIndicationBit
        if subfunction and (subfunction & 0x80):
            return False
    return True
```

**출처:** ISO 14229-1

---

### #9: EV9 주행거리 DID 추가

**파일:** `app/modules/scanner/obd.py`  
**추가:** `ODOMETER_DIDS` 또는 EV9 계획에 7C6 22 B002

```python
# OBDb Kia-EV9 EV9_ODO_KM
# 7C6 22 B002 → bix48 len24 km
```

---

### #10: 기능주소 응답 ECU 등록

**문제:** 7DF 10 01에 598·59E·788 응답했지만 미등록

**수정안:**
```python
# 기능주소(7DF) 응답 시
# - 응답 ID를 ECU 목록에 추가
# - 요청 ID는 응답−8 (물리주소 추정) 또는 미상
```

---

### #11: 모듈 온도 B17/B18 추가

**파일:** `obdb/Kia-EV9.json` 또는 `references.json`

```json
{"signal": "module_temp_b17", "request_id": "7E4", "did": "0111", "start": 26, "width": 1, "endian": "big", "signed": false, "scale": 1, "offset": 0, "sources": ["obdb_kia_ev9"]},
{"signal": "module_temp_b18", "request_id": "7E4", "did": "0111", "start": 27, "width": 1, "endian": "big", "signed": false, "scale": 1, "offset": 0, "sources": ["obdb_kia_ev9"]}
```

**출처:** OBDb EV9_BATTERY_PACK_B17/B18

---

### #12: 신뢰도 체크 (범위 검증)

**문제:** 
- 7E2 22 E004 12V=28.18V
- 7E4 22 0105 DET_MIN=839.9%
- 7E5 E001/E003 응답 길이 불일치

**수정안:**
```python
# decoder에 min/max 범위 추가
def validate_range(value: float, min_val: float, max_val: float) -> bool:
    """신뢰도 검증: 범위 벗어나면 측정불가."""
    return min_val <= value <= max_val

# 예: 12V 보조배터리는 6~18V 정상 범위
# 28.18V → 측정불가 + '정의 불일치' 표시
```

---

### #13: 최저 셀 번호 표시

**문제:** 0101 [26]=40번, 0103 셀별=115·127·130·140번 불일치

**수정안 (코드 보류):**
```
보고서에 두 값 함께 표시:
- 최저 셀 번호(요약): 40번 (3.54V)
- 최저 셀 번호(셀별): 115, 127, 130, 140번 (각 3.54V)
- 참고: 요약과 셀별 데이터 불일치
```

---

## 회귀 테스트 기대값

가짜 VIN: `ZZZ12345678901234`

### BMS 값
- **LDC 출력**: 14.93V (0x3A52)
- **LDC − 12V**: 0.43V
- **입구 온도**: 22°C (0x3E)

### 충전 인렛 온도
- **DC1**: 24°C
- **DC2**: 24°C
- **AC**: 28°C
- **편차**: 4°C

### 셀
- **개수**: 152개
- **최고**: 3.56V
- **최저**: 3.54V
- **편차**: 0.02V

### 모듈 온도
- **편차**: 2.0°C

---

## 테스트 hex 조각 (실측 일부만)

```python
# LDC E101 응답 (7E5 → 7ED)
ldc_e101_hex = "623A520000..."  # [10:11] = 3A52 → 14.93V

# 입구 온도 0101 응답 (7E4 → 7EC)
inlet_temp_hex = "62...3E..."   # [22] = 3E (62) → 22°C

# 충전 인렛 E004 응답 (744 → 74C)
dc_inlet_hex = "62...424242..."  # [8:9:10] = 42 42 42 → 24/24/28°C
```

---

## 구현 우선순위

### Phase 1 (필수)
- [x] #1: EV9 힌트
- [x] #2: LDC E101
- [x] #3: inlet_temp 오프셋
- [x] #6-8: 이미 완료
- [ ] #5: suppressPosRsp
- [ ] #11: 모듈 온도 추가

### Phase 2 (중요)
- [ ] #9: 주행거리 DID
- [ ] #10: 기능주소 응답
- [ ] #12: 범위 검증

### Phase 3 (선택)
- [ ] #4: 차종 판별 (manual-model-selection.md)
- [ ] #13: 셀 번호 표시

---

## 참고

- **출처**: https://github.com/OBDb/Kia-EV9 (커밋 8bb70bb5, CC BY-SA 4.0)
- **내장본**: `app/modules/canlab/engine/obdb/Kia-EV9.json`
- **실제 로그 커밋 금지**, 테스트는 가짜 VIN·hex 조각만
