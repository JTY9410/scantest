"""Tesla SOH (State of Health) calculation."""

from typing import Dict, Any, Optional, Tuple
from app.modules.scans.battery_soh import prepare_soh_report_data


def calculate_soh(current_nominal_full: float, 
                 manufacturer: str,
                 model: str,
                 year: int | None = None,
                 pack_code: str | None = None,
                 bol_energy: float | None = None,
                 vin: str | None = None) -> Dict[str, Any]:
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
    
    # Use comprehensive reference capacity lookup with like-for-like matching
    # Assume Tesla current_nominal_full is gross capacity
    soh_data = prepare_soh_report_data(
        current_capacity_kwh=current_nominal_full,
        current_capacity_type='gross',
        maker=manufacturer,
        model=model,
        year=year,
        trim=pack_code,
        vin=vin  # VIN for WMI/model/year/plant matching
    )
    
    result['reference_capacity'] = soh_data['reference_capacity_kwh']
    result['reference_source'] = soh_data['reference_source']
    result['reference_verification_level'] = soh_data['reference_verification_level']
    result['candidates'] = soh_data.get('candidates', [])
    
    if soh_data['soh_status']:
        # Could not calculate SOH (multiple candidates or no reference)
        result['soh_available'] = False
        result['soh_status'] = soh_data['soh_status']  # Add explicit soh_status field for ML extractor
        result['calculation_note'] = soh_data['soh_status']
        if soh_data['candidates']:
            result['warnings'].append(f"팩 후보 {len(soh_data['candidates'])}개: 관리자 팩ID 선택 필요")
    elif soh_data['soh_percent']:
        # SOH calculated successfully
        result['soh_percent'] = round(soh_data['soh_percent'], 1)
        result['soh_available'] = True
        ref_type_label = {
            'gross': '총용량',
            'net': '사용가능',
            '공표': '공표'
        }.get(soh_data['reference_capacity_type'], '총용량')
        result['calculation_note'] = (
            f'기준: {soh_data["reference_capacity_kwh"]:.2f} kWh '
            f'({ref_type_label}, {soh_data["reference_source"]})'
        )
        # Add reference-only info if community source
        if '2차 자료' in (soh_data['reference_source'] or ''):
            result['soh_percent_reference'] = result['soh_percent']
            result['soh_available'] = False  # Mark as reference only
            result['warnings'].append('2차 자료 출처는 참고용 → 공식 SOH 판정보류')
    else:
        result['soh_available'] = False
        result['calculation_note'] = '기준 용량 미등록 → SOH 산정불가'
    
    return result


def cross_check_soh(soh_result: Dict[str, Any],
                   soc_ui: float | None,
                   nominal_remaining: float | None) -> Dict[str, Any]:
    """
    SOH 교차 검증.
    
    잔여 에너지 ÷ SOC로 추정한 만충 에너지와 비교.
    
    Args:
        soh_result: calculate_soh 결과
        soc_ui: UI/displayed SOC (%) - 사용자가 보는 표시 SOC
        nominal_remaining: 공칭 잔여 에너지 (kWh)
    
    Returns:
        교차 검증 결과 추가된 dict
    """
    if not soc_ui or not nominal_remaining or soc_ui <= 0:
        return soh_result
    
    # 잔여 에너지 ÷ SOC로 만충 추정
    estimated_full = (nominal_remaining / soc_ui) * 100
    
    soh_result['cross_check'] = {
        'estimated_full_from_soc': round(estimated_full, 2),
        'method': f'{nominal_remaining:.2f} kWh ÷ {soc_ui:.1f}% × 100',
    }
    
    current_full = soh_result['current_nominal_full']
    diff_percent = abs(estimated_full - current_full) / current_full * 100
    
    soh_result['cross_check']['difference_percent'] = round(diff_percent, 1)
    
    if diff_percent > 5:
        soh_result['warnings'].append(
            f'교차 검증 편차 {diff_percent:.1f}% (현재 {current_full:.2f} vs 추정 {estimated_full:.2f} kWh)'
        )
    
    return soh_result
