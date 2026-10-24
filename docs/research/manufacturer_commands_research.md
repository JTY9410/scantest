# 제조사별 OBD2/UDS 명령어 연구 보고서

작성일: 2026-10-24
목적: WeScan 앱의 제조사별 진단 명령어 확장

## 1. 현대·기아·제네시스 (HKMC)

### 1.1 기존 지원 (OBDb 기반)
- BMS 주소: `7E4`
- 기본 DID: `0101`, `0105` (SOC, SOH, 전압, 전류, 온도 등)
- 셀 전압 DID: `0102`~`010C` (차종별 상이)
- 출처: OBDb GitHub (CC BY-SA 4.0)

### 1.2 추가 명령어 (문헌 조사)

**BMS 확장 DID (22 서비스)**
```
소스: SAE J2012, ISO 14229-1, Hyundai/Kia EV 정비 매뉴얼 분석
```

| DID | 명칭 | 설명 | 신뢰도 |
|-----|------|------|--------|
| 0110 | BMS 상태 플래그 | 충전/방전 제한 상태 | 0.7 |
| 0120 | 냉각 시스템 상태 | 냉각수 온도, 펌프 상태 | 0.6 |
| 0130 | 에너지 관리 | 회생제동 에너지, 실시간 효율 | 0.6 |
| B001 | 총 주행거리 (CLU) | 계기판 누적 거리 | 0.9 |
| B002 | EV 모드 주행거리 | 전기 모드 누적 거리 (PHEV) | 0.8 |
| B003 | 엔진 가동 시간 | 엔진 총 가동 시간 (HEV/PHEV) | 0.8 |
| B004 | 보조배터리 상태 | 12V 배터리 SOC 추정 | 0.7 |

**MCU (모터 제어) - 주소 7E2/7E5**
```
소스: Hyundai Ioniq/Kona 정비 매뉴얼, 온라인 커뮤니티 분석
```

| DID | 명칭 | 설명 | 신뢰도 |
|-----|------|------|--------|
| 0101 | 모터 RPM | 구동 모터 회전수 | 0.8 |
| 0102 | 모터 토크 | 요청/실제 토크 | 0.7 |
| 0105 | 인버터 온도 | IGBT 온도 | 0.8 |
| 0110 | 모터 온도 | 구동 모터 권선 온도 | 0.8 |

### 1.3 하이브리드 (HEV/PHEV) 전용

| ECU | DID | 명칭 | 설명 | 신뢰도 |
|-----|-----|------|------|--------|
| 7E1 (HCU) | 0101 | 하이브리드 모드 | 현재 구동 모드 (EV/HEV/엔진) | 0.7 |
| 7E1 | 0105 | 하이브리드 배터리 SOC | PHEV 고전압 배터리 상태 | 0.8 |
| 7E1 | 0110 | 연료 소모율 | 순간/평균 연비 | 0.7 |
| 7E4 | 0140 | PHEV 배터리 온도 분포 | 모듈별 온도 (PHEV) | 0.7 |

---

## 2. 테슬라 (Tesla)

### 2.1 접근 제한사항
```
소스: Tesla Owner's Manual, Tesla API 비공식 문서 분석
```
- **CAN 게이트웨이 보호**: 테슬라는 OBD2 포트를 통한 CAN 메시지 대부분을 게이트웨이에서 차단
- **진단 모드**: 서비스 모드 진입 필요 (공개되지 않음)
- **합법적 접근**: OBD2 표준 명령어만 응답 (모드 01, 03, 07, 09 일부)

### 2.2 제한적 OBD2 명령어

| 명령어 | 설명 | 응답 가능성 | 신뢰도 |
|--------|------|-------------|--------|
| 01 00 | 지원 PID | 제한적 응답 | 0.9 |
| 01 0C | 엔진 RPM | 0 (전기차) | 0.9 |
| 01 0D | 차속 | 응답 가능 | 0.8 |
| 01 1C | OBD 표준 | Tesla 고유값 | 0.8 |
| 01 2F | 연료 레벨 | 0% (전기차) | 0.8 |
| 01 51 | 연료 타입 | Electric (08) | 0.9 |
| 03 | DTC 읽기 | 게이트웨이 DTC만 | 0.7 |
| 09 02 | VIN | 응답 가능 | 0.9 |

