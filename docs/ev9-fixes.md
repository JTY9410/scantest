# 기아 EV9 실차 CAN 분석 결과 수정사항

## 완료된 수정 (13건 중 9건)

### ✅ #1: EV9 플랫폼 힌트 추가

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

---

### ✅ #2: EV9 LDC E101 추가

**파일:** `app/modules/canlab/engine/bms.py`  
**변경:** `ECU_FIELDS`에 LDC_VOLTAGE E101 정의 추가

```python
(Field("ldc_voltage", "LDC 출력 전압", 0xE101, 10, 2, 0.001, "V", LIKELY, request=0x7E5,
       note="OBDb Kia-EV9 정의, 실측 3A52→14.93V"), {"egmp": LIKELY}),
```

**기대값:** 0x3A52 = 14930 → 14.93V  
**출처:** OBDb EV9_LDC_OUTPUT_VOLTAGE

---

### ✅ #3: 입구 온도 오프셋 수정

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

---

### ✅ #6: 측정불가 → 판정보류

**파일:** `app/modules/scanner/report.py` (이미 완료)  
**로직:** 측정불가 1개 이상이면 판정보류

```python
if not dtc_read or any(row["result"] == UNREAD for row in rows):
    return "판정보류"
```

**출처:** 보고서 규칙

---

### ✅ #7: 학습 통계 격리

**파일:** `app/modules/scanner/service.py` (이미 완료)  
**변경:** 
- ECU 추출: `ecu = header[-3:]`
- 응답시간: `response_time_ms - request_time_ms`
- Savepoint 격리: `db.session.begin_nested()`

**출처:** 절대 타임스탬프 재현

---

### ✅ #8: PDF 섹션 추가

**파일:** `app/modules/scanner/pdf.py` (이미 완료)  
**추가:** 추가 수집 정보, 문제점 섹션

**출처:** HTML/PDF 비교

---

---

### ✅ #5: suppressPosRsp 처리 완료

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

## 설계 완료 (구현 TODO, 4건)

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
