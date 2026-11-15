"""신호 범위 검증 테스트 (Issue #12)."""

import pytest
from app.modules.canlab.engine.decode import decode_signals, RuleRef
from app.modules.canlab.engine.search import Layout


def test_invalid_voltage_filtered():
    """물리적으로 불가능한 전압은 결과에서 차단."""
    # 28.18V는 12V 보조배터리 범위(6~16V)를 벗어남
    
    layout = Layout(0x7E4, 0x0101, 29, 1, "big", False, 0.1, 0)  # aux_voltage
    rule = RuleRef(1, 1, "aux_voltage", layout, 1.0)
    
    # 14.5V (정상)
    samples = {(0x7E4, 0x0101): [(1000, bytes([0] * 29 + [145]))]}
    result = decode_signals(samples, [rule])
    assert "aux_voltage" in result
    assert result["aux_voltage"]["value"] == 14.5
    
    # 28.18V (비정상) → 필터링됨
    samples = {(0x7E4, 0x0101): [(1000, bytes([0] * 29 + [281]))]}
    result = decode_signals(samples, [rule])
    assert "aux_voltage" not in result  # 범위 밖이라 제외됨


def test_invalid_percentage_filtered():
    """839.9% 같은 비정상 퍼센트 값 차단."""
    # SOH는 0~110% 범위
    
    layout = Layout(0x7E4, 0x0105, 25, 2, "big", False, 0.1, 0)  # soh
    rule = RuleRef(1, 1, "soh", layout, 1.0)
    
    # 95.3% (정상)
    samples = {(0x7E4, 0x0105): [(1000, bytes([0] * 25 + [0x03, 0xB9]))]}  # 953 → 95.3%
    result = decode_signals(samples, [rule])
    assert "soh" in result
    assert result["soh"]["value"] == 95.3
    
    # 839.9% (비정상) → 필터링됨
    samples = {(0x7E4, 0x0105): [(1000, bytes([0] * 25 + [0x20, 0xCF]))]}  # 8399 → 839.9%
    result = decode_signals(samples, [rule])
    assert "soh" not in result


def test_signal_minimum_maximum():
    """모든 신호에 minimum과 maximum이 정의되어 있는지."""
    from app.modules.canlab.engine.signals import SIGNALS
    
    for signal in SIGNALS:
        assert hasattr(signal, "minimum")
        assert hasattr(signal, "maximum")
        assert signal.minimum < signal.maximum
        
        # 주요 신호 범위 확인
        if signal.key == "aux_voltage":
            assert signal.minimum == 6
            assert signal.maximum == 16
        elif signal.key == "soh":
            assert signal.minimum == 0
            assert signal.maximum == 110
        elif signal.key == "ldc_voltage":
            assert signal.minimum == 0
            assert signal.maximum == 20


def test_cell_voltage_range():
    """셀 전압 범위 검증 (1.5~4.6V)."""
    layout = Layout(0x7E4, 0x0102, 4, 1, "big", False, 0.02, 0)
    rule = RuleRef(1, 1, "cell_1", layout, 1.0)
    
    # 3.54V (정상, raw=177)
    samples = {(0x7E4, 0x0102): [(1000, bytes([0] * 4 + [177]))]}
    result = decode_signals(samples, [rule])
    assert "cell_1" in result
    
    # 0.5V (비정상, 방전 과다) → 필터링
    samples = {(0x7E4, 0x0102): [(1000, bytes([0] * 4 + [25]))]}
    result = decode_signals(samples, [rule])
    assert "cell_1" not in result
    
    # 5.0V (비정상, 과충전) → 필터링
    samples = {(0x7E4, 0x0102): [(1000, bytes([0] * 4 + [250]))]}
    result = decode_signals(samples, [rule])
    assert "cell_1" not in result
