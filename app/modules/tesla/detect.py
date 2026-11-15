"""Tesla vehicle detection and VIN decoding.

Sources:
- NHTSA vPIC VIN decoder: https://vpic.nhtsa.dot.gov/api/
- joshwardell/model3dbc: https://github.com/joshwardell/model3dbc (MIT License)
- commaai/opendbc: https://github.com/commaai/opendbc/tree/master/opendbc/dbc (MIT License)
"""

import re
from typing import Dict, Any, Optional


# Tesla VIN WMI (World Manufacturer Identifier) prefixes
TESLA_WMI = {
    '5YJ': 'TESLA, INC. (USA - Fremont)',
    '7SA': 'TESLA MOTORS (Austria)',
    'LRW': 'TESLA MOTORS (China)',
    'XP7': 'TESLA (Russia)',
    'SFZ': 'TESLA (UK)',
}

# Model codes (4th character)
MODEL_CODES = {
    '3': 'Model 3',
    'Y': 'Model Y',
    'S': 'Model S',
    'X': 'Model X',
}


def is_tesla(frames: list, vin: str | None = None) -> bool:
    """
    Tesla 차량 여부 판별.
    
    Args:
        frames: CAN 프레임 목록 [(timestamp, can_id, data), ...]
        vin: VIN (있으면 우선 체크)
    
    Returns:
        Tesla 여부
    """
    # VIN WMI 체크
    if vin and len(vin) >= 3:
        wmi = vin[:3].upper()
        if wmi in TESLA_WMI:
            return True
    
    # CAN ID 패턴 체크
    can_ids = {frame[1] for frame in frames if len(frame) >= 2}
    
    # Tesla 고유 ID 존재 확인
    tesla_signature_ids = {0x405, 0x7FF, 0x401, 0x352, 0x332}
    if len(tesla_signature_ids & can_ids) >= 3:
        return True
    
    return False


def detect_model(frames: list, vin: str | None = None) -> str | None:
    """
    Tesla 모델 감지 (Model 3/Y vs S/X).
    
    Args:
        frames: CAN 프레임 목록
        vin: VIN
    
    Returns:
        'Model 3', 'Model Y', 'Model S', 'Model X' 또는 None
    """
    # VIN 4번째 자리로 모델 감지
    if vin and len(vin) >= 4:
        model_char = vin[3].upper()
        if model_char in MODEL_CODES:
            return MODEL_CODES[model_char]
    
    # CAN ID 패턴으로 감지
    can_ids = {frame[1] for frame in frames if len(frame) >= 2}
    
    # Model 3/Y 전용 ID
    model3y_ids = {0x405, 0x401, 0x352, 0x332}
    if len(model3y_ids & can_ids) >= 3:
        # VIN으로 3 vs Y 구분
        if vin and len(vin) >= 4 and vin[3].upper() == 'Y':
            return 'Model Y'
        return 'Model 3'
    
    return None


def decode_vin(vin: str) -> Dict[str, Any]:
    """
    VIN 디코딩.
    
    Args:
        vin: 17자리 VIN
    
    Returns:
        디코딩된 정보 dict
    """
    if not vin or len(vin) != 17:
        return {'valid': False, 'error': 'Invalid VIN length'}
    
    result = {
        'valid': True,
        'vin': vin,
        'wmi': vin[:3],
        'manufacturer': TESLA_WMI.get(vin[:3], 'Unknown'),
        'model_code': vin[3] if len(vin) > 3 else None,
        'model': MODEL_CODES.get(vin[3], 'Unknown') if len(vin) > 3 else 'Unknown',
        'year_code': vin[9] if len(vin) > 9 else None,
        'year': decode_year(vin[9]) if len(vin) > 9 else None,
    }
    
    return result


def decode_year(year_code: str) -> int | None:
    """
    VIN 10번째 자리 (연식 코드) 디코딩.
    
    Args:
        year_code: 연식 코드 (1자)
    
    Returns:
        연식 (YYYY) 또는 None
    """
    # 2010-2039 매핑
    year_map = {
        'A': 2010, 'B': 2011, 'C': 2012, 'D': 2013, 'E': 2014,
        'F': 2015, 'G': 2016, 'H': 2017, 'J': 2018, 'K': 2019,
        'L': 2020, 'M': 2021, 'N': 2022, 'P': 2023, 'R': 2024,
        'S': 2025, 'T': 2026, 'V': 2027, 'W': 2028, 'X': 2029,
        'Y': 2030, '1': 2031, '2': 2032, '3': 2033, '4': 2034,
        '5': 2035, '6': 2036, '7': 2037, '8': 2038, '9': 2039,
    }
    return year_map.get(year_code.upper())


def extract_vin_from_frames(frames: list) -> str | None:
    """
    0x405 멀티플렉스에서 VIN 추출.
    
    Args:
        frames: CAN 프레임 목록 [(timestamp, can_id, data), ...]
    
    Returns:
        VIN 문자열 또는 None
    """
    vin_parts = {}
    
    for frame in frames:
        if len(frame) < 3:
            continue
        
        ts, can_id, data = frame[0], frame[1], frame[2]
        
        if can_id != 0x405 or len(data) < 8:
            continue
        
        # Multiplex 인덱스 (첫 바이트)
        mux = data[0]
        
        # 0x10: VIN 첫 7자
        # 0x11: VIN 중간 7자
        # 0x12: VIN 마지막 3자
        if mux == 0x10:
            vin_parts[0] = data[1:8].decode('ascii', errors='ignore')
        elif mux == 0x11:
            vin_parts[1] = data[1:8].decode('ascii', errors='ignore')
        elif mux == 0x12:
            vin_parts[2] = data[1:4].decode('ascii', errors='ignore')
    
    if len(vin_parts) == 3:
        vin = vin_parts[0] + vin_parts[1] + vin_parts[2]
        if len(vin) == 17:
            return vin
    
    return None
