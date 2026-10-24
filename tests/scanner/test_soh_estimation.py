"""SOH 추정 테스트"""
import pytest

from app.modules.scanner import soh_estimation


def test_estimate_soh_by_throughput_nmc():
    """Coulomb Counting 방법 - NMC 배터리"""
    result = soh_estimation.estimate_soh_by_throughput(
        cum_charge_ah=10000,      # 10,000 Ah 충전
        cum_discharge_ah=9500,    # 9,500 Ah 방전
        nominal_capacity_ah=170,  # Kona EV (64kWh)
    10|        battery_chemistry="NMC"
    )
    
    assert result.soh is not None
    assert 60 <= result.soh <= 105
    assert result.method == "coulomb_counting"
    assert result.confidence > 0.6
    assert "NMC" in result.assumptions
    
    # 계산 검증: throughput = 19,500 Ah
    # 노화 = 19,500 * 0.00015 = 2.925 Ah
    20|    # 현재 용량 = 170 - 2.925 = 167.075 Ah
    # SOH = 167.075 / 170 = 98.3%
    assert 97 <= result.soh <= 99
    assert result.details["throughput_ah"] == 19500


def test_estimate_soh_by_throughput_lfp():
    """Coulomb Counting 방법 - LFP 배터리 (BYD)"""
    result = soh_estimation.estimate_soh_by_throughput(
        cum_charge_ah=15000,
        cum_discharge_ah=14500,
    30|        nominal_capacity_ah=170,
        battery_chemistry="LFP"
    )
    
    assert result.soh is not None
    # LFP는 노화 계수가 작아서 SOH가 더 높아야 함
    assert result.soh > 95
    assert "LFP" in result.assumptions


def test_estimate_soh_by_time_light_usage():
    40|    """시간 기반 방법 - 온화한 사용"""
    result = soh_estimation.estimate_soh_by_time(
        operating_time_s=2 * 365.25 * 24 * 3600,  # 2년
        cum_charge_kwh=10000,  # 낮은 충전량 (연간 100 사이클 미만)
        nominal_capacity_kwh=64.0
    )
    
    assert result.soh is not None
    assert result.method == "time_based_fallback"
    # 2년 × 2% = 96% 예상
    50|    assert 94 <= result.soh <= 98
    assert "온화 사용" in result.details["usage_pattern"]
    assert result.details["degradation_rate_percent"] == 2.0


def test_estimate_soh_by_time_heavy_usage():
    """시간 기반 방법 - 가혹한 사용 (고속충전 빈번)"""
    result = soh_estimation.estimate_soh_by_time(
        operating_time_s=2 * 365.25 * 24 * 3600,  # 2년
        cum_charge_kwh=50000,  # 높은 충전량 (연간 300+ 사이클)
    60|        nominal_capacity_kwh=64.0
    )
    
    assert result.soh is not None
    # 2년 × 5% = 90% 예상
    assert 88 <= result.soh <= 92
    assert "가혹 사용" in result.details["usage_pattern"]
    assert result.details["degradation_rate_percent"] == 5.0


def test_estimate_soh_by_energy():
    70|    """에너지 기반 방법 (kWh throughput)"""
    result = soh_estimation.estimate_soh_by_energy(
        cum_charge_kwh=50000,
        cum_discharge_kwh=48000,
        nominal_capacity_kwh=64.0,
        battery_chemistry="NMC"
    )
    
    assert result.soh is not None
    assert result.method == "energy_throughput"
    80|    assert 60 <= result.soh <= 105
    assert result.details["throughput_kwh"] == 98000


def test_estimate_soh_multimethod_with_all_data():
    """복합 추정 - 모든 데이터가 있을 때"""
    signals = {
        "cum_charge_ah": 10000,
        "cum_discharge_ah": 9500,
        "cum_charge_kwh": 30000,
        "cum_discharge_kwh": 28000,
    90|        "operating_time_s": 3 * 365.25 * 24 * 3600,  # 3년
    }
    
    car = {
        "diag_model": "코나",
        "diag_submodel": "일렉트릭"
    }
    
    result = soh_estimation.estimate_soh_multimethod(signals, car)
    
    assert result.soh is not None
   100|    # Coulomb Counting이 최우선이므로 그 방법을 써야 함
    assert result.method in ("coulomb_counting", "fusion")
    assert result.confidence > 0.6


def test_estimate_soh_multimethod_without_ah():
    """복합 추정 - Ah 없이 kWh만 있을 때"""
    signals = {
        "cum_charge_kwh": 30000,
        "cum_discharge_kwh": 28000,
   110|        "operating_time_s": 2 * 365.25 * 24 * 3600,
    }
    
    car = {"diag_model": "IONIQ", "diag_submodel": "5"}
    
    result = soh_estimation.estimate_soh_multimethod(signals, car)
    
    assert result.soh is not None
    assert result.method in ("energy_throughput", "time_based_fallback", "fusion")


   120|def test_estimate_soh_multimethod_minimal_data():
    """복합 추정 - 최소 데이터 (시간 기반만 가능)"""
    signals = {
        "operating_time_s": 2 * 365.25 * 24 * 3600,
        "cum_charge_kwh": 15000,
    }
    
    car = {"diag_model": "EV6"}
    
    result = soh_estimation.estimate_soh_multimethod(signals, car)
   130|    
    assert result.soh is not None
    assert result.method == "time_based_fallback"


