"""Battery SOH calculation with reference capacity matching."""

from typing import Tuple, Optional, Dict, List, Any
from app.modules.scans.battery_capacity import BatteryReferenceCapacity, find_reference_capacity
from app.extensions import db


def find_matching_references(
    maker: str,
    model: str,
    year: Optional[int] = None,
    trim: Optional[str] = None,
    vin: Optional[str] = None
) -> List[BatteryReferenceCapacity]:
    """
    Find all matching reference capacity entries.
    
    Matching logic:
    1. maker + model (required, but model can be overridden by VIN for Tesla)
    2. year (if provided, must be within year_from/year_to range)
    3. trim (if provided, must match)
    4. Tesla VIN decoding (if VIN provided and maker is Tesla, overrides model/year)
    
    Returns:
        List of matching references (may be multiple candidates)
    """
    # Tesla VIN decoding FIRST: override model and year before building query
    if vin and maker.lower() == 'tesla':
        from app.modules.tesla.vin_decoder import decode_tesla_vin
        decoded = decode_tesla_vin(vin)
        
        if decoded.get('valid'):
            # Override model and year from VIN decode
            if decoded.get('model'):
                model = decoded['model']
            if decoded.get('year'):
                year = decoded['year']
    
    # Start query with maker and model
    query = db.session.query(BatteryReferenceCapacity).filter_by(maker=maker, model=model)
    
    # Year filter
    if year:
        query = query.filter(
            (BatteryReferenceCapacity.year_from.is_(None) | (BatteryReferenceCapacity.year_from <= year)),
            (BatteryReferenceCapacity.year_to.is_(None) | (BatteryReferenceCapacity.year_to >= year))
        )
    
    # Trim filter
    if trim:
        query = query.filter_by(trim=trim)
    
    # WMI filter for Tesla
    if vin and maker.lower() == 'tesla':
        wmi = vin[:3] if len(vin) >= 3 else None
        if wmi:
            query = query.filter(
                (BatteryReferenceCapacity.vin_wmi.is_(None)) | 
                (BatteryReferenceCapacity.vin_wmi == wmi)
            )
    
    # Order by verification level (official first)
    results = query.order_by(
        BatteryReferenceCapacity.verification_level.desc()
    ).all()
    
    return results


def calculate_soh(
    current_capacity_kwh: float,
    current_capacity_type: str,  # 'gross' or 'net'
    reference: BatteryReferenceCapacity
) -> Tuple[Optional[float], Optional[str]]:
    """
    Calculate SOH using like-for-like comparison.
    
    Rules:
    - Gross current capacity → compare to gross reference
    - Net current capacity → compare to net reference
    - If types don't match, return (None, reason)
    
    Returns:
        (soh_percent, error_reason)
    """
    if current_capacity_type == 'gross':
        ref_capacity = reference.gross_capacity_kwh
        if not ref_capacity:
            return None, '기준 총용량 없음'
    elif current_capacity_type == 'net':
        ref_capacity = reference.net_capacity_kwh
        if not ref_capacity:
            return None, '기준 사용가능용량 없음'
    else:
        return None, f'알 수 없는 용량 유형: {current_capacity_type}'
    
    if ref_capacity <= 0:
        return None, '기준용량이 0 이하'
    
    soh = (current_capacity_kwh / ref_capacity) * 100.0
    return soh, None


def prepare_soh_report_data(
    current_capacity_kwh: float,
    current_capacity_type: str,
    maker: str,
    model: str,
    year: Optional[int] = None,
    trim: Optional[str] = None,
    vin: Optional[str] = None
) -> Dict[str, Any]:
    """
    Prepare SOH report data with reference capacity lookup.
    
    Returns dict with:
    - reference_capacity_kwh: float or None
    - reference_capacity_type: 'gross' or 'net' or None
    - reference_source: '제조사 공표 기준' or '2차 자료 기준(참고)' or None
    - reference_verification_level: str or None
    - soh_percent: float or None
    - soh_status: '미산정' with reason, or '팩 후보 다수 — 팩ID 확인 필요', or None (success)
    - candidates: List[dict] if multiple matches
    """
    matches = find_matching_references(maker, model, year, trim, vin)
    
    if not matches:
        return {
            'reference_capacity_kwh': None,
            'reference_capacity_type': None,
            'reference_source': None,
            'reference_verification_level': None,
            'soh_percent': None,
            'soh_status': '미산정 (기준용량 정보 없음)',
            'candidates': []
        }
    
    if len(matches) > 1:
        # Multiple candidates - don't auto-select
        candidates_data = []
        for m in matches:
            cap = m.gross_capacity_kwh or m.net_capacity_kwh or m.official_capacity_kwh
            candidates_data.append({
                'pack_id': m.pack_id,
                'trim': m.trim,
                'capacity_kwh': cap,
                'verification_level': m.verification_level,
                'year_range': f"{m.year_from or '?'}-{m.year_to or '?'}"
            })
        
        return {
            'reference_capacity_kwh': None,
            'reference_capacity_type': None,
            'reference_source': None,
            'reference_verification_level': None,
            'soh_percent': None,
            'soh_status': '팩 후보 다수 — 팩ID 확인 필요',
            'candidates': candidates_data
        }
    
    # Single match - calculate SOH
    reference = matches[0]
    soh_percent, error_reason = calculate_soh(current_capacity_kwh, current_capacity_type, reference)
    
    # Determine reference capacity and type
    if current_capacity_type == 'gross' and reference.gross_capacity_kwh:
        ref_capacity = reference.gross_capacity_kwh
        ref_type = 'gross'
    elif current_capacity_type == 'net' and reference.net_capacity_kwh:
        ref_capacity = reference.net_capacity_kwh
        ref_type = 'net'
    else:
        ref_capacity = reference.gross_capacity_kwh or reference.net_capacity_kwh or reference.official_capacity_kwh
        ref_type = 'gross' if reference.gross_capacity_kwh else ('net' if reference.net_capacity_kwh else '공표')
    
    # Determine source label
    if reference.verification_level in ['제조사 공표', '높음', 'official']:
        source_label = '제조사 공표 기준'
    else:
        source_label = '2차 자료 기준(참고)'
    
    result = {
        'reference_capacity_kwh': ref_capacity,
        'reference_capacity_type': ref_type,
        'reference_source': source_label,
        'reference_verification_level': reference.verification_level,
        'soh_percent': soh_percent,
        'soh_status': f'미산정 ({error_reason})' if error_reason else None,
        'candidates': [],
        'reference_notes': reference.notes,
        'reference_warnings': reference.warnings
    }
    
    return result
