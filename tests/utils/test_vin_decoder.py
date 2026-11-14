"""Test VIN decoder module."""
import pytest
from app.utils.vin_decoder import (
    validate_vin,
    mask_vin,
    extract_wmi,
    extract_vds,
    decode_model_year,
    decode_manufacturer,
    decode_powertrain_from_vin,
)


# Synthetic/public-documentation VINs only - never use real VINs
SYNTHETIC_VINS = {
    'hyundai_ioniq5': 'KMHXXXXE0NX123456',  # Korean Hyundai, position 8='E' (BEV)
    'kia_ev6': 'KNAXXXXE0NX123456',         # Korean Kia, position 8='E' (BEV) - fixed VDS
    'tesla_model3': '5YJ3XXXXNX1234567',    # Tesla Model 3
    'nissan_leaf': 'JN1AXXXXANX123456',     # Nissan Leaf
    'invalid_with_O': 'KMHXXXXEONX12345',   # Contains 'O' - invalid
    'invalid_length': 'KMHXXXX',            # Too short
}


def test_validate_vin():
    """Test VIN validation."""
    # Valid format
    assert validate_vin('KMHXXXXE0NX123456') == True
    assert validate_vin('5YJ3XXXXNX1234567') == True
    
    # Invalid: contains I, O, Q
    assert validate_vin('KMHXXXIEXXXXXX123') == False
    assert validate_vin('KMHXXXOEXXXXXX123') == False
    assert validate_vin('KMHXXXQEXXXXXX123') == False
    
    # Invalid: wrong length
    assert validate_vin('KMHXXXXE0N12345') == False  # 16 chars
    assert validate_vin('KMHXXXXE0N12345678') == False  # 18 chars
    assert validate_vin('') == False
    assert validate_vin('KMHXXXX') == False
    
    # Invalid: non-alphanumeric
    assert validate_vin('KMHXXXX-0NX123456') == False
    assert validate_vin('KMHXXXX 0NX123456') == False


def test_mask_vin():
    """Test VIN masking for privacy."""
    assert mask_vin('KMHXXXXE0NX123456') == 'KMH**********3456'
    assert mask_vin('5YJ3XXXXNX1234567') == '5YJ**********4567'
    assert mask_vin('1G1XXXXXNX1234567') == '1G1**********4567'
    
    # Invalid VINs
    assert mask_vin('') is None
    assert mask_vin('SHORT') is None
    assert mask_vin(None) is None


def test_extract_wmi():
    """Test WMI extraction."""
    assert extract_wmi('KMHXXXXE0NX123456') == 'KMH'
    assert extract_wmi('5YJ3XXXXNX1234567') == '5YJ'
    assert extract_wmi('JN1AXXXXANX123456') == 'JN1'
    
    # Invalid
    assert extract_wmi('SHORT') is None
    assert extract_wmi('KMHXXXOEXXXXXX123') is None  # Contains O


def test_extract_vds():
    """Test VDS extraction (positions 4-9)."""
    vin = 'KMHXXXXE0NX123456'
    vds = extract_vds(vin)
    assert vds == 'XXXXE0'
    assert len(vds) == 6
    
    vin2 = '5YJ3XXXXNX1234567'
    vds2 = extract_vds(vin2)
    assert vds2 == '3XXXXN'


def test_decode_model_year():
    """Test model year decoding from position 10."""
    # 2020-2029 cycle (position 10 = index 9)
    assert decode_model_year('KMHXXXXXXL0123456') == 2020  # L at pos 10
    assert decode_model_year('KMHXXXXXXM0123456') == 2021  # M at pos 10
    assert decode_model_year('KMHXXXXXXN0123456') == 2022  # N at pos 10
    assert decode_model_year('KMHXXXXXXP0123456') == 2023  # P at pos 10
    assert decode_model_year('KMHXXXXXXR0123456') == 2024  # R at pos 10
    
    # 2001-2009 cycle
    assert decode_model_year('KMHXXXXXX10123456') == 2001  # 1 at pos 10
    assert decode_model_year('KMHXXXXXX50123456') == 2005  # 5 at pos 10
    assert decode_model_year('KMHXXXXXX90123456') == 2009  # 9 at pos 10
    
    # Invalid
    assert decode_model_year('SHORT') is None


