"""EV9 주행거리 조회 테스트 (Issue #9)."""

import pytest
from app.modules.scanner.obd import maker_odometer


def test_b002_odometer_interpretation():
    """7C6 22 B002 응답을 km로 해석."""
    # OBDb Kia-EV9: bix 48, len 24
    # 실측 예상: 6바이트 데이터 [6:9] → 주행거리
    
    # 예시 1: 50,000 km (0x00C350)
    data = bytes([0x62, 0xB0, 0x02, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x35, 0x00])
    result = maker_odometer("B002", data[3:])  # DID 에코 다음부터
    assert result == 50000
    
    # 예시 2: 100,000 km (0x0186A0)
    data = bytes([0x62, 0xB0, 0x02, 0x00, 0x00, 0x00, 0x01, 0x86, 0xA0, 0x00])
    result = maker_odometer("B002", data[3:])
    assert result == 100000
    
    # 예시 3: 범위 밖 → None
    data = bytes([0x62, 0xB0, 0x02, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
    result = maker_odometer("B002", data[3:])
    assert result is None  # 2백만 km 초과


def test_egmp_platform_detection():
    """EV9가 egmp 플랫폼으로 감지되는지."""
    from app.modules.canlab.engine.bms import platform
    
    # 모델 힌트에 EV9 포함
    assert platform("EV9", None) == "egmp"
    assert platform("기아 EV9", None) == "egmp"
    assert platform("KIA EV9", None) == "egmp"
    
    # 셀 개수로도 감지 (192셀 = EGMP)
    assert platform(None, 192) == "egmp"
    assert platform(None, 180) == "egmp"


def test_odometer_in_scan_plan():
    """EV9 스캔 계획에 7C6 22 B002가 포함되는지."""
    from app.modules.scanner.plan import build_plan, CLUSTER_ODO_DIDS
    
    # B002가 CLUSTER_ODO_DIDS에 있어야 함
    assert "B002" in CLUSTER_ODO_DIDS
    
    # 현대·기아 차량 스캔 계획
    car = {"diag_company": "기아", "diag_model": "EV9", "diag_fuel": "전기"}
    plan = build_plan(car, expand=False)
    
    # 7C6 22 B002 단계가 있어야 함
    b002_steps = [s for s in plan["steps"] if s["header"] == "7C6" and "B002" in s["command"]]
    assert len(b002_steps) >= 1
    assert b002_steps[0]["command"] == "22B002"


def test_odometer_interpretation_in_result():
    """해석 결과에 주행거리가 포함되는지."""
    from app.modules.scanner.interpret import interpret
    
    # 가짜 스캔 응답
    steps = [
        {"id": 1, "group": "maker", "label": "계기판 주행거리", "header": "7C6",
         "command": "22B002", "reply": "7CE 10 0B 62 B0 02 00 00 00 00 0C 35 00",
         "t_ms": 1000, "bus": "can"}
    ]
    
    car = {"diag_company": "기아", "diag_model": "EV9"}
    result = interpret(steps, car=car)
    
    # values에 odometer가 있어야 함
    odometer_values = [v for v in result["values"] if v["key"] == "odometer"]
    assert len(odometer_values) == 1
    assert odometer_values[0]["value"] == 50000  # 0x00C350 = 50000 km
    assert odometer_values[0]["source"] == "7C6 22 B002"
