"""WESCAN 등급 계산

기존 scanner/report.py의 threshold 로직 재사용.
새로운 threshold를 발명하지 않고 기존 검증된 값만 사용.
"""
from typing import Any


UNREAD = "측정불가"
GOOD = "양호"
CAUTION = "주의"
UNRATED = "미평가"


def compute_wescan_grades(result: dict[str, Any]) -> list[dict]:
    """WESCAN 스타일 등급 계산
    
    기존 threshold (scanner/report.py judgments):
    - SOH >= 80%: 양호
    - 절연 저항 >= 500 kΩ: 양호
    - 셀 전압 편차 <= 1.0V: 양호
    - 모듈 온도 편차 <= 20°C: 양호
    
    Args:
        result: analyzer 결과 (battery, vehicle_info, dtcs 등)
    
    Returns:
        [{'item': ..., 'standard': ..., 'value': ..., 'unit': ..., 'result': ...}]
    """
    grades = []
    battery = result.get('battery', {})
    dtcs = result.get('dtcs', [])
    
    # 1. SOH (배터리 수명)
    if 'soh_pct' in battery:
        soh = battery['soh_pct']
        grades.append({
            'item': '배터리 수명 (SOH)',
            'standard': 'SOH 80% 이상 시 양호',
            'value': soh,
            'unit': '%',
            'result': GOOD if soh >= 80 else CAUTION,
        })
    
    # 2. 절연 저항
    # Note: isolation_kohm은 BMS 0x0101 byte 57-58에 있지만
    # 현재 decoder에 구현되지 않았으므로 broadcast_signals에서 찾거나 UNREAD
    isolation = battery.get('isolation_kohm')
    if isolation is None:
        # broadcast_signals에서 찾기
        broadcast = result.get('broadcast_signals', {})
        for signal_name, info in broadcast.items():
            if 'isolation' in signal_name.lower() or 'insulation' in signal_name.lower():
                if info.get('unit', '').lower() in ['kohm', 'kω', 'kΩ']:
                    isolation = info['value']
                    break
    
    if isolation is not None:
        grades.append({
            'item': '절연 저항',
            'standard': '절연저항 500 kΩ 이상 시 양호',
            'value': isolation,
            'unit': 'kΩ',
            'result': GOOD if isolation >= 500 else CAUTION,
        })
    
    # 3. 셀 전압 편차
    max_cell = battery.get('max_cell_voltage_v')
    min_cell = battery.get('min_cell_voltage_v')
    
    if max_cell is not None and min_cell is not None:
        spread = round(max_cell - min_cell, 3)
        grades.append({
            'item': '셀 전압 편차',
            'standard': '셀 전압 최대-최소 차이 1.0V 이하 시 양호',
            'value': spread,
            'unit': 'V',
            'result': GOOD if spread <= 1.0 else CAUTION,
        })
    
    # 4. 모듈 온도 편차
    max_temp = battery.get('max_temp_c')
    min_temp = battery.get('min_temp_c')
    
    if max_temp is not None and min_temp is not None:
        spread = round(max_temp - min_temp, 1)
        grades.append({
            'item': '모듈 온도 편차',
            'standard': '모듈 온도 최대-최소 차이 20°C 이하 시 양호',
            'value': spread,
            'unit': '°C',
            'result': GOOD if spread <= 20 else CAUTION,
        })
    
    # 5. DTC (고장코드)
    dtc_count = len(dtcs)
    if dtc_count > 0:
        grades.append({
            'item': '고장 코드 (DTC)',
            'standard': 'DTC 없음 시 양호',
            'value': dtc_count,
            'unit': '개',
            'result': CAUTION,
        })
    else:
        grades.append({
            'item': '고장 코드 (DTC)',
            'standard': 'DTC 없음 시 양호',
            'value': 0,
            'unit': '개',
            'result': GOOD,
        })
    
    return grades
