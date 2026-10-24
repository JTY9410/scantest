"""배터리 SOH (State of Health) 역산 추정 모듈

OBD/UDS 진단 데이터에서 배터리 건강도를 역산하는 기능.
직접 SOH 값이 없을 때 누적 충방전량, 운행 시간 등으로 추정.
"""
from dataclasses import dataclass
from typing import Literal


# 제조사별 배터리 사양 (공칭 용량, 화학 조성)
BATTERY_SPECS = {
    "KONAELECTRIC": {"capacity_kwh": 64.0, "capacity_ah": 170, "chemistry": "NMC"},
    "IONIQ5": {"capacity_kwh": 72.6, "capacity_ah": 195, "chemistry": "NMC"},
    "IONIQ6": {"capacity_kwh": 77.4, "capacity_ah": 210, "chemistry": "NMC"},
    "EV6": {"capacity_kwh": 77.4, "capacity_ah": 210, "chemistry": "NMC"},
    "GV60": {"capacity_kwh": 77.4, "capacity_ah": 210, "chemistry": "NMC"},
    "IONIQPHEV": {"capacity_kwh": 8.9, "capacity_ah": 24, "chemistry": "NMC"},
    
    # Nissan
    "LEAF": {"capacity_kwh": 40.0, "capacity_ah": 110, "chemistry": "NMC"},
    "LEAF62": {"capacity_kwh": 62.0, "capacity_ah": 170, "chemistry": "NMC"},
    
    # BYD
    "ATTO3": {"capacity_kwh": 60.5, "capacity_ah": 170, "chemistry": "LFP"},
    "DOLPHIN": {"capacity_kwh": 44.9, "capacity_ah": 125, "chemistry": "LFP"},
    "SEAL": {"capacity_kwh": 82.5, "capacity_ah": 230, "chemistry": "LFP"},
}


@dataclass
class SOHEstimate:
    """SOH 추정 결과"""
    soh: float  # 추정 SOH (%)
    method: str  # 추정 방법
    confidence: float  # 신뢰도 (0~1)
    details: dict  # 계산 세부사항


def get_battery_spec(car: dict | None) -> dict:
    """차량 정보에서 배터리 사양을 찾는다. 모르면 일반 EV 기본값."""
    if not car:
        return {"capacity_kwh": 64.0, "capacity_ah": 170, "chemistry": "NMC"}
        
    # 모델명에서 공백 제거하고 대문자로 정규화
    model = str(car.get("diag_model") or "").replace(" ", "").upper()
    submodel = str(car.get("diag_submodel") or "").replace(" ", "").upper()
    key = f"{model}{submodel}"
    
    # 정확한 매칭 시도
    if key in BATTERY_SPECS:
        return BATTERY_SPECS[key]
    
    # 부분 매칭 (예: "KONA ELECTRIC" → "KONAELECTRIC")
    for spec_key, spec in BATTERY_SPECS.items():
        if spec_key in key or key in spec_key:
            return spec
    
    # 기본값 (중형 EV 평균)
    return {"capacity_kwh": 64.0, "capacity_ah": 170, "chemistry": "NMC"}


def estimate_soh_by_throughput(
    cum_charge_ah: float,
    cum_discharge_ah: float,
    nominal_capacity_ah: float,
    battery_chemistry: str = "NMC"
) -> SOHEstimate:
    """
    누적 충방전량 기반 SOH 추정 (Coulomb Counting Method).
    
    원리:
    - 배터리는 충방전마다 용량이 조금씩 줄어든다
    - 총 throughput (충전+방전 누적량)과 노화계수로 용량 감소를 추정
    - SOH = (현재 용량 / 초기 용량) × 100
       
    출처:
    - IEEE Battery Life Prediction (Li-ion degradation 0.005%/cycle for NMC)
    - Battery University: Cycle life vs. DoD
    """
    # 노화 계수 (화학 조성별 사이클당 용량 감소)
    degradation_per_cycle = {
        "NMC": 0.00005,  # 0.005% per cycle
        "LFP": 0.00003,  # 0.003% per cycle (LFP는 수명이 더 길다)
        "NCA": 0.00006,  # 0.006% per cycle
    }
    coeff = degradation_per_cycle.get(battery_chemistry, 0.00005)
    
    # 등가 사이클 수 = (총 throughput) / (공칭 용량 × 2)
    total_throughput = cum_charge_ah + cum_discharge_ah
    equivalent_cycles = total_throughput / (nominal_capacity_ah * 2) if nominal_capacity_ah > 0 else 0
    
    # 용량 손실 = 공칭 용량 × 사이클 × 계수
    capacity_loss = nominal_capacity_ah * equivalent_cycles * coeff
    current_capacity = max(nominal_capacity_ah - capacity_loss, 0)
    
    soh_raw = (current_capacity / nominal_capacity_ah * 100) if nominal_capacity_ah > 0 else 0
    
    return SOHEstimate(
        soh=max(60.0, min(100.0, soh_raw)),
        method="coulomb_counting",
        confidence=0.85,
        details={
            "total_throughput_ah": total_throughput,
            "equivalent_cycles": equivalent_cycles,
            "capacity_loss_ah": capacity_loss,
            "current_capacity_ah": current_capacity
        }
    )


