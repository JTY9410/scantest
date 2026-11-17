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
    decoded = None
    if vin and maker.lower() == 'tesla':
        from app.modules.tesla.vin_decoder import decode_tesla_vin
        decoded = decode_tesla_vin(vin)
        
        # Override model and year from VIN decode (even if not fully 'valid')
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
    
    # WMI filter for Tesla (critical for distinguishing 5YJ vs LRW)
    if decoded and decoded.get('wmi'):
        query = query.filter(
            (BatteryReferenceCapacity.vin_wmi.is_(None)) | 
            (BatteryReferenceCapacity.vin_wmi == decoded['wmi'])
        )
    
    # Exclude manual rows explicitly, but allow NULL (tests/legacy) and other sources
    # SQL: NULL != 'manual' evaluates to NULL (falsy), so use explicit OR with is_(None)
    from sqlalchemy import and_, or_
    query = query.filter(
        or_(
            BatteryReferenceCapacity.source_file.is_(None),  # Allow NULL (tests, legacy imports)
            BatteryReferenceCapacity.source_file != 'manual'  # Exclude manual rows
        )
    )
    
    # Only exclude rows with ALL three capacity columns NULL (completely unusable)
    # Also exclude rows where ONLY official_capacity_kwh is set and it's implausible (not battery kWh)
    # Plausible range: 10-250 kWh for automotive batteries
    from sqlalchemy import and_, case
    
    query = query.filter(
        or_(
            # Has gross or net (always usable)
            BatteryReferenceCapacity.gross_capacity_kwh.isnot(None),
            BatteryReferenceCapacity.net_capacity_kwh.isnot(None),
            # OR has plausible official_capacity_kwh (10-250 kWh range)
            and_(
                BatteryReferenceCapacity.official_capacity_kwh.isnot(None),
                BatteryReferenceCapacity.official_capacity_kwh >= 10,
                BatteryReferenceCapacity.official_capacity_kwh <= 250
            )
        )
    )
    
    # Order by verification level (official first)
    results = query.order_by(
        BatteryReferenceCapacity.verification_level.desc()
    ).all()
    
    # Deduplicate by pack_id (keep first occurrence for each pack_id)
    seen_pack_ids = set()
    seen_combos = set()  # For rows without pack_id, dedupe by (model, trim, capacity)
    deduped_results = []
    
    for r in results:
        if r.pack_id:
            # Has pack_id: dedupe by pack_id
            if r.pack_id not in seen_pack_ids:
                seen_pack_ids.add(r.pack_id)
                deduped_results.append(r)
        else:
            # No pack_id: dedupe by (model, trim, capacity_kwh)
            capacity = r.gross_capacity_kwh or r.net_capacity_kwh or r.official_capacity_kwh
            combo_key = (r.model, r.trim or '', round(capacity, 1) if capacity else None)
            if combo_key not in seen_combos:
                seen_combos.add(combo_key)
                deduped_results.append(r)
    
    # Check if all candidates have the same gross capacity
    if len(deduped_results) > 1:
        capacities = {r.gross_capacity_kwh for r in deduped_results if r.gross_capacity_kwh}
        if len(capacities) == 1:
            # All same capacity → SOH can be computed, list all candidate IDs
            pass  # return all
        # Otherwise → multiple different capacities, '팩 후보 다수'
    
    return deduped_results


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
        # Check if all candidates have the same gross capacity
        capacities = {m.gross_capacity_kwh for m in matches if m.gross_capacity_kwh}
        
        if len(capacities) > 1:
            # Different capacities - don't auto-select, SOH 미산정
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
        # else: same capacity across all → compute SOH below, list candidate pack IDs
    
    # Single match or multiple with same capacity - calculate SOH
    reference = matches[0]
    soh_percent, error_reason = calculate_soh(current_capacity_kwh, current_capacity_type, reference)
    
    # Collect all candidate pack IDs (for same-capacity multi-candidate case)
    candidate_pack_ids = [m.pack_id for m in matches if m.pack_id]
    
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
    
    # If multiple matches with same capacity, list candidate pack IDs
    if len(candidate_pack_ids) > 1:
        result['candidate_pack_ids'] = candidate_pack_ids

    return result
