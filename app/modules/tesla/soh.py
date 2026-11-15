"""Tesla SOH (State of Health) calculation."""

from typing import Dict, Any, Optional, Tuple
from app.modules.scans.battery_capacity import find_reference_capacity, BatteryReferenceCapacity


def calculate_soh(current_nominal_full: float, 
                 manufacturer: str,
                 model: str,
                 year: int | None = None,
                 pack_code: str | None = None,
                 bol_energy: float | None = None) -> Dict[str, Any]:
    """
    SOH 계산.
    
    SOH = (현재 공칭 만충 에너지 / 기준 공칭 만충 에너지) × 100
    
    Args:
        current_nominal_full: 현재 공칭 만충 에너지 (kWh) from 0x352
        manufacturer: 제조사
        model: 모델명
        year: 연식
        pack_code: 팩 코드
        bol_energy: BOL 에너지 (0x292, kWh)
    
    Returns:
        SOH 결과 dict
    """
    result = {
        'current_nominal_full': current_nominal_full,
        'soh_available': False,
        'soh_percent': None,
        'reference_capacity': None,
        'reference_source': None,
        'calculation_note': None,
        'warnings': [],
    }
    
    # BOL 에너지 체크 (신호값이 정상 범위인지)
    if bol_energy and 40 <= bol_energy <= 120:
        # BOL 값이 정상 범위이면 기준으로 사용
        result['reference_capacity'] = bol_energy
        result['reference_source'] = 'vehicle_bol_signal'
        result['soh_percent'] = round((current_nominal_full / bol_energy) * 100, 1)
        result['soh_available'] = True
        result['calculation_note'] = f'차량 신호 BOL 에너지 {bol_energy:.2f} kWh 기준'
        return result
    elif bol_energy:
        result['warnings'].append(f'BOL 에너지 신호 {bol_energy:.2f} kWh는 비정상 범위 (40-120 kWh 밖)')
    
    # 기준 용량 테이블 조회
    ref_cap = find_reference_capacity(manufacturer, model, year, pack_code)
    
    if not ref_cap:
        result['soh_available'] = False
        result['calculation_note'] = '기준 용량 미등록 → SOH 산정불가 → 판정보류'
        return result
    
    # official/government만 확정 SOH로 사용
    if ref_cap.source_type in ['official', 'government']:
        result['reference_capacity'] = ref_cap.reference_energy_kwh
        result['reference_source'] = ref_cap.source_type
        result['reference_url'] = ref_cap.source_url
        result['reference_definition'] = ref_cap.reference_definition
        result['soh_percent'] = round((current_nominal_full / ref_cap.reference_energy_kwh) * 100, 1)
        result['soh_available'] = True
        result['calculation_note'] = (
            f'기준: {ref_cap.reference_energy_kwh:.2f} kWh '
            f'({ref_cap.reference_definition or "공칭 만충"}, {ref_cap.source_type})'
        )
    
    # community 출처는 참고치로만
    elif ref_cap.source_type == 'community':
        result['reference_capacity'] = ref_cap.reference_energy_kwh
        result['reference_source'] = 'community'
        result['reference_url'] = ref_cap.source_url
        result['soh_percent_reference'] = round((current_nominal_full / ref_cap.reference_energy_kwh) * 100, 1)
        result['soh_available'] = False
        result['calculation_note'] = (
            f'참고 비율 {result["soh_percent_reference"]:.1f}% '
            f'(커뮤니티 출처 {ref_cap.reference_energy_kwh:.2f} kWh 대비, 미검증)'
        )
        result['warnings'].append('커뮤니티 출처는 공식 SOH로 채택하지 않음 → 판정보류')
    
    return result


def cross_check_soh(soh_result: Dict[str, Any],
                   soc_ave: float | None,
                   nominal_remaining: float | None) -> Dict[str, Any]:
    """
    SOH 교차 검증.
    
    잔여 에너지 ÷ SOC로 추정한 만충 에너지와 비교.
    
    Args:
        soh_result: calculate_soh 결과
        soc_ave: 평균 SOC (%)
        nominal_remaining: 공칭 잔여 에너지 (kWh)
    
    Returns:
        교차 검증 결과 추가된 dict
    """
    if not soc_ave or not nominal_remaining or soc_ave <= 0:
        return soh_result
    
    # 잔여 에너지 ÷ SOC로 만충 추정
    estimated_full = (nominal_remaining / soc_ave) * 100
    
    soh_result['cross_check'] = {
        'estimated_full_from_soc': round(estimated_full, 2),
        'method': f'{nominal_remaining:.2f} kWh ÷ {soc_ave:.1f}% × 100',
    }
    
    current_full = soh_result['current_nominal_full']
    diff_percent = abs(estimated_full - current_full) / current_full * 100
    
    soh_result['cross_check']['difference_percent'] = round(diff_percent, 1)
    
    if diff_percent > 5:
        soh_result['warnings'].append(
            f'교차 검증 편차 {diff_percent:.1f}% (현재 {current_full:.2f} vs 추정 {estimated_full:.2f} kWh)'
        )
    
    return soh_result