def estimate_soh_by_energy(
    cum_charge_kwh: float,
    cum_discharge_kwh: float,
    nominal_capacity_kwh: float,
    battery_chemistry: str = "NMC"
) -> SOHEstimate:
    """
    누적 에너지 기반 SOH 추정 (Energy Throughput Method).
    
    원리:
    - 충전/방전 에너지 누적량을 등가 사이클로 환산
    - throughput 기반 노화 추정
    """
    degradation_per_cycle = {
        "NMC": 0.00005,
        "LFP": 0.00003,
        "NCA": 0.00006,
    }
    coeff = degradation_per_cycle.get(battery_chemistry, 0.00005)
    
    total_energy = cum_charge_kwh + cum_discharge_kwh
    equivalent_cycles = total_energy / (nominal_capacity_kwh * 2) if nominal_capacity_kwh > 0 else 0
    
    capacity_loss_pct = equivalent_cycles * coeff * 100
    soh_raw = 100.0 - capacity_loss_pct
    
    return SOHEstimate(
        soh=max(60.0, min(100.0, soh_raw)),
        method="energy_throughput",
        confidence=0.80,
        details={
            "total_energy_kwh": total_energy,
            "equivalent_cycles": equivalent_cycles,
            "capacity_loss_pct": capacity_loss_pct
        }
    )


def estimate_soh_by_time(
    operating_time_s: float,
    nominal_capacity_ah: float,
    temperature_avg_c: float = 25.0,
    usage_pattern: Literal["mild", "normal", "harsh"] = "normal"
) -> SOHEstimate:
    """
    시간 기반 SOH 추정 (Calendar + Cycle Aging).
    
    원리:
    - 배터리는 시간이 지남에 따라 자연 노화 (Calendar aging)
    - 사용 패턴과 온도에 따라 노화 속도 달라짐
    - 대략 연간 2~3% 감소 (일반 사용 기준)
    
    출처:
    - NREL: Calendar aging ~2-3% per year at 25°C
    """
    years = operating_time_s / (365.25 * 24 * 3600)
    
    # 기본 노화율 (연간)
    base_degradation_per_year = 2.5  # %
    
    # 온도 보정 (10도 상승마다 노화 2배)
    temp_factor = 1.0 + (temperature_avg_c - 25) / 10 * 0.5
    
    # 사용 패턴 보정
    usage_factor = {
        "mild": 0.8,    # 완속 충전, 저부하
        "normal": 1.0,
        "harsh": 1.5    # 급속 충전, 고부하
    }.get(usage_pattern, 1.0)
    
    total_degradation = years * base_degradation_per_year * temp_factor * usage_factor
    soh_raw = 100.0 - total_degradation
    
    # 사용 패턴 설명
    usage_desc = {
        "mild": "온화 사용 (완속충전 위주)",
        "normal": "일반 사용",
        "harsh": "가혹 사용 (고속충전 빈번 추정)"
    }.get(usage_pattern, "일반 사용")
    
    # 정수로 반올림하여 반환
    soh = int(round(soh_raw))
    soh = max(0, min(100, soh))
    
    return SOHEstimate(
        soh=soh,
        method="time_based",
        confidence=0.60,  # 시간 기반은 불확실성 크다
        details={
            "operating_years": years,
            "temperature_avg_c": temperature_avg_c,
            "usage_pattern": usage_desc,
            "total_degradation_pct": total_degradation
        }
    )


def estimate_soh(ev_data: dict, car: dict | None = None) -> SOHEstimate | None:
    """
    EV 진단 데이터에서 SOH를 추정한다.
    
    우선순위:
    1. Coulomb Counting (누적 충방전량 Ah)
    2. Energy Throughput (누적 충방전량 kWh)
    3. Time-based (운행 시간)
    
    Args:
        ev_data: _ev() 결과 (배터리 관련 수치들)
        car: 차량 정보 (모델명으로 배터리 사양 추정)
    
    Returns:
        SOHEstimate 또는 None (추정 불가)
    """
    if not ev_data:
        return None
    
    # 배터리 사양 조회
    spec = get_battery_spec(car)
    
    # Method 1: Coulomb Counting (최우선)
    cum_charge_ah = ev_data.get("battery_cum_charge_ah") or ev_data.get("cumulative_charge_ah")
    cum_discharge_ah = ev_data.get("battery_cum_discharge_ah") or ev_data.get("cumulative_discharge_ah")
    
    if cum_charge_ah and cum_discharge_ah:
        return estimate_soh_by_throughput(
            cum_charge_ah=cum_charge_ah,
            cum_discharge_ah=cum_discharge_ah,
            nominal_capacity_ah=spec["capacity_ah"],
            battery_chemistry=spec["chemistry"]
        )
    
    # Method 2: Energy Throughput
    cum_charge_kwh = ev_data.get("battery_cum_charge_kwh") or ev_data.get("cumulative_charge_kwh")
    cum_discharge_kwh = ev_data.get("battery_cum_discharge_kwh") or ev_data.get("cumulative_discharge_kwh")
    
    if cum_charge_kwh and cum_discharge_kwh:
        return estimate_soh_by_energy(
            cum_charge_kwh=cum_charge_kwh,
            cum_discharge_kwh=cum_discharge_kwh,
            nominal_capacity_kwh=spec["capacity_kwh"],
            battery_chemistry=spec["chemistry"]
        )
    
    # Method 3: Time-based (최후)
    operating_time = ev_data.get("operating_time_s") or ev_data.get("total_operating_time_s")
    
    if operating_time and operating_time > 0:
        # 온도 데이터가 있으면 사용
        temp_avg = ev_data.get("battery_temp_avg_c", 25.0)
        
        # 급속충전 횟수로 사용 패턴 추정
        dc_charge_count = ev_data.get("dc_charge_count", 0)
        usage = "harsh" if dc_charge_count > 500 else "normal" if dc_charge_count > 100 else "mild"
        
        return estimate_soh_by_time(
            operating_time_s=operating_time,
            nominal_capacity_ah=spec["capacity_ah"],
            temperature_avg_c=temp_avg,
            usage_pattern=usage
        )
    
    # 추정 불가
    return None
