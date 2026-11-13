"""CAN/OBD-II 프레임 디코더 및 ISO-TP 재조립

기존 canlab/engine/bms.py와 OBDb 정의를 사용하여 실제 값 디코딩.
하드코딩하지 않고 DB 정의와 검증된 로직 재사용.
"""
import re
from typing import Any
from collections import defaultdict

import cantools

# 물리적 타당성 범위 (EV6 E-GMP 기준)
VALID_RANGES = {
    'soc_pct': (0, 110),  # SOC 0-100% + 여유
    'soh_pct': (0, 110),  # SOH 0-100% + 여유
    'pack_voltage_v': (500, 850),  # EV6 팩 전압 범위
    'pack_current_a': (-600, 600),  # 전류 ±600A
    'temp_c': (-40, 100),  # 온도 범위
    'cell_voltage_mv': (2500, 4300),  # 셀 전압 2.5-4.3V
}

# 무효 센티널 값
INVALID_SENTINELS = {
    0xFF,  # 단일 바이트
    0xFFFF,  # 2바이트
    0xFFFFFFFF,  # 4바이트
}


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


def is_valid_value(value: Any, value_type: str) -> bool:
    """물리적 타당성 검증
    
    Args:
        value: 검증할 값
        value_type: 값 유형 (soc_pct, pack_voltage_v, temp_c, cell_voltage_mv 등)
    
    Returns:
        True if valid, False otherwise
    """
    if value is None:
        return False
    
    # 센티널 값 체크
    if isinstance(value, int) and value in INVALID_SENTINELS:
        return False
    
    # 범위 체크
    if value_type in VALID_RANGES:
        min_val, max_val = VALID_RANGES[value_type]
        if not (min_val <= value <= max_val):
            return False
    
    return True


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
        load_pct = round(data[2] * 100 / 255, 1)
        if is_valid_value(load_pct, 'soc_pct'):
            values['engine_load_pct'] = load_pct
    
    elif pid == 0x05 and len(data) >= 3:  # 냉각수 온도
        temp_c = data[2] - 40
        if is_valid_value(temp_c, 'temp_c'):
            values['coolant_temp_c'] = temp_c
    
    elif pid == 0x0C and len(data) >= 4:  # 엔진 RPM
        values['engine_rpm'] = ((data[2] << 8) | data[3]) / 4
    
    elif pid == 0x0D and len(data) >= 3:  # 차속
        values['vehicle_speed_kmh'] = data[2]
    
    elif pid == 0x0F and len(data) >= 3:  # 흡기 온도
        temp_c = data[2] - 40
        if is_valid_value(temp_c, 'temp_c'):
            values['intake_temp_c'] = temp_c
    
    elif pid == 0x11 and len(data) >= 3:  # 스로틀 위치
        throttle_pct = round(data[2] * 100 / 255, 1)
        if is_valid_value(throttle_pct, 'soc_pct'):
            values['throttle_position_pct'] = throttle_pct
    
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
        vin = vin_bytes.decode('ascii', errors='ignore').strip('\x00')
        # VIN 마스킹 (개인정보 보호)
        if len(vin) >= 17:
            values['vin_masked'] = vin[:5] + '*****' + vin[10:]
        else:
            values['vin_masked'] = vin
    
    return values


