"""CAN/OBD-II 프레임 디코더 및 ISO-TP 재조립"""
import re
from typing import Any
from collections import defaultdict

import cantools


def parse_can_frame(data_str: str) -> list[int]:
    """CAN 데이터 문자열을 바이트 리스트로 변환
    
    예: "02 01 00 00 00 00 00 00" -> [0x02, 0x01, 0x00, ...]
    """
    return [int(b, 16) for b in data_str.strip().split()]


def reassemble_isotp_frames(frames: list[dict]) -> dict[str, bytes]:
    """ISO-TP 멀티프레임 재조립
    
    첫 프레임: 1x yy yy ... (x = 데이터 길이 상위 4비트)
    연속 프레임: 2x yy yy ... (x = 시퀀스 번호 0-F)
    
    Returns:
        {ecu_id: reassembled_data}
    """
    sessions = defaultdict(lambda: {'length': 0, 'data': bytearray(), 'seq': 0})
    completed = {}
    
    for frame in frames:
        can_id = frame['can_id']
        data = parse_can_frame(frame['data'])
        
        if not data:
            continue
        
        pci = data[0]
        
        # 단일 프레임: 0x yy yy ...
        if (pci & 0xF0) == 0x00:
            length = pci & 0x0F
            completed[can_id] = bytes(data[1:1+length])
        
        # 첫 프레임: 1x yy yy ...
        elif (pci & 0xF0) == 0x10:
            length = ((pci & 0x0F) << 8) | data[1]
            sessions[can_id]['length'] = length
            sessions[can_id]['data'] = bytearray(data[2:])
            sessions[can_id]['seq'] = 1
        
        # 연속 프레임: 2x yy yy ...
        elif (pci & 0xF0) == 0x20:
            seq = pci & 0x0F
            if can_id in sessions and sessions[can_id]['seq'] == seq:
                sessions[can_id]['data'].extend(data[1:])
                sessions[can_id]['seq'] = (seq + 1) % 16
                
                # 완료 확인
                if len(sessions[can_id]['data']) >= sessions[can_id]['length']:
                    completed[can_id] = bytes(sessions[can_id]['data'][:sessions[can_id]['length']])
                    del sessions[can_id]
    
    return completed


def decode_mode01_response(data: bytes) -> dict[str, Any]:
    """Mode 01 (현재 데이터) 응답 디코딩
    
    응답 형식: 41 PID [data bytes]
    """
    if len(data) < 2 or data[0] != 0x41:
        return {}
    
    pid = data[1]
    values = {}
    
    # Mode 01 표준 PIDs (SAE J1979)
    if pid == 0x00 and len(data) >= 6:  # 지원 PIDs
        supported = int.from_bytes(data[2:6], 'big')
        values['supported_pids_01_20'] = f"0x{supported:08X}"
    
    elif pid == 0x01 and len(data) >= 6:  # Monitor status
        mil = (data[2] & 0x80) >> 7
        dtc_count = data[2] & 0x7F
        values['mil_status'] = 'ON' if mil else 'OFF'
        values['dtc_count'] = dtc_count
    
    elif pid == 0x04 and len(data) >= 3:  # 엔진 부하
        values['engine_load_pct'] = round(data[2] * 100 / 255, 1)
    
    elif pid == 0x05 and len(data) >= 3:  # 냉각수 온도
        values['coolant_temp_c'] = data[2] - 40
    
    elif pid == 0x0C and len(data) >= 4:  # 엔진 RPM
        values['engine_rpm'] = ((data[2] << 8) | data[3]) / 4
    
    elif pid == 0x0D and len(data) >= 3:  # 차속
        values['vehicle_speed_kmh'] = data[2]
    
    elif pid == 0x0F and len(data) >= 3:  # 흡기 온도
        values['intake_temp_c'] = data[2] - 40
    
    elif pid == 0x11 and len(data) >= 3:  # 스로틀 위치
        values['throttle_position_pct'] = round(data[2] * 100 / 255, 1)
    
    elif pid == 0x20 and len(data) >= 6:  # 지원 PIDs 21-40
        supported = int.from_bytes(data[2:6], 'big')
        values['supported_pids_21_40'] = f"0x{supported:08X}"
    
    elif pid == 0x40 and len(data) >= 6:  # 지원 PIDs 41-60
        supported = int.from_bytes(data[2:6], 'big')
        values['supported_pids_41_60'] = f"0x{supported:08X}"
    
    elif pid == 0x60 and len(data) >= 6:  # 지원 PIDs 61-80
        supported = int.from_bytes(data[2:6], 'big')
        values['supported_pids_61_80'] = f"0x{supported:08X}"
    
    elif pid == 0x80 and len(data) >= 6:  # 지원 PIDs 81-A0
        supported = int.from_bytes(data[2:6], 'big')
        values['supported_pids_81_a0'] = f"0x{supported:08X}"
    
    return values


def decode_mode09_response(data: bytes) -> dict[str, Any]:
    """Mode 09 (차량 정보) 응답 디코딩
    
    응답 형식: 49 PID [data bytes]
    """
    if len(data) < 2 or data[0] != 0x49:
        return {}
    
    pid = data[1]
    values = {}
    
    if pid == 0x00 and len(data) >= 6:  # 지원 PIDs
        supported = int.from_bytes(data[2:6], 'big')
        values['supported_pids_mode09'] = f"0x{supported:08X}"
    
    elif pid == 0x02:  # VIN
        vin_bytes = data[2:]
        values['vin'] = vin_bytes.decode('ascii', errors='ignore').strip('\x00')
    
    return values


