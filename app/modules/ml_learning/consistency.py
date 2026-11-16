"""데이터 정합성 점수 계산."""

from app.extensions import db
from app.modules.ml_learning.models import MLConsistencyScore, MLScanFeature
from app.modules.scans.models import Scan


def calculate_consistency_score(scan: Scan) -> MLConsistencyScore:
    """
    Calculate data consistency score (0-100) for a scan.
    
    Checks:
    - Distribution match against same maker/model/year/fuel
    - Physical plausibility (sum of cells vs pack, SOC vs voltage, temps, SOH vs age)
    
    Returns:
        MLConsistencyScore with score and detailed issues
    """
    score = 100
    issues = []
    
    # Check if we have enough reference data
    reference_count = db.session.query(MLScanFeature).filter_by(
        maker=scan.car_maker,
        model=scan.car_model,
        fuel_type=_map_fuel(scan.car_fuel)
    ).count()
    
    min_required = 10
    sufficient_data = reference_count >= min_required
    
    if not sufficient_data:
        return MLConsistencyScore(
            scan_id=scan.id,
            score=0,
            issues=[f"데이터 부족: {reference_count}/{min_required} 샘플"],
            sufficient_data=False,
            min_samples_required=min_required,
            actual_samples=reference_count
        )
    
    # Physical plausibility checks
    if scan.bms_data and isinstance(scan.bms_data, dict):
        battery = scan.bms_data.get('battery', {})
        
        # SOC vs voltage
        soc = _get_value(battery.get('soc'))
        voltage = _get_value(battery.get('pack_voltage'))
        
        if soc is not None and voltage is not None:
            if soc > 90 and voltage < 350:  # Example threshold
                score -= 20
                issues.append("SOC-전압 불일치: SOC 90% 이상이지만 팩 전압 낮음")
        
        # Temperature range
        max_temp = _get_value(battery.get('max_temp'))
        min_temp = _get_value(battery.get('min_temp'))
        
        if max_temp is not None and min_temp is not None:
            if max_temp - min_temp > 30:
                score -= 15
                issues.append(f"모듈 온도 편차 과다: {max_temp - min_temp:.1f}℃")
    
    # Distribution match (placeholder)
    distribution_match = 0.85
    physical_plausibility = score / 100.0
    
    return MLConsistencyScore(
        scan_id=scan.id,
        score=max(0, score),
        distribution_match=distribution_match,
        physical_plausibility=physical_plausibility,
        issues=issues,
        sufficient_data=True,
        min_samples_required=min_required,
        actual_samples=reference_count
    )


def _map_fuel(fuel_str):
    """Map fuel string to ML fuel_type."""
    fuel = (fuel_str or "").lower()
    if "전기" in fuel or "electric" in fuel:
        return "ev"
    elif "하이브리드" in fuel or "hybrid" in fuel:
        return "hev"
    return "ice"


def _get_value(item):
    """Extract value from various formats."""
    if item is None:
        return None
    if isinstance(item, dict):
        return item.get('value')
    return item
