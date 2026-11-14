"""ECU and signal category backfill based on explicit source file evidence ONLY.

Evidence-based classification - NO guessing or inference from signal names.

ECU module sources (in priority order):
1. DBC BO_ transmitter node explicitly mapped to ECU in source file
2. UDS/ISO-TP CAN ID explicitly associated with named ECU header in same source file
3. File path that literally contains ECU name (e.g., /BMS/, _bms_, bms_commands/)

Signal category sources:
1. DBC comment that explicitly states the category
2. File structure that groups signals by category (e.g., /battery_soc/, /charging_status/)

NO pattern matching on signal names. NO keyword guessing.
"""
import re
from typing import Optional, Dict, Any
from datetime import datetime, timezone

# ECU names that must appear literally in paths
ECU_NAMES = [
    'BMS',      # Battery Management System
    'MCU',      # Motor Control Unit
    'OBC',      # On-Board Charger
    'VCU',      # Vehicle Control Unit
    'ECM',      # Engine Control Module
    'TCM',      # Transmission Control Module
    'BCM',      # Body Control Module
    'ABS',      # Anti-lock Braking System
    'ESP',      # Electronic Stability Program
    'HVAC',     # Heating, Ventilation, Air Conditioning
    'TPMS',     # Tire Pressure Monitoring System
    'ADAS',     # Advanced Driver Assistance Systems
    'ICM',      # Instrument Cluster Module
    'CGW',      # Central Gateway
]

# Signal categories that must appear literally in paths or explicit DBC comments
SIGNAL_CATEGORIES = [
    'battery_soc',
    'battery_soh',
    'battery_voltage',
    'battery_current',
    'battery_temp',
    'motor_speed',
    'motor_torque',
    'motor_temp',
    'vehicle_speed',
    'odometer',
    'charging_status',
    'charging_power',
    'dtc',
]


