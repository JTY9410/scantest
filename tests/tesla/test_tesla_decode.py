"""Tesla CAN signal decoding tests."""

import pytest
import struct
from app.modules.tesla.decode import (
    decode_0x352_energy,
    decode_0x292_soc,
    decode_0x401_brick_voltages,
    decode_0x332_summary,
    decode_0x132_pack_vi,
    decode_0x2B4_lv_dcdc,
)


def test_decode_0x352_energy():
    """0x352 에너지 디코딩."""
    # Mux 0: NominalFullPackEnergy 65.26 kWh (3263 * 0.02)
    data_mux0 = bytes([0x00, 0x00]) + struct.pack('<H', 3263) + struct.pack('<HH', 1654, 1646)
    
    # Mux 1: EnergyBuffer 2.93 kWh (293 * 0.01)
    data_mux1 = bytes([0x01, 0x01]) + struct.pack('<H', 293) + struct.pack('<HH', 1500, 985)
    
    frames = [
        (1.0, data_mux0),
        (1.1, data_mux1),
        (1.2, data_mux0),
    ]
    
    result = decode_0x352_energy(frames)
    
    assert 'nominal_full_pack_energy' in result
    assert abs(result['nominal_full_pack_energy'] - 65.26) < 0.01
    assert 'energy_buffer' in result
    assert abs(result['energy_buffer'] - 2.93) < 0.01


def test_decode_0x292_soc():
    """0x292 SOC 디코딩."""
    # SOC: min 54.5%, ui 50.8%, max 55.3%, ave 55.0%
    # 10bit 값: 545, 508, 553, 550
    soc_min = 545  # 54.5%
    soc_ui = 508   # 50.8%
    soc_max = 553  # 55.3%
    soc_ave = 550  # 55.0%
    bol = 1  # 0.1 kWh (비정상)
    
    val = (soc_min & 0x3FF) | ((soc_ui & 0x3FF) << 10) | ((soc_max & 0x3FF) << 20) | ((soc_ave & 0x3FF) << 30) | ((bol & 0x3FF) << 40)
    data = struct.pack('<Q', val)
    
    frames = [(1.0, data)]
    result = decode_0x292_soc(frames)
    
    assert abs(result['soc_min'] - 54.5) < 0.1
    assert abs(result['soc_ui'] - 50.8) < 0.1
    assert abs(result['soc_max'] - 55.3) < 0.1
    assert abs(result['soc_ave'] - 55.0) < 0.1


def test_decode_0x401_brick_voltages():
    """0x401 브릭 전압 디코딩."""
    frames = []
    
    # Mux 0: 브릭 0, 1, 2 (3.8244 V, 3.8260 V, 3.8280 V)
    # 전압 * 10000 = raw value
    data = bytes([0x00, 0x2A]) + struct.pack('<HHH', 38244, 38260, 38280)
    frames.append((1.0, data))
    
    # Mux 1: 브릭 3, 4, 5
    data = bytes([0x01, 0x2A]) + struct.pack('<HHH', 38290, 38300, 38304)
    frames.append((1.1, data))
    
    result = decode_0x401_brick_voltages(frames)
    
    assert result['brick_count'] == 6
    assert abs(result['min_voltage'] - 3.8244) < 0.0001
    assert abs(result['max_voltage'] - 3.8304) < 0.0001
    assert result['min_brick_num'] == 1  # 1-based
    assert result['max_brick_num'] == 6
    assert abs(result['voltage_spread'] - 0.0060) < 0.0001


def test_decode_0x332_summary():
    """0x332 요약 디코딩."""
    # Mux 0: 온도 (최고 24.5°C, 최저 23.5°C, 평균 24.0°C)
    # byte[2] = (24.5 + 40) / 0.5 = 129
    # byte[3] = (23.5 + 40) / 0.5 = 127
    # byte[4] = (24.0 + 40) / 0.5 = 128
    data_temp = bytes([0x00, 0x07, 129, 127, 128, 0, 0, 0])
    
    # Mux 1: 전압 (최고 3.830 V, 최저 3.824 V)
    # v_max = 3.830 / 0.002 = 1915 → bits
    # v_min = 3.824 / 0.002 = 1912
    data_volt = bytes([0x01, 0x00, 0, 0, 0, 0, 0, 0])  # 간략화
    
    frames = [(1.0, data_temp), (1.1, data_volt)]
    result = decode_0x332_summary(frames)
    
    assert 'temp_max' in result
    assert abs(result['temp_max'] - 24.5) < 0.1
    assert abs(result['temp_min'] - 23.5) < 0.1
    assert abs(result['temp_avg'] - 24.0) < 0.1
    assert abs(result['temp_spread'] - 1.0) < 0.1


def test_decode_0x132_pack_vi():
    """0x132 팩 전압/전류 디코딩."""
    # 전압 367.50 V = 36750 * 0.01
    # 전류 0.8 A (방전) = -8 * -0.1
    data = struct.pack('<HhHH', 36750, -8, 0, 0)
    
    frames = [(1.0, data), (1.1, data)]
    result = decode_0x132_pack_vi(frames)
    
    assert abs(result['pack_voltage'] - 367.50) < 0.01
    assert abs(result['pack_current'] - 0.8) < 0.1


def test_decode_0x2B4_lv_dcdc():
    """0x2B4 12V/DC-DC 디코딩."""
    # LV 12.56 V = 1256 * 0.01
    # HV 367.5 V = 3675 * 0.1
    # LV Current 18 A = 180 * 0.1
    data = struct.pack('<HHHH', 1256, 3675, 180, 0)
    
    frames = [(1.0, data)]
    result = decode_0x2B4_lv_dcdc(frames)
    
    assert abs(result['lv_voltage'] - 12.56) < 0.01
    assert abs(result['hv_voltage'] - 367.5) < 0.1
    assert abs(result['lv_current'] - 18.0) < 0.1
