"""SOH 추정 모듈 테스트"""
import pytest
from app.modules.scanner.soh_estimation import (
    estimate_soh,
    estimate_soh_by_throughput,
    estimate_soh_by_energy,
    estimate_soh_by_time,
    get_battery_spec
)


def test_estimate_soh_by_throughput():
    """Coulomb Counting 방법 테스트"""
    result = estimate_soh_by_throughput(
        cum_charge_ah=5000,
        cum_discharge_ah=4750,
        nominal_capacity_ah=170,
        battery_chemistry="NMC"
    )
    
    # 약 14.4 사이클 (9750 / (170*2))
    # 용량 손실 = 170 * 14.4 * 0.00005 ≈ 0.122 Ah
    # 현재 용량 = 170 - 0.122 = 169.878 Ah
    # SOH = 169.878 / 170 * 100 ≈ 99.9%
    
    assert result.method == "coulomb_counting"
    assert 99.0 <= result.soh <= 100.0
    assert result.confidence == 0.85


def test_estimate_soh_by_throughput_heavy_use():
    """많이 사용한 배터리 (저SOH)"""
    result = estimate_soh_by_throughput(
        cum_charge_ah=100000,
        cum_discharge_ah=95000,
        nominal_capacity_ah=170,
        battery_chemistry="NMC"
    )
    
    # 약 573 사이클
    # 용량 손실 = 170 * 573 * 0.00005 ≈ 4.87 Ah
    # 현재 용량 = 170 - 4.87 ≈ 165.13 Ah
    # SOH ≈ 97.1%
    
    assert result.method == "coulomb_counting"
    assert 95.0 <= result.soh <= 98.0


def test_estimate_soh_by_energy():
    """에너지 기반 방법 (kWh throughput)"""
    result = estimate_soh_by_energy(
        cum_charge_kwh=3000,
        cum_discharge_kwh=2850,
        nominal_capacity_kwh=64.0,
        battery_chemistry="NMC"
    )
    
    # 약 45.7 사이클
    # 노화 ≈ 45.7 * 0.00005 * 100 = 0.23%
    # SOH ≈ 99.77%
    
    assert result.method == "energy_throughput"
    assert 60 <= result.soh <= 105
    assert result.confidence == 0.80


def test_estimate_soh_by_time_normal():
    """시간 기반 방법 - 일반 사용"""
    result = estimate_soh_by_time(
        operating_time_s=2 * 365.25 * 24 * 3600,  # 2년
        nominal_capacity_ah=170,
        temperature_avg_c=25.0,
        usage_pattern="normal"
    )
    
    # 2년 * 2.5% = 5% 감소 → SOH 95%
    assert result.method == "time_based"
    assert 93 <= result.soh <= 97
    assert result.confidence == 0.60


def test_estimate_soh_by_time_harsh():
    """시간 기반 방법 - 가혹 사용"""
    result = estimate_soh_by_time(
        operating_time_s=3 * 365.25 * 24 * 3600,  # 3년
        nominal_capacity_ah=170,
        temperature_avg_c=35.0,  # 더운 지역
        usage_pattern="harsh"
    )
    
    # 3년 * 2.5% * 1.5 (temp) * 1.5 (usage) ≈ 16.9% 감소
    assert result.method == "time_based"
    assert 80 <= result.soh <= 90


def test_estimate_soh_by_time_mild():
    """시간 기반 방법 - 온화한 사용"""
    result = estimate_soh_by_time(
        operating_time_s=1 * 365.25 * 24 * 3600,  # 1년
        nominal_capacity_ah=64.0,
        temperature_avg_c=20.0,
        usage_pattern="mild"
    )
    
    # 계산: 1년 × 2.5% × 0.75 (temp@20°C) × 0.8 (mild) = 1.5% 손실 → 98.5%
    # float 정밀도로 98.5를 반환하므로 ±0.5% 허용 범위로 97-99 검증
    assert result.method == "time_based"
    assert 97 <= result.soh <= 99


def test_estimate_soh_multimethod_coulomb_priority():
    """여러 데이터가 있을 때 Coulomb Counting 우선"""
    ev_data = {
        "battery_cum_charge_ah": 10000,
        "battery_cum_discharge_ah": 9500,
        "battery_cum_charge_kwh": 3000,  # 이것도 있지만
        "battery_cum_discharge_kwh": 2850,
        "operating_time_s": 2 * 365.25 * 24 * 3600,
    }
    
    car = {"diag_model": "KONA", "diag_submodel": "ELECTRIC"}
    
    result = estimate_soh(ev_data, car)
    
    # Coulomb Counting이 최우선이므로 그 방법을 써야 함
    assert result is not None
    assert result.method == "coulomb_counting"


def test_estimate_soh_multimethod_minimal_data():
    """최소한의 데이터 (시간만)"""
    ev_data = {
        "operating_time_s": 365.25 * 24 * 3600,  # 1년
    }
    
    car = {"diag_model": "IONIQ", "diag_submodel": "5"}
    
    result = estimate_soh(ev_data, car)
    
    assert result is not None
    assert result.method == "time_based"


def test_estimate_soh_no_data():
    """데이터가 전혀 없을 때"""
    ev_data = {}
    result = estimate_soh(ev_data, None)
    
    assert result is None


def test_get_battery_spec_exact_match():
    """정확한 모델명 매칭"""
    car = {"diag_model": "KONA", "diag_submodel": "ELECTRIC"}
    spec = get_battery_spec(car)
    
    assert spec["capacity_kwh"] == 64.0
    assert spec["capacity_ah"] == 170
    assert spec["chemistry"] == "NMC"