def decode_uds22_response(data: bytes, did: int) -> dict[str, Any]:
    """UDS 0x22 (ReadDataByIdentifier) 응답 디코딩
    
    응답 형식: 62 DID_H DID_L [data bytes]
    """
    if len(data) < 3 or data[0] != 0x62:
        return {}
    
    response_did = (data[1] << 8) | data[2]
    if response_did != did:
        return {}
    
    payload = data[3:]
    values = {}
    
    # Hyundai/Kia EV BMS DIDs
    if did == 0x0101:  # 220101: BMS 주요 데이터
        if len(payload) >= 6:
            values['bms_soc_pct'] = round(payload[0] / 2.0, 1)
            values['bms_soh_pct'] = round(payload[1] / 2.0, 1)
            values['bms_voltage_v'] = round(((payload[2] << 8) | payload[3]) / 10.0, 1)
            values['bms_current_a'] = round((((payload[4] << 8) | payload[5]) - 32768) / 10.0, 1)
    
    elif did == 0x0105:  # 220105: 배터리 온도
        if len(payload) >= 4:
            values['bms_temp_inlet_c'] = payload[0] - 40
            values['bms_temp_max_c'] = payload[1] - 40
            values['bms_temp_min_c'] = payload[2] - 40
    
    elif did == 0x0102:  # 220102: 셀 전압
        if len(payload) >= 2:
            values['cell_voltage_max_mv'] = (payload[0] << 8) | payload[1]
            if len(payload) >= 4:
                values['cell_voltage_min_mv'] = (payload[2] << 8) | payload[3]
    
    return values


def decode_kwp21_response(data: bytes, pid: int) -> dict[str, Any]:
    """KWP2000 0x21 (ReadDataByLocalId) 응답 디코딩
    
    응답 형식: 61 PID [data bytes]
    """
    if len(data) < 2 or data[0] != 0x61:
        return {}
    
    response_pid = data[1]
    if response_pid != pid:
        return {}
    
    payload = data[2:]
    values = {}
    
    # Hyundai/Kia BMS PIDs (2101-210E)
    if pid == 0x01:  # 2101: SOC/SOH
        if len(payload) >= 2:
            values['bms_soc_pct'] = round(payload[0] / 2.0, 1)
            values['bms_soh_pct'] = round(payload[1] / 2.0, 1)
    
    elif pid == 0x02:  # 2102: 전압/전류
        if len(payload) >= 4:
            values['bms_voltage_v'] = round(((payload[0] << 8) | payload[1]) / 10.0, 1)
            values['bms_current_a'] = round((((payload[2] << 8) | payload[3]) - 32768) / 10.0, 1)
    
    elif pid == 0x03:  # 2103: 셀 전압 (최대/최소)
        if len(payload) >= 4:
            values['cell_voltage_max_mv'] = (payload[0] << 8) | payload[1]
            values['cell_voltage_min_mv'] = (payload[2] << 8) | payload[3]
    
    elif pid == 0x04:  # 2104: 배터리 온도
        if len(payload) >= 3:
            values['bms_temp_inlet_c'] = payload[0] - 40
            values['bms_temp_max_c'] = payload[1] - 40
            values['bms_temp_min_c'] = payload[2] - 40
    
    elif pid == 0x05:  # 2105: 모듈 전압들
        module_voltages = []
        for i in range(0, len(payload), 2):
            if i + 1 < len(payload):
                voltage = ((payload[i] << 8) | payload[i+1]) / 50.0
                module_voltages.append(round(voltage, 2))
        if module_voltages:
            values['module_voltages_v'] = module_voltages
    
    return values


def apply_formula(value: Any, formula: str, safe_eval: callable) -> Any:
    """진단 명령의 formula를 적용하여 값 변환
    
    formula 예시: "x/2", "(x-32768)/10", "x*0.01"
    """
    if not formula or not isinstance(value, (int, float)):
        return value
    
    try:
        # 안전한 수식 평가
        result = safe_eval(formula, {'x': value})
        return round(result, 3) if isinstance(result, float) else result
    except Exception:
        return value


def extract_bits(data: bytes, bit_position: int, bit_length: int) -> int:
    """비트 위치와 길이로 데이터 추출
    
    Args:
        data: 바이트 배열
        bit_position: 시작 비트 (0부터, LSB first)
        bit_length: 추출할 비트 수
    
    Returns:
        추출된 정수 값
    """
    byte_pos = bit_position // 8
    bit_offset = bit_position % 8
    
    if byte_pos >= len(data):
        return 0
    
    # 필요한 바이트들을 모아서 정수로 변환
    value = 0
    bits_read = 0
    current_byte = byte_pos
    
    while bits_read < bit_length and current_byte < len(data):
        byte_val = data[current_byte]
        available_bits = 8 - (bit_offset if current_byte == byte_pos else 0)
        bits_to_read = min(bit_length - bits_read, available_bits)
        
        shift = bit_offset if current_byte == byte_pos else 0
        mask = ((1 << bits_to_read) - 1) << shift
        extracted = (byte_val & mask) >> shift
        
        value |= extracted << bits_read
        bits_read += bits_to_read
        current_byte += 1
    
    return value


def decode_dbc_frame(can_id: int, data: bytes, dbc_db: cantools.database.Database) -> dict[str, Any]:
    """DBC를 사용하여 CAN 프레임 디코딩
    
    Args:
        can_id: CAN ID (정수)
        data: 프레임 데이터 (8바이트)
        dbc_db: cantools Database 객체
    
    Returns:
        {signal_name: decoded_value}
    """
    try:
        message = dbc_db.get_message_by_frame_id(can_id)
        decoded = message.decode(data)
        return decoded
    except (KeyError, ValueError):
        return {}