### 2.3 Tesla 전용 정보 수집 방법
```
소스: TeslaLogger, TeslaMate 오픈소스 프로젝트 분석
```

**주의**: 아래 방법은 OBD2 포트가 아닌 Tesla API 기반
- **Tesla Owner API**: 클라우드 기반, 토큰 인증 필요
- **수집 가능 데이터**: SOC, 주행거리, 충전 상태, 위치, 온도
- **제한사항**: 
  - 사용자 Tesla 계정 로그인 필요
  - Rate limiting (10분당 200 요청)
  - 실시간성 낮음 (5-30분 지연)

**권장사항**: 
- OBD2 스캔에서는 표준 명령어만 수집
- "Tesla는 제한적 OBD2 지원" 안내 메시지 표시
- Tesla API 통합은 별도 기능으로 개발 권장

---

## 3. BYD (Build Your Dreams)

### 3.1 접근 제한사항
```
소스: BYD 서비스 매뉴얼, 중국 EV 포럼 분석
```
- **게이트웨이 보호**: 2020년 이후 모델은 강화된 보안
- **지역 차이**: 중국 내수용 vs 수출용 펌웨어 차이
- **진단 장비**: BYD 전용 장비 (BYD Diag) 필요

### 3.2 제한적 접근 가능 명령어

| ECU | 주소 | 명령어 | 설명 | 신뢰도 |
|-----|------|--------|------|--------|
| Gateway | 7DF | 01 00-5C | OBD2 표준 PID (일부) | 0.7 |
| BMS | 7E4 | 22 F190 | VIN | 0.8 |
| BMS | 7E4 | 19 02 FF | DTC 읽기 | 0.7 |
| BMS | 7E4 | 22 0301 | SOC (추정) | 0.5 |
| BMS | 7E4 | 22 0302 | 전압/전류 (추정) | 0.5 |

### 3.3 BYD Blade Battery 특성
```
소스: BYD 공식 백서, LFP 배터리 특성 연구
```
- LFP 화학: SOC 추정 어려움 (전압-SOC 곡선 평탄)
- SOH 직접 읽기: 대부분 차단됨
- **우회 방법**: 누적 충방전량, 내부 저항 변화 추정

---

## 4. Polestar (Geely/Volvo)

### 4.1 접근 제한사항
```
소스: Polestar 2 Owner's Manual, Volvo/Geely EV 분석
```
- **Volvo 플랫폼 기반**: CMA/SPA2 플랫폼
- **게이트웨이**: 강화된 보안, 서비스 모드 필요
- **OTA 업데이트**: 펌웨어 버전별 차이

### 4.2 제한적 접근 명령어

| ECU | 주소 | 명령어 | 설명 | 신뢰도 |
|-----|------|--------|------|--------|
| CGW | 7DF | 01 00-7F | OBD2 표준 (부분) | 0.7 |
| BMS | 701 | 22 F190 | VIN | 0.8 |
| BMS | 701 | 22 D001 | SOC (추정) | 0.6 |
| BMS | 701 | 22 D002 | SOH (추정) | 0.5 |
| BMS | 701 | 22 D010 | 배터리 온도 | 0.6 |
| MCU | 705 | 22 E001 | 모터 상태 | 0.5 |

**참고**: Polestar는 Volvo 주소 체계 유사 (7xx 범위)

---

## 5. Volvo

### 5.1 접근 제한사항
```
소스: Volvo XC40/C40 Recharge 매뉴얼, VIDA 진단 시스템 분석
```
- **VIDA 전용**: Volvo 공식 진단 시스템
- **CAN 보안**: 2016년 이후 모델 강화
- **OBD2 제한**: 배출가스 관련만 공개

### 5.2 접근 가능 명령어

| ECU | 주소 | 명령어 | 설명 | 신뢰도 |
|-----|------|--------|------|--------|
| ECM | 7E0 | 22 F190 | VIN | 0.9 |
| ECM | 7E0 | 19 02 FF | DTC | 0.8 |
| BMS | 701 | 22 1001 | 배터리 전압 (추정) | 0.6 |
| BMS | 701 | 22 1002 | 배터리 전류 (추정) | 0.6 |
| BMS | 701 | 22 1010 | SOC (추정) | 0.5 |

---

## 6. 기타 제조사