def test_decode_manufacturer():
    """Test manufacturer decoding from WMI."""
    assert decode_manufacturer('KMHXXXXE0NX123456') == 'Hyundai'
    assert decode_manufacturer('KNAXXXXE0NX123456') == 'Kia'
    assert decode_manufacturer('5YJ3XXXXNX1234567') == 'Tesla'
    assert decode_manufacturer('JN1AXXXXANX123456') == 'Nissan'
    assert decode_manufacturer('1G1XXXXXNX1234567') == 'Chevrolet'
    
    # Unknown WMI
    assert decode_manufacturer('ZZZXXXXXNX1234567') is None


def test_decode_powertrain_from_vin():
    """Test powertrain decoding with sample rules."""
    # Sample rules mimicking database data
    sample_rules = [
        {
            'wmi_pattern': 'KMH',
            'vds_position': 8,  # 1-indexed (5th char of VDS)
            'vds_value_pattern': 'E',
            'powertrain': 'BEV',
            'confidence': 0.95,
        },
        {
            'wmi_pattern': 'KNA',
            'vds_position': 8,
            'vds_value_pattern': 'E',
            'powertrain': 'BEV',
            'confidence': 0.95,
        },
        {
            'wmi_pattern': 'KMH',
            'vds_position': 8,
            'vds_value_pattern': 'F',
            'powertrain': 'PHEV',
            'confidence': 0.95,
        },
        {
            'wmi_pattern': '5YJ',
            'vds_position': 4,
            'vds_value_pattern': '3',
            'powertrain': 'BEV',
            'confidence': 0.99,
        },
    ]
    
    # Hyundai BEV (position 8 = E)
    vin = 'KMHXXXXE0NX123456'
    powertrain, source, confidence = decode_powertrain_from_vin(vin, sample_rules)
    assert powertrain == 'BEV'
    assert source == 'vin_rule'
    assert confidence == 0.95
    
    # Kia BEV (position 8 = E)
    vin2 = 'KNAXXXXE0NX123456'
    powertrain2, source2, confidence2 = decode_powertrain_from_vin(vin2, sample_rules)
    assert powertrain2 == 'BEV'
    assert source2 == 'vin_rule'
    
    # Hyundai PHEV (position 8 = F)
    vin3 = 'KMHXXXXF0NX123456'
    powertrain3, source3, confidence3 = decode_powertrain_from_vin(vin3, sample_rules)
    assert powertrain3 == 'PHEV'
    assert source3 == 'vin_rule'
    assert confidence3 == 0.95
    
    # Tesla Model 3 (position 4 = 3)
    vin4 = '5YJ3XXXXNX1234567'
    powertrain4, source4, confidence4 = decode_powertrain_from_vin(vin4, sample_rules)
    assert powertrain4 == 'BEV'
    assert source4 == 'vin_rule'
    assert confidence4 == 0.99
    
    # No matching rule
    vin5 = '1G1XXXXXNX1234567'  # Chevrolet, no rule
    powertrain5, source5, confidence5 = decode_powertrain_from_vin(vin5, sample_rules)
    assert powertrain5 == 'unknown'
    assert source5 == 'no_vin_rule'
    assert confidence5 == 0.0
    
    # Invalid VIN
    powertrain6, source6, confidence6 = decode_powertrain_from_vin('SHORT', sample_rules)
    assert powertrain6 is None
    assert source6 == 'invalid_vin'


def test_no_full_vins_in_code():
    """Assert that no full real VINs appear in test code.
    
    This test checks that we only use synthetic/masked VINs.
    """
    import inspect
    source = inspect.getsource(pytest.importorskip('tests.utils.test_vin_decoder'))
    
    # Check for common real VIN patterns (this is a basic check)
    # Real VINs should not appear; only synthetic ones with 'X' masking
    
    # Count X's in VINs - synthetic VINs should have many X's
    vins_in_code = []
    for line in source.split('\n'):
        if "'" in line and len(line) > 20:
            # Look for potential VIN strings
            import re
            potential_vins = re.findall(r"'([A-Z0-9]{17})'", line)
            vins_in_code.extend(potential_vins)
    
    # All VINs in test code should contain 'X' (synthetic marker)
    for vin in vins_in_code:
        if len(vin) == 17 and vin.isalnum():
            assert 'X' in vin, f"Potential real VIN in test code: {mask_vin(vin)}"
