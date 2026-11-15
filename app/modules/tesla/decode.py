"""Tesla CAN signal decoding.

Sources:
- joshwardell/model3dbc Model3CAN.dbc (commit c56c113): https://github.com/joshwardell/model3dbc (MIT License)
- commaai/opendbc tesla_*.dbc (commit 27fa1c5): https://github.com/commaai/opendbc/tree/master/opendbc/dbc (MIT License)
- dalathegreat/Battery-Emulator TESLA-BATTERY.cpp (commit 0808398): https://github.com/dalathegreat/Battery-Emulator (GPL-3.0)
"""

import struct
from typing import Dict, Any, List, Tuple
from collections import defaultdict
import statistics


def decode_0x352_energy(frames: List[Tuple[float, bytes]]) -> Dict[str, Any]:
    """
    0x352 BMS 에너지 상태 디코딩 (신형 펌웨어 다중화 형식).
    
    Multiplex 0: NominalFullPackEnergy, NominalEnergyRemaining, IdealEnergyRemaining
    Multiplex 1: FullChargeComplete, EnergyBuffer, ExpectedEnergyRemaining, EnergyToChargeComplete
    
    Source: dalathegreat/Battery-Emulator TESLA-BATTERY.cpp
    """
    mux0_frames = []
    mux1_frames = []
    
    for ts, data in frames:
        if len(data) < 8:
            continue
        
        mux = data[0] & 0x03
        
        if mux == 0:
            # NominalFullPackEnergy: bytes[3:2] * 0.02 kWh
            # NominalEnergyRemaining: bytes[5:4] * 0.02 kWh
            # IdealEnergyRemaining: bytes[7:6] * 0.02 kWh
            full = struct.unpack('<H', data[2:4])[0] * 0.02
            nom_rem = struct.unpack('<H', data[4:6])[0] * 0.02
            ideal_rem = struct.unpack('<H', data[6:8])[0] * 0.02
            mux0_frames.append((ts, full, nom_rem, ideal_rem))
        
        elif mux == 1:
            # FullChargeComplete: bit 0 of byte[1]
            # EnergyBuffer: bytes[3:2] * 0.01 kWh
            # ExpectedEnergyRemaining: bytes[5:4] * 0.02 kWh
            # EnergyToChargeComplete: bytes[7:6] * 0.02 kWh
            full_chg = (data[1] & 0x01) == 1
            buffer = struct.unpack('<H', data[2:4])[0] * 0.01
            exp_rem = struct.unpack('<H', data[4:6])[0] * 0.02
            to_chg = struct.unpack('<H', data[6:8])[0] * 0.02
            mux1_frames.append((ts, full_chg, buffer, exp_rem, to_chg))
    
    result = {}
    
    if mux0_frames:
        # 중앙값 사용
        full_vals = [f[1] for f in mux0_frames]
        nom_rem_vals = [f[2] for f in mux0_frames]
        result['nominal_full_pack_energy'] = statistics.median(full_vals)
        result['nominal_energy_remaining'] = statistics.median(nom_rem_vals)
        result['ideal_energy_remaining'] = statistics.median([f[3] for f in mux0_frames])
    
    if mux1_frames:
        result['energy_buffer'] = statistics.median([f[2] for f in mux1_frames])
        result['expected_energy_remaining'] = statistics.median([f[3] for f in mux1_frames])
        result['energy_to_charge_complete'] = statistics.median([f[4] for f in mux1_frames])
    
    return result


def decode_0x292_soc(frames: List[Tuple[float, bytes]]) -> Dict[str, Any]:
    """
    0x292 BMS SOC 디코딩.
    
    Min: bits[9:0] * 0.1 %
    UI: bits[19:10] * 0.1 %
    Max: bits[29:20] * 0.1 %
    Ave: bits[39:30] * 0.1 %
    BOL: bits[49:40] * 0.1 kWh
    """
    soc_vals = []
    
    for ts, data in frames:
        if len(data) < 8:
            continue
        
        # 8바이트를 64bit little-endian으로
        val = struct.unpack('<Q', data)[0]
        
        soc_min = ((val >> 0) & 0x3FF) * 0.1
        soc_ui = ((val >> 10) & 0x3FF) * 0.1
        soc_max = ((val >> 20) & 0x3FF) * 0.1
        soc_ave = ((val >> 30) & 0x3FF) * 0.1
        bol = ((val >> 40) & 0x3FF) * 0.1
        
        soc_vals.append({
            'min': soc_min,
            'ui': soc_ui,
            'max': soc_max,
            'ave': soc_ave,
            'bol': bol,
        })
    
    if not soc_vals:
        return {}
    
    return {
        'soc_min': statistics.median([s['min'] for s in soc_vals]),
        'soc_ui': statistics.median([s['ui'] for s in soc_vals]),
        'soc_max': statistics.median([s['max'] for s in soc_vals]),
        'soc_ave': statistics.median([s['ave'] for s in soc_vals]),
        'bol_energy': statistics.median([s['bol'] for s in soc_vals]),
    }