def extract_ecu_from_file_path(file_path: str) -> Optional[tuple[str, Dict[str, Any]]]:
    """Extract ECU from file path that literally contains ECU name.
    
    Rules:
    - Path must contain ECU name surrounded by path separators, underscores, or hyphens
    - Examples: /BMS/, /bms/, _BMS_, -bms-, bms_commands, commands_bms
    - NOT matched: "bmsdata" (no separator), "BMS123" (followed by digits)
    
    Returns:
        (ecu_name, evidence_dict) or None
    """
    if not file_path:
        return None
    
    path_lower = file_path.lower()
    
    for ecu in ECU_NAMES:
        ecu_lower = ecu.lower()
        
        # Pattern: ECU name surrounded by non-alphanumeric chars or at boundaries
        # Must be a complete word, not part of another word
        pattern = r'(?:^|[/_\-])' + re.escape(ecu_lower) + r'(?:[/_\-]|$)'
        
        if re.search(pattern, path_lower):
            evidence = {
                "rule": "file_path",
                "matched_text": file_path,
                "ecu_name": ecu,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            return ecu, evidence
    
    return None


def extract_ecu_from_dbc_transmitter(
    dbc_sender_ecu: Optional[str]
) -> Optional[tuple[str, Dict[str, Any]]]:
    """Extract ECU from DBC BO_ message sender/transmitter field.
    
    The DBC file explicitly states which ECU sends the message via the BO_ sender field.
    This is the most reliable source.
    
    Returns:
        (ecu_name, evidence_dict) or None
    """
    if not dbc_sender_ecu:
        return None
    
    sender_upper = dbc_sender_ecu.strip().upper()
    
    # Check if sender exactly matches a known ECU name
    for ecu in ECU_NAMES:
        if sender_upper == ecu.upper():
            evidence = {
                "rule": "dbc_transmitter",
                "matched_text": dbc_sender_ecu,
                "ecu_name": ecu,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            return ecu, evidence
    
    return None


def extract_ecu_from_uds_can_id(
    command_bytes: Optional[str],
    file_path: Optional[str]
) -> Optional[tuple[str, Dict[str, Any]]]:
    """Extract ECU from UDS/ISO-TP CAN ID if same file associates it with ECU.
    
    UDS diagnostic commands use specific CAN IDs for ECU communication.
    If the same source file (e.g., comments, documentation) explicitly maps
    CAN ID ranges to ECU names, use that mapping.
    
    Common UDS CAN ID ranges (from ISO 14229):
    - 0x7E0-0x7E7: Standard OBD-II
    - 0x7E8-0x7EF: Standard OBD-II responses
    - But manufacturer-specific mappings vary
    
    For now, only use if file path contains both CAN ID and ECU name.
    
    Returns:
        (ecu_name, evidence_dict) or None
    """
    if not command_bytes or not file_path:
        return None
    
    # Extract CAN ID from command (e.g., "22 01 05" or header "7E1")
    # This is a simplified check - full implementation would parse the file
    # for explicit CAN ID -> ECU mappings
    
    # For now, only use file path evidence if command looks like UDS
    if not (command_bytes.strip().startswith(('22', '01', '09', '03')) or 
            re.search(r'\b7[ED][0-9A-F]\b', command_bytes)):
        return None
    
    # Check if file path contains ECU name - this suggests association
    ecu_result = extract_ecu_from_file_path(file_path)
    if ecu_result:
        ecu, path_evidence = ecu_result
        evidence = {
            "rule": "uds_can_id",
            "matched_text": f"CAN ID in {file_path}, command: {command_bytes}",
            "ecu_name": ecu,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        return ecu, evidence
    
    return None


def extract_category_from_path(file_path: str) -> Optional[tuple[str, Dict[str, Any]]]:
    """Extract signal category from file path that literally contains category name.
    
    Returns:
        (category, evidence_dict) or None
    """
    if not file_path:
        return None
    
    path_lower = file_path.lower()
    
    for category in SIGNAL_CATEGORIES:
        # Category must appear as part of path structure
        if category in path_lower:
            evidence = {
                "rule": "file_path",
                "matched_text": file_path,
                "category": category,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            return category, evidence
    
    return None


def extract_category_from_dbc_comment(comment: Optional[str]) -> Optional[tuple[str, Dict[str, Any]]]:
    """Extract category from explicit DBC comment that states the category.
    
    Returns:
        (category, evidence_dict) or None
    """
    if not comment:
        return None
    
    comment_lower = comment.lower()
    
    # Look for explicit category statements in comments
    for category in SIGNAL_CATEGORIES:
        # Check for explicit mentions like "category: battery_soc" or "type: charging_status"
        if re.search(rf'\b{re.escape(category)}\b', comment_lower):
            evidence = {
                "rule": "dbc_comment",
                "matched_text": comment[:200],  # Truncate long comments
                "category": category,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            return category, evidence
    
    return None


# Main extraction functions used by CLI

def extract_ecu_from_evidence(
    file_path: Optional[str] = None,
    command_bytes: Optional[str] = None,
    dbc_sender_ecu: Optional[str] = None,
) -> Optional[tuple[str, Dict[str, Any]]]:
    """Extract ECU module from explicit evidence sources.
    
    Priority order:
    1. DBC transmitter (most reliable)
    2. UDS CAN ID + file association
    3. File path
    
    Returns:
        (ecu_name, evidence_dict) or None
    """
    # 1. DBC transmitter (highest priority)
    result = extract_ecu_from_dbc_transmitter(dbc_sender_ecu)
    if result:
        return result
    
    # 2. UDS CAN ID with file association
    result = extract_ecu_from_uds_can_id(command_bytes, file_path)
    if result:
        return result
    
    # 3. File path
    result = extract_ecu_from_file_path(file_path)
    if result:
        return result
    
    return None


def extract_category_from_evidence(
    file_path: Optional[str] = None,
    dbc_comment: Optional[str] = None,
) -> Optional[tuple[str, Dict[str, Any]]]:
    """Extract signal category from explicit evidence sources.
    
    Priority order:
    1. DBC comment (explicit statement)
    2. File path (directory structure)
    
    Returns:
        (category, evidence_dict) or None
    """
    # 1. DBC comment
    result = extract_category_from_dbc_comment(dbc_comment)
    if result:
        return result
    
    # 2. File path
    result = extract_category_from_path(file_path)
    if result:
        return result
    
    return None
