"""ECU and signal category backfill based on explicit source file evidence.

Phase 6: Evidence-based classification only - no guessing or inference.
"""
import re
from typing import Optional

# ECU module patterns in file paths, comments, and signal names
ECU_PATTERNS = {
    'BMS': [
        r'\bBMS\b',
        r'Battery[\s_]Management',
        r'/BMS/',
        r'_bms_',
        r'^bms[\s_]',
    ],
    'MCU': [
        r'\bMCU\b',
        r'Motor[\s_]Control',
        r'/MCU/',
        r'_mcu_',
        r'^mcu[\s_]',
    ],
    'OBC': [
        r'\bOBC\b',
        r'On[\s_]?Board[\s_]Charger',
        r'/OBC/',
        r'_obc_',
        r'^obc[\s_]',
    ],
    'VCU': [
        r'\bVCU\b',
        r'Vehicle[\s_]Control',
        r'/VCU/',
        r'_vcu_',
        r'^vcu[\s_]',
    ],
    'ECM': [
        r'\bECM\b',
        r'Engine[\s_]Control',
        r'/ECM/',
        r'_ecm_',
        r'^ecm[\s_]',
    ],
    'TCM': [
        r'\bTCM\b',
        r'Transmission[\s_]Control',
        r'/TCM/',
        r'_tcm_',
        r'^tcm[\s_]',
    ],
    'BCM': [
        r'\bBCM\b',
        r'Body[\s_]Control',
        r'/BCM/',
        r'_bcm_',
        r'^bcm[\s_]',
    ],
    'ABS': [
        r'\bABS\b',
        r'\bESP\b',
        r'Anti[\s_]?lock',
        r'/ABS/',
        r'_abs_',
    ],
    'HVAC': [
        r'\bHVAC\b',
        r'Climate',
        r'/HVAC/',
        r'_hvac_',
    ],
    'TPMS': [
        r'\bTPMS\b',
        r'Tire[\s_]Pressure',
        r'/TPMS/',
        r'_tpms_',
    ],
}

# Signal category patterns based on signal name and description
CATEGORY_PATTERNS = {
    'battery_soc': [
        r'\bSOC\b',
        r'State[\s_]?of[\s_]?Charge',
        r'Battery[\s_]?Charge',
    ],
    'battery_soh': [
        r'\bSOH\b',
        r'State[\s_]?of[\s_]?Health',
        r'Battery[\s_]?Health',
    ],
    'battery_voltage': [
        r'Battery[\s_]?Volt',
        r'\bHV[\s_]?Volt',
        r'Cell[\s_]?Volt',
        r'Pack[\s_]?Volt',
    ],
    'battery_current': [
        r'Battery[\s_]?Current',
        r'\bHV[\s_]?Current',
        r'Pack[\s_]?Current',
    ],
    'battery_temp': [
        r'Battery[\s_]?Temp',
        r'Cell[\s_]?Temp',
        r'Pack[\s_]?Temp',
        r'BMS[\s_]?Temp',
    ],
    'motor_speed': [
        r'Motor[\s_]?Speed',
        r'Motor[\s_]?RPM',
        r'\bRPM\b',
    ],
    'motor_torque': [
        r'Motor[\s_]?Torque',
        r'Torque[\s_]?Actual',
    ],
    'motor_temp': [
        r'Motor[\s_]?Temp',
        r'Inverter[\s_]?Temp',
        r'MCU[\s_]?Temp',
    ],
    'vehicle_speed': [
        r'\bSpeed\b',
        r'Vehicle[\s_]?Speed',
        r'\bVSS\b',
    ],
    'odometer': [
        r'Odometer',
        r'Mileage',
        r'Total[\s_]?Distance',
    ],
    'charging_status': [
        r'Charg(e|ing)[\s_]?Status',
        r'Charg(e|ing)[\s_]?State',
    ],
    'charging_power': [
        r'Charg(e|ing)[\s_]?Power',
        r'Charg(e|ing)[\s_]?Current',
        r'Charg(e|ing)[\s_]?Voltage',
    ],
    'dtc': [
        r'\bDTC\b',
        r'Fault[\s_]?Code',
        r'Diagnostic[\s_]?Trouble',
        r'Error[\s_]?Code',
    ],
}


def extract_ecu_from_evidence(
    file_path: Optional[str] = None,
    command_label: Optional[str] = None,
    signal_name: Optional[str] = None,
    dbc_comment: Optional[str] = None,
) -> Optional[str]:
    """Extract ECU module from explicit evidence in source files.
    
    Args:
        file_path: Source file path
        command_label: Command/signal label
        signal_name: DBC signal name
        dbc_comment: DBC file comment
        
    Returns:
        ECU module name if found, else None
    """
    # Collect all text sources
    sources = []
    if file_path:
        sources.append(file_path)
    if command_label:
        sources.append(command_label)
    if signal_name:
        sources.append(signal_name)
    if dbc_comment:
        sources.append(dbc_comment)
    
    if not sources:
        return None
    
    # Try each ECU pattern against all sources
    for ecu_name, patterns in ECU_PATTERNS.items():
        for pattern in patterns:
            for source in sources:
                if re.search(pattern, source, re.IGNORECASE):
                    return ecu_name
    
    return None


def extract_category_from_evidence(
    signal_name: Optional[str] = None,
    dbc_comment: Optional[str] = None,
    command_label: Optional[str] = None,
) -> Optional[str]:
    """Extract signal category from explicit evidence.
    
    Args:
        signal_name: DBC signal name
        dbc_comment: DBC file comment
        command_label: Command label
        
    Returns:
        Signal category if found, else None
    """
    # Collect all text sources
    sources = []
    if signal_name:
        sources.append(signal_name)
    if dbc_comment:
        sources.append(dbc_comment)
    if command_label:
        sources.append(command_label)
    
    if not sources:
        return None
    
    # Try each category pattern against all sources
    for category, patterns in CATEGORY_PATTERNS.items():
        for pattern in patterns:
            for source in sources:
                if re.search(pattern, source, re.IGNORECASE):
                    return category
    
    return None
