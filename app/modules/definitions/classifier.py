"""정의 데이터 자동 분류 서비스.

ECU 주소, 메시지 이름, 단위, 라벨 등 실제 신호 특성으로 분류를 개선한다.
"""
from sqlalchemy import text

from app.extensions import db


# ECU 주소 매핑 (표준 및 제조사별)
# 출처: ISO 15765-4 (CAN), ISO 14230 (KWP2000), OBDb 데이터 분석
ECU_ADDRESS_MAP = {
    # Standard OBD-II / ISO addresses
    '7E0': 'ECM', '7E8': 'ECM',  # Engine
    '7E1': 'TCM', '7E9': 'TCM',  # Transmission
    '7DF': 'BROADCAST',           # Broadcast request
    
    # Hyundai/Kia EV-specific (EGMP platform analysis)
    '7E4': 'BMS', '7EC': 'BMS',  # Battery Management System (response)
    '7E2': 'MCU', '7EA': 'MCU',  # Motor Control Unit / VCU
    '7E5': 'OBC', '7ED': 'OBC',  # On-Board Charger
    '7C6': 'CLUSTER', '7CE': 'CLUSTER',  # Instrument Cluster
    '7A0': 'BCM', '7A8': 'BCM',  # Body Control Module
    '7D1': 'ABS', '7D9': 'ABS',  # ABS/ESC
    
    # Extended addressing (common patterns)
    '760': 'CLUSTER', '770': 'CLUSTER',
    '761': 'CLUSTER', '771': 'CLUSTER',
}

# 알려진 전기차 모델 (제조사 공식 라인업, 단어 경계 사용)
KNOWN_BEV_MODELS = [
    # Hyundai
    'IONIQ 5', 'IONIQ 6', 'IONIQ 7', 'KONA ELECTRIC', 'KONA EV',
    # Kia
    'EV3', 'EV4', 'EV5', 'EV6', 'EV9', 'NIRO EV', 'SOUL EV', 'RAY EV',
    # Genesis
    'GV60', 'GV70 ELECTRIC', 'G80 ELECTRIFIED', 'GV80 ELECTRIFIED',
    # Tesla
    'MODEL S', 'MODEL 3', 'MODEL X', 'MODEL Y', 'CYBERTRUCK', 'ROADSTER',
    # Nissan
    'LEAF', 'ARIYA',
    # GM
    'BOLT EV', 'BOLT EUV', 'HUMMER EV', 'LYRIQ', 'EQUINOX EV', 'BLAZER EV',
    # Ford
    'MUSTANG MACH-E', 'F-150 LIGHTNING', 'E-TRANSIT',
    # VW Group
    'ID.3', 'ID.4', 'ID.5', 'ID.7', 'ID. BUZZ',
    'E-TRON', 'E-TRON GT', 'Q4 E-TRON', 'Q8 E-TRON',
    'TAYCAN', 'MACAN ELECTRIC',
    # Others
    'I-PACE', 'EQS', 'EQE', 'ATTO 3', 'SEAL', 'DOLPHIN',
]

KNOWN_PHEV_KEYWORDS = [
    'PLUG-IN', 'PLUG IN', 'PHEV', 'RECHARGEABLE',
]

KNOWN_HEV_KEYWORDS = [
    'HYBRID', 'HEV', 'SELF-CHARGING',
]

# 알려진 ICE 전용 모델 패턴 (엔진만)
KNOWN_ICE_INDICATORS = [
    'DIESEL', 'TURBO', 'GDI', 'CRDI', 'TCI',
]


def classify_powertrain_from_model(model: str) -> str:
    """차량 모델명으로 파워트레인 추론."""
    if not model:
        return 'unknown'
    
    model_upper = model.upper()
    
    # BEV: 알려진 전기차 모델 (단어 경계)
    for ev_model in KNOWN_BEV_MODELS:
        if f' {ev_model.upper()} ' in f' {model_upper} ' or model_upper.startswith(ev_model.upper() + ' ') or model_upper.endswith(' ' + ev_model.upper()):
            return 'BEV'
    
    # PHEV: 플러그인 하이브리드 키워드
    for phev_kw in KNOWN_PHEV_KEYWORDS:
        if phev_kw.upper() in model_upper:
            return 'PHEV'
    
    # HEV: 하이브리드 (PHEV 제외)
    for hev_kw in KNOWN_HEV_KEYWORDS:
        if hev_kw.upper() in model_upper:
            return 'HEV'
    
    # ICE 지표
    for ice_kw in KNOWN_ICE_INDICATORS:
        if ice_kw in model_upper:
            return 'ICE'
    
    return 'unknown'


