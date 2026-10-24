"""SOH 추정 추가 테스트 (복원된 6개)"""
import pytest
from app.modules.scanner.soh_estimation import (
    estimate_soh,
    estimate_soh_by_throughput,
    estimate_soh_by_time,
)


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
    # 3년 × 2.5% × 0.8 (mild) = 6% 손실 → 94%
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
    # 3년 × 2.5% × 1.5 (temp) × 1.5 (harsh) = 16.875% 손실 → ~83%
    assert 80.0 <= result.soh <= 88.0


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