def test_estimate_soh_multimethod_no_data():
    """복합 추정 - 데이터 부족"""
    signals = {}
    car = {"diag_model": "EV6"}
    
    result = soh_estimation.estimate_soh_multimethod(signals, car)
   140|    
    assert result.soh is None
    assert result.method == "unavailable"


def test_get_battery_spec_hyundai():
    """배터리 사양 조회 - 현대차"""
    car = {"diag_model": "코나", "diag_submodel": "일렉트릭"}
    spec = soh_estimation.get_battery_spec(car)
    
    assert spec["capacity_kwh"] == 64.0
   150|    assert spec["capacity_ah"] == 170
    assert spec["chemistry"] == "NMC"


def test_get_battery_spec_kia():
    """배터리 사양 조회 - 기아"""
    car = {"diag_model": "EV6"}
    spec = soh_estimation.get_battery_spec(car)
    
    assert spec["capacity_kwh"] == 77.4
    assert spec["capacity_ah"] == 216
   160|    assert spec["chemistry"] == "NMC"


def test_get_battery_spec_nissan():
    """배터리 사양 조회 - 닛산"""
    car = {"diag_model": "LEAF"}
    spec = soh_estimation.get_battery_spec(car)
    
    assert spec["capacity_kwh"] == 40.0
    assert spec["chemistry"] == "NMC"

   170|
def test_get_battery_spec_unknown():
    """배터리 사양 조회 - 미지원 차종 (기본값 반환)"""
    car = {"diag_model": "Unknown", "diag_submodel": "Model"}
    spec = soh_estimation.get_battery_spec(car)
    
    # 기본값 (중형 EV 평균)
    assert spec["capacity_kwh"] == 64.0
    assert spec["capacity_ah"] == 170
    assert spec["chemistry"] == "NMC"

   180|
def test_format_soh_result_excellent():
    """SOH 결과 포맷 - 매우 좋음"""
    estimate = soh_estimation.SOHEstimate(
        soh=95.0,
        method="coulomb_counting",
        confidence=0.75,
        assumptions="테스트",
        details={}
    )
    
    result = soh_estimation.format_soh_result(estimate)
   190|    
    assert result["soh"] == 95.0
    assert result["status"] == "excellent"
    assert "매우 좋음" in result["status_text"]


def test_format_soh_result_good():
    """SOH 결과 포맷 - 좋음"""
    estimate = soh_estimation.SOHEstimate(
        soh=85.0,
        method="coulomb_counting",
   200|        confidence=0.75,
        assumptions="테스트",
        details={}
    )
    
    result = soh_estimation.format_soh_result(estimate)
    
    assert result["soh"] == 85.0
    assert result["status"] == "good"
    assert "좋음" in result["status_text"]

   210|
def test_format_soh_result_fair():
    """SOH 결과 포맷 - 보통"""
    estimate = soh_estimation.SOHEstimate(
        soh=75.0,
        method="time_based_fallback",
        confidence=0.5,
        assumptions="테스트",
        details={}
    )
   220|    
    result = soh_estimation.format_soh_result(estimate)
    
    assert result["soh"] == 75.0
    assert result["status"] == "fair"
    assert "보통" in result["status_text"]


def test_format_soh_result_poor():
    """SOH 결과 포맷 - 나쁨"""
    estimate = soh_estimation.SOHEstimate(
   230|        soh=65.0,
        method="time_based_fallback",
        confidence=0.5,
        assumptions="테스트",
        details={}
    )
    
    result = soh_estimation.format_soh_result(estimate)
    
    assert result["soh"] == 65.0
   240|    assert result["status"] == "poor"
    assert "나쁨" in result["status_text"]


def test_format_soh_result_unavailable():
    """SOH 결과 포맷 - 추정 불가"""
    estimate = soh_estimation.SOHEstimate(
        soh=None,
        method="unavailable",
        confidence=0.0,
        assumptions="데이터 부족",
   250|        details={}
    )
    
    result = soh_estimation.format_soh_result(estimate)
    
    assert result["soh"] is None
    assert result["status"] == "unavailable"


def test_soh_physical_limits():
    """SOH 물리적 한계 테스트 (60% ~ 105%)"""
   260|    # 아주 많이 노화된 경우 (60% 하한)
    result = soh_estimation.estimate_soh_by_throughput(
        cum_charge_ah=100000,
        cum_discharge_ah=95000,
        nominal_capacity_ah=170,
        battery_chemistry="NMC"
    )
    assert result.soh >= 60.0
    
    # 새 배터리 (105% 상한, 공칭보다 약간 높을 수 있음)
   270|    result = soh_estimation.estimate_soh_by_throughput(
        cum_charge_ah=100,
        cum_discharge_ah=50,
        nominal_capacity_ah=170,
        battery_chemistry="NMC"
    )
    assert result.soh <= 105.0


def test_soh_confidence_scores():
    """신뢰도 점수 테스트"""
   280|    # 높은 신뢰도: Coulomb Counting, 정상 범위
    result = soh_estimation.estimate_soh_by_throughput(
        cum_charge_ah=10000,
        cum_discharge_ah=9500,
        nominal_capacity_ah=170,
        battery_chemistry="NMC"
    )
    assert result.confidence >= 0.7
    
    # 낮은 신뢰도: Time-based fallback
   290|    result = soh_estimation.estimate_soh_by_time(
        operating_time_s=2 * 365.25 * 24 * 3600,
        cum_charge_kwh=15000,
        nominal_capacity_kwh=64.0
    )
    assert result.confidence <= 0.6
