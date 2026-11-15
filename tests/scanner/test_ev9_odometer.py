"""EV9 주행거리 조회 테스트 (Issue #9)."""

import pytest
from app.modules.scanner.obd import maker_odometer


def test_b002_odometer_interpretation():
    """7C6 22 B002 응답을 km로 해석."""
    # OBDb Kia-EV9: bix 48, len 24
    # maker_odometer는 data[6:9]를 읽음 (62 B0 02 제외 후 6바이트 건너뛰고 3바이트)
    
    # 예시 1: 50,000 km (0x00C350)
    # 62 B0 02 [00 00 00 00 00 00] [00 C3 50] ...
    data = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xC3, 0x50])
    result = maker_odometer("B002", data)
    assert result == 50000
    
    # 예시 2: 100,000 km (0x0186A0)
    data = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x86, 0xA0])
    result = maker_odometer("B002", data)
    assert result == 100000
    
    # 예시 3: 범위 밖 (0xFFFFFF = 16777215 km) → divisor 적용 후에도 2백만 초과
    # 실제로는 _tail 로직으로 끝 2-3바이트를 다시 시도
    # 0xFF 0xFF는 65535, 범위 내라서 통과함
    # 2백만 초과를 테스트하려면 더 큰 값 필요 (패스)


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


def test_odometer_in_scan_plan(app):
    """EV9 스캔 계획에 7C6 22 B002가 포함되는지."""
    from app.modules.scanner.plan import build_plan, CLUSTER_ODO_DIDS
    
    with app.app_context():
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
    """해석 결과에 주행거리가 포함되는지 (간단한 단위 테스트)."""
    from app.modules.scanner.interpret import ODOMETER_SOURCES
    from app.modules.scanner.obd import maker_odometer
    
    # ODOMETER_SOURCES에 7C6 B002가 있어야 함
    assert ("7C6", "B002") in ODOMETER_SOURCES
    
    # 실제 해석 로직 확인
    data = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xC3, 0x50])
    result = maker_odometer("B002", data)
    assert result == 50000
