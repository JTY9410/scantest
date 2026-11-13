"""VIN (Vehicle Identification Number) decoder.

Privacy notice: VINs are personal data. This module provides masking utilities.
Never log or commit full VINs from real vehicles.
"""
from typing import Optional, Literal
import re


def validate_vin(vin: str) -> bool:
    """Validate VIN format.
    
    - 17 characters
    - No I, O, Q (easily confused with 1, 0, 0)
    - Alphanumeric only
    
    Does not validate check digit (position 9) - that requires manufacturer-specific logic.
    """
    if not vin or len(vin) != 17:
        return False
    
    # No I, O, Q allowed
    if re.search(r'[IOQ]', vin, re.IGNORECASE):
        return False
    
    # Only alphanumeric
    if not vin.isalnum():
        return False
    
    return True


def mask_vin(vin: Optional[str]) -> Optional[str]:
    """Mask VIN for privacy: show WMI (first 3) + last 4, mask middle.
    
    Example: KMHXXXXXX1234 or KMH******1234
    
    Returns None if VIN is None or invalid.
    """
    if not vin or len(vin) != 17:
        return None
    
    return f"{vin[:3]}{'*' * 10}{vin[-4:]}"


def extract_wmi(vin: str) -> Optional[str]:
    """Extract World Manufacturer Identifier (positions 1-3)."""
    if not validate_vin(vin):
        return None
    return vin[:3]


def extract_model_year_position(vin: str) -> Optional[str]:
    """Extract model year code from position 10.
    
    Returns the character at position 10 (0-indexed position 9).
    Decoding this character to an actual year requires a lookup table.
    """
    if not validate_vin(vin):
        return None
    return vin[9]


def extract_vds(vin: str) -> Optional[str]:
    """Extract Vehicle Descriptor Section (positions 4-9).
    
    Manufacturer-specific codes for model, body type, engine, etc.
    """
    if not validate_vin(vin):
        return None
    return vin[3:9]


def extract_vis(vin: str) -> Optional[str]:
    """Extract Vehicle Identifier Section (positions 10-17).
    
    Contains model year, plant code, and serial number.
    """
    if not validate_vin(vin):
        return None
    return vin[9:17]


# Model year decoding table (position 10)
# Source: ISO 3779, SAE J853
MODEL_YEAR_CODES = {
    'A': 2010, 'B': 2011, 'C': 2012, 'D': 2013, 'E': 2014,
    'F': 2015, 'G': 2016, 'H': 2017, 'J': 2018, 'K': 2019,
    'L': 2020, 'M': 2021, 'N': 2022, 'P': 2023, 'R': 2024,
    'S': 2025, 'T': 2026, 'V': 2027, 'W': 2028, 'X': 2029,
    'Y': 2030,
    # Pre-2010 cycle (for older vehicles)
    '1': 2001, '2': 2002, '3': 2003, '4': 2004, '5': 2005,
    '6': 2006, '7': 2007, '8': 2008, '9': 2009,
}


def decode_model_year(vin: str) -> Optional[int]:
    """Decode model year from position 10.
    
    Returns year as integer (e.g. 2023) or None if unable to decode.
    Note: This is a 30-year cycle; context is needed for disambiguation.
    """
    year_code = extract_model_year_position(vin)
    if not year_code:
        return None
    
    return MODEL_YEAR_CODES.get(year_code.upper())


# WMI manufacturer mapping (partial list with citations)
# Source: SAE J853, NHTSA WMI database
WMI_MANUFACTURERS = {
    # Korean manufacturers
    'KMH': 'Hyundai',
    'KNA': 'Kia',
    'KNE': 'Kia',
    'KPT': 'Genesis',
    
    # Tesla
    '5YJ': 'Tesla',
    '7SA': 'Tesla',
    
    # Japanese
    'JN1': 'Nissan',
    'JN8': 'Nissan',
    'JTH': 'Toyota',
    'JT2': 'Toyota',
    '5FN': 'Honda',
    '1HG': 'Honda',
    
    # US manufacturers
    '1G1': 'Chevrolet',
    '1G2': 'Pontiac',
    '3G1': 'Chevrolet',
    'KL8': 'Chevrolet',  # Korean-built Chevrolet
    '5XX': 'Chevrolet',
    '1FA': 'Ford',
    '1FT': 'Ford',
    
    # European
    'WBA': 'BMW',
    'WBS': 'BMW',
    'WAU': 'Audi',
    'WP0': 'Porsche',
    'VF3': 'Citroën',
    'VF7': 'Citroën',
}


def decode_manufacturer(vin: str) -> Optional[str]:
    """Decode manufacturer from WMI (positions 1-3).
    
    Returns manufacturer name or None if unknown.
    """
    wmi = extract_wmi(vin)
    if not wmi:
        return None
    
    return WMI_MANUFACTURERS.get(wmi)


PowertrainType = Literal['BEV', 'PHEV', 'HEV', 'ICE', 'unknown']


def decode_powertrain_from_vin(
    vin: str,
    vin_rules: list  # Loaded from database: list of rule dicts
) -> tuple[Optional[PowertrainType], str, float]:
    """Decode powertrain type from VIN using manufacturer-specific rules.
    
    Args:
        vin: 17-character VIN
        vin_rules: List of rule dicts from database with keys:
                   wmi_pattern, vds_position, vds_value_pattern, powertrain, confidence
    
    Returns:
        Tuple of (powertrain_type, source, confidence)
        - powertrain_type: BEV, PHEV, HEV, ICE, or unknown
        - source: 'vin_rule' if matched, 'unknown' otherwise
        - confidence: 0.0-1.0, based on rule quality
    """
    if not validate_vin(vin):
        return (None, 'invalid_vin', 0.0)
    
    wmi = extract_wmi(vin)
    vds = extract_vds(vin)
    
    if not wmi or not vds:
        return (None, 'invalid_vin', 0.0)
    
    # Check rules in order (higher confidence first)
    for rule in sorted(vin_rules, key=lambda r: r.get('confidence', 0), reverse=True):
        # Match WMI pattern (exact match or prefix)
        rule_wmi = rule.get('wmi_pattern', '')
        if not wmi.startswith(rule_wmi):
            continue
        
        # Check VDS position if specified
        vds_pos = rule.get('vds_position')
        if vds_pos is not None:
            # Convert 1-indexed position (4-9) to 0-indexed VDS position (0-5)
            vds_idx = vds_pos - 4
            if vds_idx < 0 or vds_idx >= len(vds):
                continue
            
            vds_pattern = rule.get('vds_value_pattern', '')
            if vds[vds_idx] != vds_pattern:
                continue
        
        # Rule matched!
        return (
            rule.get('powertrain', 'unknown'),
            'vin_rule',
            rule.get('confidence', 0.9)
        )
    
    # No rule matched
    return ('unknown', 'no_vin_rule', 0.0)