def classify_powertrain_from_commands(vehicle_id: int) -> str:
    """해당 차량의 진단 명령 증거로 파워트레인 추론."""
    result = db.session.execute(text("""
        SELECT 
            COUNT(*) FILTER (WHERE ecu_module = 'BMS') as bms_count,
            COUNT(*) FILTER (WHERE protocol = 'OBD-II' AND service = '01') as obd_fuel_count,
            COUNT(*) as total_count
        FROM diagnostic_commands
        WHERE source_id = :vehicle_id AND source_type = 'vehicle'
    """), {"vehicle_id": vehicle_id}).fetchone()
    
    if not result or result.total_count == 0:
        return 'unknown'
    
    # BMS 명령이 많으면 전기차
    if result.bms_count > 3:
        return 'BEV'
    
    # OBD-II Mode 01 연료 시스템 명령만 있으면 ICE
    if result.obd_fuel_count > 10 and result.bms_count == 0:
        return 'ICE'
    
    return 'unknown'


def map_ecu_from_address(address: str, ecu_name: str = None) -> str:
    """ECU 주소 및 이름으로 ECU 모듈 매핑."""
    if not address:
        return None
    
    # 주소 정규화 (0x 제거, 대문자)
    addr_clean = address.upper().replace('0X', '').strip()
    
    # 표준 매핑 테이블 조회
    if addr_clean in ECU_ADDRESS_MAP:
        return ECU_ADDRESS_MAP[addr_clean]
    
    # ECU 이름 패턴 (OBDb/WiCAN 메타데이터)
    if ecu_name:
        ecu_upper = ecu_name.upper()
        if 'BMS' in ecu_upper or 'BATTERY' in ecu_upper:
            return 'BMS'
        if 'MCU' in ecu_upper or 'MOTOR' in ecu_upper or 'INVERTER' in ecu_upper:
            return 'MCU'
        if 'OBC' in ecu_upper or 'CHARGER' in ecu_upper:
            return 'OBC'
        if 'VCU' in ecu_upper or 'VEHICLE CONTROL' in ecu_upper:
            return 'VCU'
        if 'ECM' in ecu_upper or 'ENGINE' in ecu_upper:
            return 'ECM'
        if 'TCM' in ecu_upper or 'TRANSMISSION' in ecu_upper:
            return 'TCM'
        if 'CLUSTER' in ecu_upper or 'DASHBOARD' in ecu_upper:
            return 'CLUSTER'
        if 'BCM' in ecu_upper or 'BODY' in ecu_upper:
            return 'BCM'
        if 'ABS' in ecu_upper or 'BRAKE' in ecu_upper or 'ESC' in ecu_upper:
            return 'ABS'
    
    return 'UNKNOWN'


