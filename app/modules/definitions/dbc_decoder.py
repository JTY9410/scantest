"""DBC 브로드캐스트 CAN 프레임 디코딩

요청-응답이 아닌 주기적 브로드캐스트 CAN 프레임을 DBC 정의로 디코딩.
"""
from typing import Any

from app.extensions import db
from app.modules.definitions.models import DbcMessage, DbcSignal, VehicleDefinition
from app.modules.definitions.decoder import is_valid_value


def extract_signal_value(data: bytes, signal: DbcSignal) -> float | None:
    """DBC 신호 비트 추출 및 변환
    
    Args:
        data: CAN 프레임 데이터 (8바이트)
        signal: DbcSignal 정의
    
    Returns:
        변환된 값 또는 None
    """
    if len(data) == 0:
        return None
    
    try:
        # 바이트를 비트 배열로 변환
        bits = []
        for byte in data:
            for i in range(8):
                bits.append((byte >> i) & 1)
        
        # start_bit부터 bit_length만큼 추출
        start = signal.start_bit
        length = signal.bit_length
        
        if start + length > len(bits):
            return None
        
        # 비트 추출 (byte_order 고려)
        extracted_bits = bits[start:start+length]
        
        # 정수로 변환
        if signal.byte_order == 'big':
            # Big endian (MSB first)
            raw_value = 0
            for i, bit in enumerate(extracted_bits):
                raw_value |= (bit << (length - 1 - i))
        else:
            # Little endian (LSB first)
            raw_value = 0
            for i, bit in enumerate(extracted_bits):
                raw_value |= (bit << i)
        
        # 부호 처리
        if signal.value_type == 'signed':
            # 2의 보수
            if raw_value >= (1 << (length - 1)):
                raw_value -= (1 << length)
        
        # 스케일 및 오프셋 적용
        physical_value = raw_value * signal.factor + signal.offset
        
        return physical_value
    
    except Exception:
        return None


def decode_dbc_frame(can_id: int, data: bytes, maker: str | None = None, model: str | None = None) -> dict[str, Any]:
    """DBC 프레임 디코딩
    
    Args:
        can_id: CAN ID (정수)
        data: 프레임 데이터
        maker: 제조사 (차량 매칭용)
        model: 모델 (차량 매칭용)
    
    Returns:
        {signal_name: {'value': ..., 'unit': ..., 'valid': bool}}
    """
    # 차량 정의 조회 (maker/model 매칭)
    vehicle_defs = []
    if maker:
        query = db.session.query(VehicleDefinition).filter_by(maker=maker)
        if model:
            query = query.filter(
                (VehicleDefinition.model == model) |
                (VehicleDefinition.model.is_(None))
            )
        vehicle_defs = query.all()
    
    if not vehicle_defs:
        # 매칭 실패 시 전체 DBC에서 검색
        vehicle_defs = db.session.query(VehicleDefinition).all()
    
    vehicle_def_ids = [vd.id for vd in vehicle_defs]
    
    if not vehicle_def_ids:
        return {}
    
    # CAN ID로 메시지 찾기
    messages = db.session.query(DbcMessage).filter(
        DbcMessage.can_id == can_id,
        DbcMessage.vehicle_definition_id.in_(vehicle_def_ids)
    ).all()
    
    if not messages:
        return {}
    
    decoded = {}
    
    for message in messages:
        # 메시지의 신호들 조회
        signals = db.session.query(DbcSignal).filter_by(message_id=message.id).all()
        
        for signal in signals:
            value = extract_signal_value(data, signal)
            
            if value is None:
                continue
            
            # 타당성 검증
            valid = True
            
            # min/max 범위 체크
            if signal.min_value is not None and value < signal.min_value:
                valid = False
            if signal.max_value is not None and value > signal.max_value:
                valid = False
            
            # 물리적 타당성 체크 (기존 범위 재사용)
            if signal.unit:
                unit_lower = signal.unit.lower()
                if '%' in unit_lower or 'soc' in signal.signal_name.lower():
                    valid = valid and is_valid_value(value, 'soc_pct')
                elif 'v' in unit_lower and 'voltage' in signal.signal_name.lower():
                    if 'pack' in signal.signal_name.lower() or 'battery' in signal.signal_name.lower():
                        valid = valid and is_valid_value(value, 'pack_voltage_v')
                    elif 'cell' in signal.signal_name.lower():
                        valid = valid and is_valid_value(value * 1000, 'cell_voltage_mv')
                elif 'a' in unit_lower and 'current' in signal.signal_name.lower():
                    valid = valid and is_valid_value(value, 'pack_current_a')
                elif 'c' in unit_lower or 'temp' in signal.signal_name.lower():
                    valid = valid and is_valid_value(value, 'temp_c')
            
            decoded[signal.signal_name] = {
                'value': round(value, 3) if isinstance(value, float) else value,
                'unit': signal.unit,
                'valid': valid,
                'message_name': message.message_name,
                'can_id': f"0x{can_id:X}",
            }
    
    return decoded


def decode_broadcast_frames(can_frames: list[dict], maker: str | None = None, model: str | None = None) -> dict[int, dict]:
    """브로드캐스트 CAN 프레임들을 DBC로 디코딩
    
    Args:
        can_frames: CAN 프레임 리스트 [{'can_id': ..., 'data': ..., 'timestamp': ...}]
        maker: 제조사
        model: 모델
    
    Returns:
        {can_id: {signal_name: decoded_info}}
    """
    # CAN ID별로 최신 프레임만 유지
    latest_frames = {}
    for frame in can_frames:
        can_id_str = frame.get('can_id', '').upper()
        
        # CAN ID 파싱
        try:
            if can_id_str.startswith('0X'):
                can_id = int(can_id_str, 16)
            elif can_id_str.startswith('0'):
                can_id = int(can_id_str, 16)
            else:
                can_id = int(can_id_str)
        except ValueError:
            continue
        
        # 요청/응답 ID는 제외 (7DF, 7E0-7EF, 7C6 등)
        if 0x7C0 <= can_id <= 0x7FF:
            continue
        
        # 최신 프레임만 유지
        latest_frames[can_id] = frame
    
    # 각 CAN ID 디코딩
    all_decoded = {}
    for can_id, frame in latest_frames.items():
        data_str = frame.get('data', '')
        try:
            data_bytes = bytes([int(b, 16) for b in data_str.strip().split()])
        except (ValueError, AttributeError):
            continue
        
        decoded = decode_dbc_frame(can_id, data_bytes, maker, model)
        if decoded:
            all_decoded[can_id] = decoded
    
    return all_decoded
