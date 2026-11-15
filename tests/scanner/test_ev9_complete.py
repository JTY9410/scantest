"""Test EV9 complete fixes (#4-#13)."""

import pytest


def test_suppress_pos_rsp_3e_80():
    """#5: 3E 80 (suppressPosRsp) 무응답은 정상."""
    from app.modules.scanner.obd import evaluate
    
    # 3E 80 = TesterPresent with suppressPosRsp
    outcome = evaluate("3E80", None, "CAN", None)
    
    assert outcome.status == "ok"
    assert "suppress" in outcome.message.lower()


def test_suppress_pos_rsp_other_service():
    """#5: 다른 서비스는 무응답 시 timeout."""
    from app.modules.scanner.obd import evaluate
    
    # 22 F190 = ReadDataByIdentifier (no suppressPosRsp)
    outcome = evaluate("22F190", None, "CAN", None)
    
    assert outcome.status == "timeout"


def test_odometer_b002_exists():
    """#9: 주행거리 B002가 ODOMETER_DIDS에 존재."""
    from app.modules.scanner.obd import ODOMETER_DIDS
    
    assert "B002" in ODOMETER_DIDS


def test_module_temp_b17_b18_exists():
    """#11: 모듈 온도 B17/B18 정의 존재."""
    import json
    from pathlib import Path
    
    ref_path = Path(__file__).parent.parent.parent / "app/modules/canlab/engine/references.json"
    with open(ref_path) as f:
        data = json.load(f)
    
    hypotheses = data["hypotheses"]
    
    b17 = next((h for h in hypotheses if h["signal"] == "module_temp_b17"), None)
    assert b17 is not None
    assert b17["did"] == "0111"
    assert b17["start"] == 26
    
    b18 = next((h for h in hypotheses if h["signal"] == "module_temp_b18"), None)
    assert b18 is not None
    assert b18["did"] == "0111"
    assert b18["start"] == 27


def test_ev9_regression_complete():
    """EV9 완료 회귀 테스트 (가짜 값만)."""
    
    # Fake VIN
    vin = "ZZZ12345678901234"
    assert len(vin) == 17
    
    # suppressPosRsp 테스트
    from app.modules.scanner.obd import evaluate
    outcome_3e80 = evaluate("3E80", None, "CAN", None)
    assert outcome_3e80.status == "ok"
    
    # Module temp B17/B18 존재 확인
    import json
    from pathlib import Path
    ref_path = Path(__file__).parent.parent.parent / "app/modules/canlab/engine/references.json"
    with open(ref_path) as f:
        data = json.load(f)
    
    signals = [h["signal"] for h in data["hypotheses"]]
    assert "module_temp_b17" in signals
    assert "module_temp_b18" in signals