def classify_signal_category(signal_name: str, unit: str = None, label: str = None) -> str:
    """신호 이름, 단위, 라벨로 카테고리 분류 (한국어 포함)."""
    name_upper = (signal_name or '').upper()
    unit_upper = (unit or '').upper()
    label_upper = (label or '').upper()
    
    # 배터리 SOC
    if any(kw in name_upper or kw in label_upper for kw in ['SOC', 'STATE OF CHARGE', 'STATE_OF_CHARGE', '충전상태', '충전량']):
        if unit_upper in ['%', 'PERCENT']:
            return 'battery_soc'
    
    # 배터리 SOH
    if any(kw in name_upper or kw in label_upper for kw in ['SOH', 'STATE OF HEALTH', 'STATE_OF_HEALTH', '배터리수명', '건강상태']):
        return 'battery_soh'
    
    # 셀 전압
    if 'CELL' in name_upper and any(kw in name_upper or kw in unit_upper for kw in ['VOLT', 'V', '전압']):
        return 'cell_voltage'
    
    # 배터리 전압
    if any(kw in name_upper or kw in label_upper for kw in ['PACK', 'BATTERY', 'HV', 'HIGH VOLTAGE', '고전압', '배터리']):
        if any(kw in name_upper or kw in unit_upper or kw in label_upper for kw in ['VOLT', 'V', '전압']):
            return 'battery_voltage'
    
    # 배터리 전류
    if any(kw in name_upper or kw in label_upper for kw in ['PACK', 'BATTERY', 'HV', '배터리']):
        if any(kw in name_upper or kw in unit_upper or kw in label_upper for kw in ['CURRENT', 'AMP', 'A', '전류']):
            return 'battery_current'
    
    # 온도 (단위 기반)
    if any(kw in unit_upper for kw in ['°C', '℃', 'DEGC', 'CELSIUS', '도']) or any(kw in name_upper or kw in label_upper for kw in ['TEMP', 'TEMPERATURE', '온도']):
        return 'temperature'
    
    # 충전 파워
    if 'CHARG' in name_upper and any(kw in name_upper or kw in unit_upper for kw in ['POWER', 'KW', 'W', '전력', '파워']):
        return 'charging_power'
    
    # DTC / 고장
    if any(kw in name_upper or kw in label_upper for kw in ['DTC', 'FAULT', 'ERROR', 'WARNING', 'ALARM', '고장', '경고', '오류']):
        return 'dtc'
    
    # 차량 속도 (단위 기반)
    if any(kw in unit_upper for kw in ['KM/H', 'MPH', 'KPH']) or any(kw in name_upper or kw in label_upper for kw in ['VEHICLE SPEED', 'CAR SPEED', '차속', '속도']):
        return 'drive_speed'
    
    # 토크 (단위 기반)
    if any(kw in unit_upper for kw in ['NM', 'N·M', 'N-M']) or 'TORQUE' in name_upper or '토크' in label_upper:
        return 'drive_torque'
    
    # 구동 파워
    if any(kw in name_upper for kw in ['MOTOR POWER', 'DRIVE POWER']) or '구동전력' in label_upper:
        return 'drive_power'
    
    return 'other'