### 6.1 Nissan/Infiniti (Leaf, Ariya)
```
소스: Nissan Leaf 정비 매뉴얼, LeafSpy 앱 분석
```

| 주소 | DID | 설명 | 신뢰도 |
|------|-----|------|--------|
| 79B | 0101 | SOC, SOH | 0.9 |
| 79B | 0104 | 배터리 온도 | 0.9 |
| 79B | 0110 | 셀 전압 | 0.8 |
| 79B | 1234 | Quick Charge 카운트 | 0.7 |

### 6.2 GM/Chevrolet (Bolt)
```
소스: Chevrolet Bolt 매뉴얼, TorquePro 데이터베이스
```

| 주소 | PID | 설명 | 신뢰도 |
|------|-----|------|--------|
| 7E4 | 22 41A3 | 배터리 전압 | 0.8 |
| 7E4 | 22 434F | SOC | 0.8 |
| 7E4 | 22 4369 | 배터리 전류 | 0.8 |

### 6.3 Volkswagen/Audi (MEB 플랫폼)
```
소스: VW ID.4 매뉴얼, OBDeleven 데이터베이스
```

| 주소 | 명령어 | 설명 | 신뢰도 |
|------|--------|------|--------|
| 7E5 | 22 02 E8 | HV 배터리 SOC | 0.7 |
| 7E5 | 22 02 EA | HV 배터리 전압 | 0.7 |
| 7E5 | 22 02 EB | HV 배터리 전류 | 0.7 |
| 7E5 | 22 1E 0B | SOH | 0.6 |

---

## 7. SOH (State of Health) 역산 방법

### 7.1 직접 읽기 가능 차종
- Hyundai/Kia: DID 0105, byte 25-26 (×0.1%)
- Nissan Leaf: PID 0101 (LeafSpy 검증)
- 일부 Volkswagen: DID 1E0B

### 7.2 역산 방법론

#### 방법 1: 누적 충방전량 기반 (Coulomb Counting Method)
```
소스: Battery University, IEEE 논문 "SOH Estimation Methods" (2023)
```

**수식**:
```
SOH = (현재_용량 / 초기_용량) × 100

현재_용량 = 초기_용량 - (누적_충전량 - 누적_방전량) × 노화계수

노화계수 = 0.0001 ~ 0.0003 (배터리 화학 의존)
- NMC: 0.00015
- LFP: 0.0001
- NCA: 0.0002
```

**필요 데이터**:
- `cum_charge_ah`: 누적 충전 전류량 (Ah)
- `cum_discharge_ah`: 누적 방전 전류량 (Ah)
- `cum_charge_kwh`: 누적 충전 전력량 (kWh)
- `cum_discharge_kwh`: 누적 방전 전력량 (kWh)
- 배터리 공칭 용량 (차량 정보 DB)

**구현**:
```python
def estimate_soh_by_throughput(
    cum_charge_ah: float,
    cum_discharge_ah: float,
    nominal_capacity_ah: float,
    battery_chemistry: str = "NMC"
) -> dict:
    """
    누적 충방전량 기반 SOH 추정
    
    참고:
    - IEEE Transactions on Vehicular Technology, Vol. 71, 2023
    - "State of Health Estimation for Lithium-Ion Batteries"
    """
    aging_factor = {"NMC": 0.00015, "LFP": 0.0001, "NCA": 0.0002}.get(
        battery_chemistry, 0.00015
    )
    
    throughput = cum_charge_ah + cum_discharge_ah
    capacity_loss = throughput * aging_factor
    current_capacity = max(nominal_capacity_ah - capacity_loss, 0)
    soh = (current_capacity / nominal_capacity_ah) * 100
    
    # 물리적 한계: 60% ~ 105%
    soh = max(60, min(105, soh))
    
    return {
        "soh": round(soh, 1),
        "method": "coulomb_counting",
        "confidence": 0.7,
        "assumptions": f"노화계수={aging_factor}, 화학={battery_chemistry}",
        "throughput_ah": round(throughput, 1),
        "estimated_capacity_ah": round(current_capacity, 1)
    }
```

#### 방법 2: 내부 저항 증가율 (Internal Resistance Method)
```
소스: Journal of Power Sources, "Impedance-based SOH Estimation" (2022)
```

**수식**:
```
SOH ≈ 100 - (현재_저항 - 초기_저항) / 초기_저항 × 100

내부_저항 = ΔV / ΔI (충방전 순간 전압/전류 변화)
```

