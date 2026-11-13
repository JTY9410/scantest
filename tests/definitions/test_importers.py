"""Tests for definition importers."""
import pytest
from pathlib import Path

from app.modules.definitions.importers import (
    compute_sha256,
    parse_dbc_file,
)


def test_compute_sha256(tmp_path):
    """SHA-256 계산 테스트."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello world")
    
    sha256 = compute_sha256(test_file)
    assert len(sha256) == 64
    assert sha256 == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def test_parse_dbc_simple():
    """간단한 DBC 파싱 테스트."""
    dbc_content = """VERSION "Test"

BO_ 256 TestMessage: 8 ECU1
 SG_ TestSignal : 0|8@1+ (1,0) [0|255] "unit" ECU2
"""
    tmp_file = Path("/tmp/test.dbc")
    tmp_file.write_text(dbc_content)
    
    messages = parse_dbc_file(tmp_file)
    assert len(messages) == 1
    assert messages[0]['can_id'] == 256
    assert messages[0]['name'] == 'TestMessage'
    assert len(messages[0]['signals']) == 1
    assert messages[0]['signals'][0]['name'] == 'TestSignal'
    
    tmp_file.unlink()


def test_parse_dbc_multiple_signals():
    """여러 신호가 있는 DBC 파싱."""
    dbc_content = """VERSION "Test"

BO_ 100 BatteryStatus: 8 BMS
 SG_ Voltage : 0|16@1+ (0.1,0) [0|500] "V" VCU
 SG_ Current : 16|16@1- (0.1,-1000) [-1000|1000] "A" VCU
 SG_ SOC : 32|8@1+ (1,0) [0|100] "%" VCU
"""
    tmp_file = Path("/tmp/test2.dbc")
    tmp_file.write_text(dbc_content)
    
    messages = parse_dbc_file(tmp_file)
    assert len(messages) == 1
    assert len(messages[0]['signals']) == 3
    
    voltage_sig = messages[0]['signals'][0]
    assert voltage_sig['name'] == 'Voltage'
    assert voltage_sig['start_bit'] == 0
    assert voltage_sig['bit_length'] == 16
    assert voltage_sig['factor'] == 0.1
    assert voltage_sig['unit'] == 'V'
    
    tmp_file.unlink()