def decode_0x401_brick_voltages(frames: List[Tuple[float, bytes]]) -> Dict[str, Any]:
    """
    0x401 브릭(셀 그룹) 전압 디코딩.
    
    96개 브릭: mux 0~31, 각 3개씩
    
    Source: dalathegreat/Battery-Emulator TESLA-BATTERY.cpp
    """
    cells = defaultdict(list)
    
    for ts, data in frames:
        if len(data) < 8:
            continue
        
        mux = data[0]
        flag = data[1]
        
        # mux >= 64는 스킵
        if mux >= 64:
            continue
        
        # 0x2A 플래그: 3개 브릭
        if flag == 0x2A:
            for k in range(3):
                brick_num = mux * 3 + k
                voltage = struct.unpack('<H', data[2 + 2*k:4 + 2*k])[0] * 0.0001
                if 1.5 < voltage < 4.6:  # 유효 범위
                    cells[brick_num].append(voltage)
        
        # 0x02 플래그: 1개 브릭
        elif flag == 0x02:
            voltage = struct.unpack('<H', data[2:4])[0] * 0.0001
            if 1.5 < voltage < 4.6:
                cells[mux * 3].append(voltage)
    
    if not cells:
        return {}
    
    # 각 브릭의 중앙값
    brick_medians = {num: statistics.median(voltages) for num, voltages in cells.items()}
    
    if not brick_medians:
        return {}
    
    min_brick = min(brick_medians, key=brick_medians.get)
    max_brick = max(brick_medians, key=brick_medians.get)
    
    return {
        'brick_count': len(brick_medians),
        'brick_voltages': brick_medians,
        'min_voltage': brick_medians[min_brick],
        'min_brick_num': min_brick + 1,  # 1-based
        'max_voltage': brick_medians[max_brick],
        'max_brick_num': max_brick + 1,
        'voltage_spread': brick_medians[max_brick] - brick_medians[min_brick],
        'total_voltage': sum(brick_medians.values()),
        'average_voltage': statistics.mean(brick_medians.values()),
    }


def decode_0x332_summary(frames: List[Tuple[float, bytes]]) -> Dict[str, Any]:
    """
    0x332 BMS 셀 온도/전압 요약 디코딩.
    
    Mux 0: 온도 (최고/최저/평균, 센서 번호)
    Mux 1: 전압 (최고/최저, 브릭 번호)
    
    Source: dalathegreat/Battery-Emulator TESLA-BATTERY.cpp (newer firmware layout)
    """
    temps = []
    volts = []
    
    for ts, data in frames:
        if len(data) < 8:
            continue
        
        mux = data[0] & 0x03
        
        if mux == 0:
            # 신형 펌웨어: byte[3] <= byte[4] <= byte[2]
            t_max = data[2] * 0.5 - 40
            t_min = data[3] * 0.5 - 40
            t_avg = data[4] * 0.5 - 40
            
            newer = data[3] <= data[4] <= data[2]
            if newer:
                t_max_num = (data[1] & 0x0F)
                t_min_num = ((data[0] >> 2) & 0x0F)
            else:
                t_max_num = ((data[0] >> 2) & 0x0F)
                t_min_num = (data[1] & 0x0F)
            
            temps.append({
                'max': t_max,
                'min': t_min,
                'avg': t_avg,
                'max_num': t_max_num,
                'min_num': t_min_num,
            })
        
        elif mux == 1:
            # Voltage: bits
            v_max = (((data[1] & 0x3F) << 6) | ((data[0] >> 2) & 0x3F)) * 0.002
            v_min = (((data[3] & 0x0F) << 8) | data[2]) * 0.002
            v_max_num = 1 + (data[4] & 0x7F)
            v_min_num = 1 + (data[5] & 0x7F)
            
            volts.append({
                'max': v_max,
                'min': v_min,
                'max_num': v_max_num,
                'min_num': v_min_num,
            })
    
    result = {}
    
    if temps:
        result['temp_max'] = statistics.median([t['max'] for t in temps])
        result['temp_min'] = statistics.median([t['min'] for t in temps])
        result['temp_avg'] = statistics.median([t['avg'] for t in temps])
        result['temp_spread'] = result['temp_max'] - result['temp_min']
        # 센서 번호는 최빈값
        result['temp_max_sensor'] = max(set([t['max_num'] for t in temps]), key=[t['max_num'] for t in temps].count)
        result['temp_min_sensor'] = max(set([t['min_num'] for t in temps]), key=[t['min_num'] for t in temps].count)
    
    if volts:
        result['voltage_max'] = statistics.median([v['max'] for v in volts])
        result['voltage_min'] = statistics.median([v['min'] for v in volts])
        result['voltage_spread'] = result['voltage_max'] - result['voltage_min']
        result['voltage_max_brick'] = max(set([v['max_num'] for v in volts]), key=[v['max_num'] for v in volts].count)
        result['voltage_min_brick'] = max(set([v['min_num'] for v in volts]), key=[v['min_num'] for v in volts].count)
    
    return result