def reclassify_all_definitions():
    """전체 정의 데이터 재분류 (CLI 명령 및 임포트 후 자동 실행)."""
    print("📊 Reclassifying definition data...")
    
    # 1. Vehicle powertrain
    print("  🚗 Vehicle powertrain...")
    result = db.session.execute(text("""
        WITH model_classification AS (
            SELECT 
                id,
                model,
                CASE
                    WHEN model ~* '\\m(EV6|EV9|EV3|EV4|EV5|IONIQ 5|IONIQ 6|IONIQ 7|KONA ELECTRIC|KONA EV|NIRO EV|SOUL EV|RAY EV|GV60|GV70 ELECTRIC|ID\\.4|ID\\.3|ID\\.7|MODEL [3SXY]|LEAF|ARIYA|BOLT EV|BOLT EUV|E-TRON|TAYCAN|I-PACE|MACH-E|LYRIQ|ATTO 3)\\M' THEN 'BEV'
                    WHEN model ~* '\\m(PLUG-?IN|PHEV|RECHARGEABLE)\\M' THEN 'PHEV'
                    WHEN model ~* '\\m(HYBRID|HEV)\\M' AND NOT model ~* '\\m(PLUG)\\M' THEN 'HEV'
                    WHEN model ~* '\\m(DIESEL|TURBO|GDI|CRDI)\\M' THEN 'ICE'
                    ELSE 'unknown'
                END as inferred_powertrain
            FROM vehicle_definitions
        )
        UPDATE vehicle_definitions v
        SET powertrain = mc.inferred_powertrain
        FROM model_classification mc
        WHERE v.id = mc.id AND v.powertrain != mc.inferred_powertrain
    """))
    db.session.commit()
    print(f"     Updated {result.rowcount} vehicles")
    
    # 2. DBC signals protocol (always CAN)
    print("  📡 DBC signals protocol...")
    result = db.session.execute(text("""
        UPDATE dbc_signals
        SET protocol = 'CAN'
        WHERE protocol IS NULL OR protocol != 'CAN'
    """))
    db.session.commit()
    print(f"     Updated {result.rowcount} signals")
    
    # 3. Diagnostic commands protocol
    print("  🔧 Diagnostic commands protocol...")
    result = db.session.execute(text("""
        UPDATE diagnostic_commands
        SET protocol = CASE
            WHEN service IN ('01', '02', '03', '04', '05', '06', '07', '08', '09', '0A') THEN 'OBD-II'
            WHEN service IN ('10', '11', '14', '19', '22', '27', '2E', '2F', '31', '3E', '85') THEN 'UDS'
            WHEN service IN ('21', '23') THEN 'KWP2000'
            ELSE 'unknown'
        END
        WHERE protocol IS NULL OR protocol = 'unknown'
    """))
    db.session.commit()
    print(f"     Updated {result.rowcount} commands")
    
    # 4. ECU module from address and name
    print("  🏭 ECU modules from addresses...")
    result = db.session.execute(text("""
        UPDATE diagnostic_commands
        SET ecu_module = CASE
            -- Standard OBD-II addresses
            WHEN UPPER(REPLACE(ecu_address, '0x', '')) IN ('7E0', '7E8') THEN 'ECM'
            WHEN UPPER(REPLACE(ecu_address, '0x', '')) IN ('7E1', '7E9') THEN 'TCM'
            -- Hyundai/Kia EV addresses
            WHEN UPPER(REPLACE(ecu_address, '0x', '')) IN ('7E4', '7EC') THEN 'BMS'
            WHEN UPPER(REPLACE(ecu_address, '0x', '')) IN ('7E2', '7EA') THEN 'MCU'
            WHEN UPPER(REPLACE(ecu_address, '0x', '')) IN ('7E5', '7ED') THEN 'OBC'
            WHEN UPPER(REPLACE(ecu_address, '0x', '')) IN ('7C6', '7CE') THEN 'CLUSTER'
            WHEN UPPER(REPLACE(ecu_address, '0x', '')) IN ('7A0', '7A8') THEN 'BCM'
            WHEN UPPER(REPLACE(ecu_address, '0x', '')) IN ('7D1', '7D9') THEN 'ABS'
            -- Name patterns
            WHEN ecu_name ~* '(bms|battery)' OR label ~* '(battery|pack|cell|soc|soh|배터리)' THEN 'BMS'
            WHEN ecu_name ~* '(motor|mcu|inverter)' OR label ~* '(motor|inverter|모터)' THEN 'MCU'
            WHEN ecu_name ~* '(obc|charger)' OR label ~* '(charger|charging|충전)' THEN 'OBC'
            WHEN ecu_name ~* '(vcu|vehicle)' OR label ~* '(vehicle_control)' THEN 'VCU'
            WHEN ecu_name ~* '(ecm|engine)' OR label ~* '(engine|rpm|coolant|엔진)' THEN 'ECM'
            WHEN ecu_name ~* '(tcm|transmission)' OR label ~* '(transmission|gear|변속)' THEN 'TCM'
            WHEN ecu_name ~* '(cluster|dashboard)' OR label ~* '(계기판)' THEN 'CLUSTER'
            WHEN ecu_name ~* '(bcm|body)' THEN 'BCM'
            WHEN ecu_name ~* '(abs|brake)' OR label ~* '(abs|brake|제동)' THEN 'ABS'
            ELSE 'UNKNOWN'
        END
        WHERE ecu_module IS NULL OR ecu_module = 'UNKNOWN'
    """))
    db.session.commit()
    print(f"     Updated {result.rowcount} command ECUs")
    
    # 5. DBC signal ECU from message name and transmitter
    print("  🏭 DBC signal ECU modules...")
    result = db.session.execute(text("""
        UPDATE dbc_signals s
        SET ecu_module = CASE
            WHEN signal_name ~* '(bms|battery|pack|cell|soc|soh|배터리)' THEN 'BMS'
            WHEN signal_name ~* '(motor|inverter|mccu|mcu|모터)' THEN 'MCU'
            WHEN signal_name ~* '(obc|charger|charge(?!_discharge)|충전)' THEN 'OBC'
            WHEN signal_name ~* '(vcu|vehicle_control)' THEN 'VCU'
            WHEN signal_name ~* '(ecm|engine|엔진)' THEN 'ECM'
            WHEN signal_name ~* '(tcm|transmission|변속)' THEN 'TCM'
            WHEN signal_name ~* '(cluster|dashboard|계기판)' THEN 'CLUSTER'
            WHEN signal_name ~* '(bcm|body)' THEN 'BCM'
            WHEN signal_name ~* '(abs|brake|제동)' THEN 'ABS'
            ELSE 'UNKNOWN'
        END
        WHERE ecu_module IS NULL OR ecu_module = 'UNKNOWN'
    """))
    db.session.commit()
    print(f"     Updated {result.rowcount} signal ECUs")
    
    # 6. Signal category from name, unit, and Korean labels
    print("  📋 Signal categories...")
    result = db.session.execute(text("""
        UPDATE dbc_signals
        SET signal_category = CASE
            WHEN signal_name ~* '\\m(soc|state.*charge|충전상태)\\M' THEN 'battery_soc'
            WHEN signal_name ~* '\\m(soh|state.*health|배터리수명|건강상태)\\M' THEN 'battery_soh'
            WHEN signal_name ~* 'cell.*volt' THEN 'cell_voltage'
            WHEN signal_name ~* '(pack|battery|hv|고전압|배터리).*(voltage|volt|전압)' THEN 'battery_voltage'
            WHEN signal_name ~* '(pack|battery|hv|배터리).*(current|amp|전류)' THEN 'battery_current'
            WHEN signal_name ~* '(temp|temperature|온도)' OR unit ~* '(°C|℃|degc|celsius)' THEN 'temperature'
            WHEN signal_name ~* 'charg.*power' OR (signal_name ~* 'charg' AND unit ~* '(kw|power)') THEN 'charging_power'
            WHEN signal_name ~* '(dtc|fault|error|warning|고장|경고)' THEN 'dtc'
            WHEN unit ~* '(km/h|mph|kph)' OR signal_name ~* '(vehicle.*speed|car.*speed|차속|속도)' THEN 'drive_speed'
            WHEN unit ~* '(nm|n·m)' OR signal_name ~* 'torque|토크' THEN 'drive_torque'
            WHEN signal_name ~* '(motor|drive).*power|구동전력' THEN 'drive_power'
            ELSE 'other'
        END
        WHERE signal_category IS NULL OR signal_category = 'other'
    """))
    db.session.commit()
    print(f"     Updated {result.rowcount} categories")
    
    print("✅ Reclassification complete!")
    
    # Return summary counts
    summary = db.session.execute(text("""
        SELECT 
            'vehicle_definitions.powertrain' as table_column,
            jsonb_object_agg(powertrain, count) as counts
        FROM (
            SELECT powertrain, COUNT(*) as count
            FROM vehicle_definitions
            GROUP BY powertrain
            ORDER BY count DESC
        ) t
        
        UNION ALL
        
        SELECT 
            'diagnostic_commands.protocol',
            jsonb_object_agg(protocol, count)
        FROM (
            SELECT protocol, COUNT(*) as count
            FROM diagnostic_commands
            GROUP BY protocol
            ORDER BY count DESC
        ) t
        
        UNION ALL
        
        SELECT 
            'diagnostic_commands.ecu_module',
            jsonb_object_agg(ecu_module, count)
        FROM (
            SELECT ecu_module, COUNT(*) as count
            FROM diagnostic_commands
            GROUP BY ecu_module
            ORDER BY count DESC
        ) t
        
        UNION ALL
        
        SELECT 
            'dbc_signals.signal_category',
            jsonb_object_agg(signal_category, count)
        FROM (
            SELECT signal_category, COUNT(*) as count
            FROM dbc_signals
            GROUP BY signal_category
            ORDER BY count DESC
        ) t
    """)).fetchall()
    
    return {row.table_column: row.counts for row in summary}