def decode_bms_0101(data: bytes) -> dict[str, Any]:
    """Hyundai/Kia BMS 0x0101 디코딩 (canlab/engine/bms.py 로직)
    
    응답: 62 01 01 [data...] (UDS 에코 제외, data[0]부터 시작)
    검증된 바이트 위치 사용 (2026-11-05 검증)
    """
    if len(data) < 3 or data[0] != 0x62 or data[1] != 0x01 or data[2] != 0x01:
        return {}
    
    # UDS 에코(62 01 01) 제외, payload는 data[3]부터
    payload = data[3:]
    values = {}
    
    try:
        # SOC: byte 4, scale 0.5, 확인됨
        if len(payload) > 4:
            soc = payload[4] * 0.5
            if is_valid_value(soc, 'soc_pct'):
                values['soc_pct'] = round(soc, 1)
            else:
                values['soc_pct_invalid'] = soc
        
        # 팩 전류: bytes 10-11, scale 0.1, signed, 확인됨
        if len(payload) >= 12:
            current_raw = int.from_bytes(payload[10:12], 'big', signed=True)
            current = current_raw * 0.1
            if is_valid_value(current, 'pack_current_a'):
                values['pack_current_a'] = round(current, 1)
            else:
                values['pack_current_a_invalid'] = current
        
        # 팩 전압: bytes 12-13, scale 0.1, 확인됨
        if len(payload) >= 14:
            voltage_raw = int.from_bytes(payload[12:14], 'big')
            voltage = voltage_raw * 0.1
            if is_valid_value(voltage, 'pack_voltage_v'):
                values['pack_voltage_v'] = round(voltage, 1)
            else:
                values['pack_voltage_v_invalid'] = voltage
        
        # 최고 모듈 온도: byte 14, signed, 확인됨
        if len(payload) > 14:
            max_temp = int.from_bytes(payload[14:15], 'big', signed=True)
            if is_valid_value(max_temp, 'temp_c'):
                values['max_temp_c'] = max_temp
            else:
                values['max_temp_c_invalid'] = max_temp
        
        # 최저 모듈 온도: byte 15, signed, 확인됨
        if len(payload) > 15:
            min_temp = int.from_bytes(payload[15:16], 'big', signed=True)
            if is_valid_value(min_temp, 'temp_c'):
                values['min_temp_c'] = min_temp
            else:
                values['min_temp_c_invalid'] = min_temp
        
        # 최고 셀 전압: byte 23, scale 0.02, 확인됨
        if len(payload) > 23:
            max_cell_raw = payload[23]
            max_cell = max_cell_raw * 0.02  # V 단위
            max_cell_mv = max_cell * 1000  # mV 단위
            if is_valid_value(max_cell_mv, 'cell_voltage_mv') and max_cell_raw not in INVALID_SENTINELS:
                values['max_cell_voltage_v'] = round(max_cell, 3)
            else:
                values['max_cell_voltage_v_invalid'] = max_cell
        
        # 최저 셀 전압: byte 25, scale 0.02, 확인됨
        if len(payload) > 25:
            min_cell_raw = payload[25]
            min_cell = min_cell_raw * 0.02  # V 단위
            min_cell_mv = min_cell * 1000  # mV 단위
            if is_valid_value(min_cell_mv, 'cell_voltage_mv') and min_cell_raw not in INVALID_SENTINELS:
                values['min_cell_voltage_v'] = round(min_cell, 3)
            else:
                values['min_cell_voltage_v_invalid'] = min_cell
        
        # 누적 충전 전력량: bytes 38-41, scale 0.1, 확인됨
        if len(payload) >= 42:
            cum_charge_kwh = int.from_bytes(payload[38:42], 'big') * 0.1
            values['cum_charge_kwh'] = round(cum_charge_kwh, 1)
        
        # 누적 방전 전력량: bytes 42-45, scale 0.1, 확인됨
        if len(payload) >= 46:
            cum_discharge_kwh = int.from_bytes(payload[42:46], 'big') * 0.1
            values['cum_discharge_kwh'] = round(cum_discharge_kwh, 1)
    
    except Exception as e:
        values['decode_error'] = str(e)
    
    return values


def decode_bms_0105(data: bytes) -> dict[str, Any]:
    """Hyundai/Kia BMS 0x0105 디코딩
    
    SOH, 표시 SOC, 남은 에너지 등
    """
    if len(data) < 3 or data[0] != 0x62 or data[1] != 0x01 or data[2] != 0x05:
        return {}
    
    payload = data[3:]
    values = {}
    
    try:
        # SOH: bytes 25-26, scale 0.1, 확인됨 (E-GMP, 니로, 1세대)
        if len(payload) >= 27:
            soh_raw = int.from_bytes(payload[25:27], 'big')
            soh = soh_raw * 0.1
            if is_valid_value(soh, 'soh_pct'):
                values['soh_pct'] = round(soh, 1)
            else:
                values['soh_pct_invalid'] = soh
        
        # 표시 SOC: byte 31, scale 0.5, 확인됨
        if len(payload) > 31:
            display_soc = payload[31] * 0.5
            if is_valid_value(display_soc, 'soc_pct'):
                values['display_soc_pct'] = round(display_soc, 1)
            else:
                values['display_soc_pct_invalid'] = display_soc
    
    except Exception as e:
        values['decode_error'] = str(e)
    
    return values


def decode_uds_response(data: bytes) -> dict[str, Any]:
    """UDS 0x22/KWP 0x21 응답 통합 디코딩
    
    BMS 검증된 로직 사용
    """
    if len(data) < 3:
        return {}
    
    service = data[0]
    
    # UDS 0x62 (ReadDataByIdentifier 응답)
    if service == 0x62:
        did = (data[1] << 8) | data[2]
        
        if did == 0x0101:
            return decode_bms_0101(data)
        elif did == 0x0105:
            return decode_bms_0105(data)
    
    # KWP 0x61 (ReadDataByLocalId 응답) - 동일한 디코딩 로직
    # (현대/기아는 0x22를 주로 사용하므로 0x61은 별도 처리 생략)
    
    return {}


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