def decode_0x132_pack_vi(frames: List[Tuple[float, bytes]]) -> Dict[str, Any]:
    """
    0x132 HV 배터리 전압/전류 디코딩.
    
    Voltage: bytes[1:0] * 0.01 V
    Current: bytes[3:2] (signed) * -0.1 A
    """
    voltages = []
    currents = []
    
    for ts, data in frames:
        if len(data) < 8:
            continue
        
        voltage = struct.unpack('<H', data[0:2])[0] * 0.01
        current = struct.unpack('<h', data[2:4])[0] * -0.1
        
        voltages.append(voltage)
        currents.append(current)
    
    if not voltages:
        return {}
    
    return {
        'pack_voltage': statistics.median(voltages),
        'pack_voltage_min': min(voltages),
        'pack_voltage_max': max(voltages),
        'pack_current': statistics.median(currents),
    }


def decode_0x2B4_lv_dcdc(frames: List[Tuple[float, bytes]]) -> Dict[str, Any]:
    """
    0x2B4 PCS DC-DC 레일 상태 디코딩.
    
    LV: bytes[1:0] & 0x1FFF * 0.01 V
    HV: bytes[3:2] & 0x3FFF * 0.1 V
    LV Current: bytes[5:4] & 0x1FFF (signed) * 0.1 A
    """
    lv_vals = []
    hv_vals = []
    lv_i_vals = []
    
    for ts, data in frames:
        if len(data) < 8:
            continue
        
        lv = (struct.unpack('<H', data[0:2])[0] & 0x1FFF) * 0.01
        hv = (struct.unpack('<H', data[2:4])[0] & 0x3FFF) * 0.1
        
        lv_i_raw = (struct.unpack('<H', data[4:6])[0] & 0x1FFF)
        if lv_i_raw & 0x1000:
            lv_i_raw -= 0x2000
        lv_i = lv_i_raw * 0.1
        
        lv_vals.append(lv)
        hv_vals.append(hv)
        lv_i_vals.append(lv_i)
    
    if not lv_vals:
        return {}
    
    return {
        'lv_voltage': statistics.median(lv_vals),
        'lv_voltage_min': min(lv_vals),
        'lv_voltage_max': max(lv_vals),
        'hv_voltage': statistics.median(hv_vals),
        'lv_current': statistics.median(lv_i_vals),
    }


def decode_0x3D2_cumulative_energy(frames: List[Tuple[float, bytes]]) -> Dict[str, Any]:
    """
    0x3D2 누적 충/방전 에너지 디코딩.
    
    Discharge: bytes[3:0] * 0.001 kWh
    Charge: bytes[7:4] * 0.001 kWh
    """
    if not frames:
        return {}
    
    # 첫/마지막 프레임
    first_data = frames[0][1] if len(frames[0]) > 1 else None
    last_data = frames[-1][1] if len(frames) > 0 and len(frames[-1]) > 1 else None
    
    result = {}
    
    if last_data and len(last_data) >= 8:
        discharge = struct.unpack('<I', last_data[0:4])[0] * 0.001
        charge = struct.unpack('<I', last_data[4:8])[0] * 0.001
        result['cumulative_discharge'] = discharge
        result['cumulative_charge'] = charge
    
    if first_data and last_data and len(first_data) >= 8 and len(last_data) >= 8:
        dis_start = struct.unpack('<I', first_data[0:4])[0] * 0.001
        dis_end = struct.unpack('<I', last_data[0:4])[0] * 0.001
        result['session_discharge'] = dis_end - dis_start
    
    return result