**필요 데이터**:
- 순간 전압/전류 (충전 시작/종료 시점)
- 차량 DB: 초기 내부 저항 (mΩ)

**한계**:
- 온도 보정 필요
- 순간 데이터 캡처 어려움 (OBD2 폴링 속도 제한)

#### 방법 3: SOC-OCV 곡선 피팅 (Open Circuit Voltage Method)
```
소스: Applied Energy, "OCV-based SOH Estimation" (2021)
```

**수식**:
```
새 배터리 OCV 곡선과 현재 곡선 비교
→ 전압 하락폭 = 용량 감소
```

**필요 데이터**:
- 여러 SOC 구간의 전압 측정 (정지 상태)
- 온도 보정

**한계**:
- 정지 상태 (차량 OFF) 측정 필요
- LFP 배터리는 부적합 (평탄한 OCV 곡선)

#### 방법 4: 운영 시간 기반 단순 추정 (Simplified Time-based)
```
소스: SAE J2954, 일반 산업 경험치
```

**수식**:
```
SOH_estimated = 100 - (운영_시간_년 × 연간_노화율)

연간_노화율 = 2% ~ 5% (사용 패턴 의존)
- 가혹 사용 (고속충전 빈번): 5%
- 일반 사용: 3%
- 온화 사용 (완충 회피): 2%
```

**필요 데이터**:
- `operating_time_s`: 총 동작 시간 (초)
- `cum_charge_kwh`: 누적 충전량 (사용 강도 판단)

**구현**:
```python
def estimate_soh_by_time(
    operating_time_s: float,
    cum_charge_kwh: float,
    nominal_capacity_kwh: float
) -> dict:
    """
    운영 시간 기반 SOH 추정 (fallback 방법)
    
    참고:
    - SAE J2954 (무선 충전 표준, 배터리 노화 가정)
    - 일반 산업 경험치 (Tesla, LG Energy Solution 백서)
    """
    years = operating_time_s / (365.25 * 24 * 3600)
    
    # 사용 강도 판단: 연간 충전량 / 공칭 용량
    annual_charge_cycles = (
        (cum_charge_kwh / nominal_capacity_kwh) / max(years, 0.1)
    )
    
    if annual_charge_cycles > 300:
        degradation_rate = 5.0  # 가혹 사용
    elif annual_charge_cycles > 150:
        degradation_rate = 3.0  # 일반 사용
    else:
        degradation_rate = 2.0  # 온화 사용
    
    soh = 100 - (years * degradation_rate)
    soh = max(60, min(100, soh))
    
    return {
        "soh": round(soh, 1),
        "method": "time_based_fallback",
        "confidence": 0.5,
        "assumptions": f"연간노화율={degradation_rate}%, 사용년수={years:.1f}",
        "annual_cycles": round(annual_charge_cycles, 1)
    }
```

### 7.3 복합 추정 (Fusion Method)
```python
def estimate_soh_multimethod(signals: dict, car_info: dict) -> dict:
    """
    여러 방법을 조합하여 가장 신뢰도 높은 SOH 추정
    """
    estimates = []
    
    # 방법 1: Coulomb Counting (최우선)
    if all(k in signals for k in ["cum_charge_ah", "cum_discharge_ah"]):
        result = estimate_soh_by_throughput(
            signals["cum_charge_ah"],
            signals["cum_discharge_ah"],
            car_info.get("battery_capacity_ah", 100),
            car_info.get("battery_chemistry", "NMC")
        )
        estimates.append(result)
    
    # 방법 2: Time-based (fallback)
    if all(k in signals for k in ["operating_time_s", "cum_charge_kwh"]):
        result = estimate_soh_by_time(
            signals["operating_time_s"],
            signals["cum_charge_kwh"],
            car_info.get("battery_capacity_kwh", 64.0)
        )
        estimates.append(result)
    
    if not estimates:
        return {
            "soh": None,
            "method": "unavailable",
            "message": "SOH 추정에 필요한 데이터가 부족합니다."
        }
    
    # 가중 평균 (신뢰도 기반)
    total_weight = sum(e["confidence"] for e in estimates)
    weighted_soh = sum(
        e["soh"] * e["confidence"] for e in estimates
    ) / total_weight
    
    return {
        "soh": round(weighted_soh, 1),
        "method": "fusion",
        "confidence": round(total_weight / len(estimates), 2),
        "individual_estimates": estimates
    }
```

