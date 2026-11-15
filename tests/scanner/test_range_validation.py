"""신호 범위 검증 테스트 (Issue #12)."""

import pytest
from app.modules.canlab.engine.decode import decode_signals, RuleRef
from app.modules.canlab.engine.search import Layout


def test_invalid_voltage_filtered():
    """물리적으로 불가능한 전압은 결과에서 차단."""
    # 28.18V는 12V 보조배터리 범위(6~16V)를 벗어남
    
    layout = Layout(0x7E4, 0x0101, 29, 1, "big", False, 0.1, 0)  # aux_voltage
    rule = RuleRef(1, 1, "aux_voltage", layout, 1.0)
    
    # 14.5V (정상, raw=145)
    samples = {(0x7E4, 0x0101): [(1000.0, bytes([0] * 29 + [145]))]}
    result = decode_signals(samples, [rule])
    assert "aux_voltage" in result
    assert result["aux_voltage"]["value"] == 14.5
    
    # 28.18V (비정상, raw=281은 28.1V) → 범위(6-16V) 밖이라 필터링됨
    # 실제로는 255를 초과할 수 없으므로 20V (raw=200)로 테스트
    samples = {(0x7E4, 0x0101): [(1000.0, bytes([0] * 29 + [200]))]}
    result = decode_signals(samples, [rule])
    assert "aux_voltage" not in result  # 20V는 범위(6-16V) 밖


def test_invalid_percentage_filtered():
    """839.9% 같은 비정상 퍼센트 값 차단."""
    # SOH는 0~110% 범위
    
    layout = Layout(0x7E4, 0x0105, 25, 2, "big", False, 0.1, 0)  # soh
    rule = RuleRef(1, 1, "soh", layout, 1.0)
    
    # 95.3% (정상, raw=953)
    samples = {(0x7E4, 0x0105): [(1000.0, bytes([0] * 25 + [0x03, 0xB9]))]}  # 953 → 95.3%
    result = decode_signals(samples, [rule])
    assert "soh" in result
    assert result["soh"]["value"] == 95.3
    
    # 200% (비정상, raw=2000) → 범위(0-110%) 밖이라 필터링됨
    samples = {(0x7E4, 0x0105): [(1000.0, bytes([0] * 25 + [0x07, 0xD0]))]}  # 2000 → 200%
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
    # cell_1은 signals.py에 정의되지 않았으므로 범위 체크 안 됨
    # 대신 max_cell_v를 테스트
    from app.modules.canlab.engine.signals import BY_KEY
    
    # max_cell_v 신호 존재 확인
    assert "max_cell_v" in BY_KEY
    signal = BY_KEY["max_cell_v"]
    assert signal.minimum == 1.5
    assert signal.maximum == 4.6
    
    # Layout과 RuleRef로 테스트
    layout = Layout(0x7E4, 0x0101, 23, 1, "big", False, 0.02, 0)
    rule = RuleRef(1, 1, "max_cell_v", layout, 1.0)
    
    # 3.54V (정상, raw=177)
    samples = {(0x7E4, 0x0101): [(1000.0, bytes([0] * 23 + [177]))]}
    result = decode_signals(samples, [rule])
    assert "max_cell_v" in result
    assert abs(result["max_cell_v"]["value"] - 3.54) < 0.01
    
    # 0.5V (비정상, raw=25) → 범위(1.5-4.6V) 밖이라 필터링
    samples = {(0x7E4, 0x0101): [(1000.0, bytes([0] * 23 + [25]))]}
    result = decode_signals(samples, [rule])
    assert "max_cell_v" not in result
    
    # 5.0V (비정상, raw=250) → 범위 밖이라 필터링
    samples = {(0x7E4, 0x0101): [(1000.0, bytes([0] * 23 + [250]))]}
    result = decode_signals(samples, [rule])
    assert "max_cell_v" not in result