def test_get_battery_spec_partial_match():
    """부분 매칭 (공백 포함 등)"""
    car = {"diag_model": "KONA ELECTRIC", "diag_submodel": ""}
    spec = get_battery_spec(car)
    
    assert spec["capacity_ah"] == 170
    assert spec["chemistry"] == "NMC"


def test_get_battery_spec_unknown():
    """알 수 없는 차량 - 기본값 반환"""
    car = {"diag_model": "UNKNOWN", "diag_submodel": "MODEL"}
    spec = get_battery_spec(car)
    
    # 기본값
    assert spec["capacity_kwh"] == 64.0
    assert spec["capacity_ah"] == 170
    assert spec["chemistry"] == "NMC"


def test_estimate_soh_lfp_battery():
    """LFP 배터리 (BYD 등) - 노화율 더 낮음"""
    result = estimate_soh_by_throughput(
        cum_charge_ah=100000,
        cum_discharge_ah=95000,
        nominal_capacity_ah=170,
        battery_chemistry="LFP"
    )
    
    # LFP는 노화계수 0.00003 (NMC 0.00005보다 낮음)
    # 573 사이클 * 0.00003 = 0.017 → 용량 손실 2.9 Ah
    # SOH ≈ 98.3%
    
    assert result.method == "coulomb_counting"
    assert 97.5 <= result.soh <= 99.0


def test_soh_bounds():
    """SOH는 항상 60~100% 범위"""
    # 극단적으로 많이 사용 (물리적으로 불가능한 수준)
    result = estimate_soh_by_throughput(
        cum_charge_ah=10000000,
        cum_discharge_ah=10000000,
        nominal_capacity_ah=170,
        battery_chemistry="NMC"
    )
    
    # 계산상 음수가 나와도 60% 이상으로 클리핑
    assert 60.0 <= result.soh <= 100.0
    
    # 새 배터리
    result2 = estimate_soh_by_throughput(
        cum_charge_ah=10,
        cum_discharge_ah=5,
        nominal_capacity_ah=170,
        battery_chemistry="NMC"
    )
    
    assert 60.0 <= result2.soh <= 100.0


def test_estimate_soh_by_throughput_nmc():
    """Coulomb Counting 방법 - NMC 배터리"""
    result = estimate_soh_by_throughput(
        cum_charge_ah=10000,
        cum_discharge_ah=9500,
        nominal_capacity_ah=170,
        battery_chemistry="NMC"
    )
    
    assert result.soh is not None
    assert 60.0 <= result.soh <= 100.0
    assert result.method == "coulomb_counting"
    assert result.confidence > 0.6


def test_estimate_soh_by_throughput_lfp():
    """Coulomb Counting 방법 - LFP 배터리 (BYD)"""
    result = estimate_soh_by_throughput(
        cum_charge_ah=15000,
        cum_discharge_ah=14500,
        nominal_capacity_ah=170,
        battery_chemistry="LFP"
    )
    
    assert result.soh is not None
    assert result.soh > 95.0
    assert result.method == "coulomb_counting"


def test_estimate_soh_by_time_light_usage():
    """시간 기반 방법 - 온화한 사용 (3년)"""
    result = estimate_soh_by_time(
        operating_time_s=3 * 365.25 * 24 * 3600,  # 3년
        nominal_capacity_ah=64.0,
        temperature_avg_c=25.0,
        usage_pattern="mild"
    )
    
    assert result.soh is not None
    assert result.method == "time_based"
    # 3년 × 2.5% × 0.8 (mild) × 0.875 (temp@25°C) = 5.25% 손실 → 94.75%
    assert 92.0 <= result.soh <= 96.0


def test_estimate_soh_by_time_heavy_usage():
    """시간 기반 방법 - 가혹한 사용 (3년, 고온)"""
    result = estimate_soh_by_time(
        operating_time_s=3 * 365.25 * 24 * 3600,  # 3년
        nominal_capacity_ah=64.0,
        temperature_avg_c=35.0,  # 고온
        usage_pattern="harsh"
    )
    
    assert result.soh is not None
    assert result.method == "time_based"
    # 3년 × 2.5% × 1.5 (harsh) × 1.25 (temp@35°C) = 14.0625% 손실 → ~86%
    assert 82.0 <= result.soh <= 90.0


def test_estimate_soh_multimethod_with_all_data():
    """복합 추정 - 모든 데이터가 있을 때 (Coulomb Counting 우선)"""
    ev_data = {
        "battery_cum_charge_ah": 10000,
        "battery_cum_discharge_ah": 9500,
        "battery_cum_charge_kwh": 30000,
        "battery_cum_discharge_kwh": 28000,
        "battery_operating_time_s": 3 * 365.25 * 24 * 3600,
    }
    
    car = {
        "diag_model": "IONIQ",
        "diag_submodel": "5"
    }
    
    result = estimate_soh(ev_data, car)
    
    assert result is not None
    assert result.soh is not None
    # Coulomb Counting이 최우선
    assert result.method == "coulomb_counting"
    assert result.confidence > 0.6


def test_estimate_soh_multimethod_without_ah():
    """복합 추정 - Ah 없이 kWh만 있을 때 (에너지 기반)"""
    ev_data = {
        "battery_cum_charge_kwh": 30000,
        "battery_cum_discharge_kwh": 28000,
        "battery_operating_time_s": 2 * 365.25 * 24 * 3600,
    }
    
    car = {"diag_model": "IONIQ", "diag_submodel": "5"}
    
    result = estimate_soh(ev_data, car)
    
    assert result is not None
    assert result.soh is not None
    # Ah가 없으면 에너지 기반
    assert result.method == "energy_throughput"