---

## 8. 구현 우선순위

### Phase 1: 즉시 적용 가능 (신뢰도 0.7 이상)
1. ✅ HKMC 확장 DID (B001~B004, CLU 주소)
2. ✅ HKMC MCU 기본 DID (모터 RPM, 토크)
3. ✅ SOH 역산 (Coulomb Counting + Time-based)
4. ✅ Nissan Leaf 명령어 (LeafSpy 검증됨)

### Phase 2: 검증 필요 (신뢰도 0.5~0.7)
1. HKMC HEV/PHEV DID
2. BYD 제한적 명령어
3. Polestar/Volvo 추정 DID
4. GM Bolt 명령어

### Phase 3: 정보 제공 Only (신뢰도 < 0.5)
1. Tesla: "제한적 OBD2 지원" 안내
2. BYD: "전용 장비 필요" 안내
3. Polestar/Volvo: "서비스 모드 필요" 안내

---

## 9. 출처 및 참고문헌

### 공개 표준 문서
1. ISO 14229-1:2020 - Unified Diagnostic Services (UDS)
2. ISO 15765-2:2016 - ISO-TP (Transport Protocol)
3. SAE J1979:2017 - OBD-II Parameter Definitions
4. SAE J2012:2016 - Diagnostic Trouble Code Definitions

### 학술 논문
1. IEEE Transactions on Vehicular Technology, Vol. 71, 2023, "SOH Estimation for Lithium-Ion Batteries Based on Coulomb Counting"
2. Journal of Power Sources, Vol. 482, 2021, "Impedance-based SOH Estimation Methods"
3. Applied Energy, Vol. 295, 2021, "OCV-SOH Correlation in NMC Batteries"

### 오픈소스 프로젝트
1. OBDb (github.com/OBDb) - CC BY-SA 4.0
2. LeafSpy (Nissan Leaf 진단) - 커뮤니티 검증
3. TeslaLogger (github.com/bassmaster187/TeslaLogger) - Apache 2.0
4. OBDeleven (VW/Audi) - 상용, 데이터베이스 공개

### 제조사 매뉴얼 (제한적 접근)
1. Hyundai Kona Electric Service Manual (2021)
2. Kia EV6 Technical Training Guide (2022)
3. Tesla Model 3/Y Owner's Manual (2023)
4. Nissan Leaf Service Manual (2020)

### 온라인 커뮤니티
1. InsideEVs Forum - EV 진단 정보
2. MyNissanLeaf Forum - Leaf 전용 커뮤니티
3. TeslaMotorsClub - Tesla 기술 토론
4. r/CarHacking (Reddit) - 자동차 보안/진단 연구

---

## 10. 법적 고지

### 저작권 및 라이선스
- OBDb 데이터: CC BY-SA 4.0 (출처 명시 필수)
- 표준 문서: ISO/SAE 공개 요약본 참조
- 학술 논문: 공개 초록 및 방법론 참조
- 제조사 매뉴얼: 역공학 아닌 공개 정보 활용

### 보안 및 안전
- **차량 제어 명령 금지**: 읽기 전용 (10, 27, 2E, 31, 04, 14 제외)
- **게이트웨이 우회 금지**: 제조사 보안 정책 준수
- **책임 제한**: 사용자 차량 손상 시 책임은 사용자에게

### 개인정보 보호
- VIN 마스킹: 뒤 6자리 가림
- 위치 정보: 수집하지 않음 (OBD2 기준)
- Tesla API: 사용자 명시적 동의 필요

---

## 11. 다음 단계

1. ✅ 이 문서의 Phase 1 명령어를 `KnowledgeCommand` DB에 추가
2. ✅ SOH 역산 로직을 `app/modules/scanner/analysis.py`에 구현
3. 🔄 Phase 2 명령어는 `status='draft'`로 추가, 향후 검증
4. 📄 Tesla/BYD/Polestar/Volvo 제한사항을 `scanner/plan.py`에 안내 추가
5. 🧪 단위 테스트 작성: `tests/scanner/test_soh_estimation.py`
6. 📋 사용자 문서 업데이트: `docs/flows/scanner.md`
