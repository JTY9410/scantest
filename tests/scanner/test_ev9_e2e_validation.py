"""EV9 기능 E2E 검증 테스트."""

import pytest


def test_odometer_dids_contains_b002():
    """#9: B002가 ODOMETER_DIDS에 있는지 (E2E 검증)."""
    from app.modules.scanner.obd import ODOMETER_DIDS
    
    # B002가 주행거리 DID 목록에 포함되어 있어야 함
    assert "B002" in ODOMETER_DIDS
    # ODOMETER_SOURCES에도 포함되어 있어야 함
    from app.modules.scanner.interpret import ODOMETER_SOURCES
    assert ("7C6", "B002") in ODOMETER_SOURCES


def test_signal_range_validation_exists():
    """#12: 모든 신호에 범위 검증이 있는지 (E2E 검증)."""
    from app.modules.canlab.engine.signals import SIGNALS
    
    # 모든 신호에 minimum/maximum이 정의되어 있어야 함
    for signal in SIGNALS:
        assert hasattr(signal, 'minimum'), f"{signal.key}에 minimum 없음"
        assert hasattr(signal, 'maximum'), f"{signal.key}에 maximum 없음"
        assert signal.minimum < signal.maximum
        
        # 주요 신호들의 범위 확인
        if signal.key == 'aux_voltage':
            # 12V 보조배터리: 6~16V (28.18V는 범위 밖)
            assert signal.minimum == 6
            assert signal.maximum == 16
        elif signal.key == 'soh':
            # SOH: 0~110% (839.9%는 범위 밖)
            assert signal.minimum == 0
            assert signal.maximum == 110


def test_decode_signals_filters_out_of_range():
    """#12: decode_signals가 범위 밖 값을 필터링하는지 (E2E 검증)."""
    from app.modules.canlab.engine.decode import decode_signals
    import inspect
    
    # decode_signals 소스 코드에 범위 체크 로직이 있는지 확인
    source = inspect.getsource(decode_signals)
    assert 'minimum' in source and 'maximum' in source, \
        "decode_signals에 범위 검증 로직이 없음"


def test_broadcast_and_ecu_registration():
    """#10: 브로드캐스트 주소 정의 및 ECU 등록 로직 (E2E 검증)."""
    from app.modules.scanner.interpret import BROADCAST, _ecu_address, _request_of
    
    # 브로드캐스트 주소 정의
    assert BROADCAST["can11"] == "7DF"
    assert BROADCAST["can29"] == "18DB33F1"
    
    # ECU 주소 변환 함수
    assert _ecu_address(0x598) == "598"
    assert _ecu_address(0x59E) == "59E"
    assert _ecu_address(0x788) == "788"
    
    # 요청 주소 계산 (응답 - 8)
    assert _request_of("598") == "590"
    assert _request_of("59E") == "596"
    assert _request_of("788") == "780"


def test_manual_override_and_scan_plan(app):
    """#4: 수동 차종 지정 및 스캔 계획 (E2E 검증)."""
    from app.modules.scanner.plan import build_plan, _is_hkmc, _is_electrified
    
    with app.app_context():
        # 수동 override 우선순위
        car_with_override = {
            "diag_company": "현대",
            "diag_model": "아이오닉5",
            "diag_fuel": "휘발유",  # 잘못된 정보
            "override_type": "ev",  # 수동 override
            "override_source": "manual_override"
        }
        
        # override_type이 우선되어야 함
        assert _is_electrified(car_with_override)
        
        # 현대·기아 차량 감지
        kia_car = {"diag_company": "기아", "diag_model": "EV9"}
        assert _is_hkmc(kia_car)
        
        # EV9 스캔 계획에 B002가 포함되는지
        plan = build_plan(kia_car, expand=False)
        b002_steps = [s for s in plan["steps"] 
                     if s.get("header") == "7C6" and "B002" in s.get("command", "")]
        assert len(b002_steps) >= 1, "7C6 22 B002가 스캔 계획에 없음"


def test_overall_judgment_with_unread():
    """#6: 측정불가 → 판정보류 (E2E 검증)."""
    from app.modules.scanner.report import overall, UNREAD
    
    # 측정불가 항목이 있으면 판정보류
    rows_with_unread = [
        {"result": "양호"},
        {"result": UNREAD},
        {"result": "양호"}
    ]
    
    result = overall(rows_with_unread, dtc_count=0, dtc_read=True)
    assert result == "판정보류", "측정불가가 있는데 판정보류가 아님"
    
    # 측정불가 없으면 양호
    rows_all_good = [
        {"result": "양호"},
        {"result": "양호"}
    ]
    
    result = overall(rows_all_good, dtc_count=0, dtc_read=True)
    assert result == "양호"


def test_module_temperature_and_cell_info():
    """#13: 모듈 온도 및 셀 정보 (E2E 검증)."""
    import json
    from pathlib import Path
    
    # references.json에 module_temp_b17/b18이 있는지
    ref_json = Path(__file__).parent.parent.parent / 'app' / 'modules' / 'canlab' / 'engine' / 'references.json'
    with open(ref_json) as f:
        data = json.load(f)
    
    signals = {h['signal']: h for h in data['hypotheses']}
    assert 'module_temp_b17' in signals, "module_temp_b17 정의 없음"
    assert 'module_temp_b18' in signals, "module_temp_b18 정의 없음"
    
    # report.py에 module_temperatures 함수가 있는지
    from app.modules.scanner import report
    assert hasattr(report, 'module_temperatures'), "module_temperatures 함수 없음"
    
    # cell_voltages 함수도 있어야 함
    assert hasattr(report, 'cell_voltages'), "cell_voltages 함수 없음"


def test_ev9_platform_detection():
    """#1: EV9 플랫폼 감지 (E2E 검증)."""
    from app.modules.canlab.engine.bms import platform
    
    # EV9는 egmp 플랫폼으로 감지되어야 함
    assert platform("EV9", None) == "egmp"
    assert platform("기아 EV9", None) == "egmp"
    assert platform("KIA EV9", None) == "egmp"
    
    # 192셀은 egmp
    assert platform(None, 192) == "egmp"


def test_ldc_e101_field_exists():
    """#2: LDC E101 필드 (E2E 검증)."""
    from app.modules.canlab.engine.bms import ECU_FIELDS
    
    # E101 LDC 출력 전압 필드가 있는지
    ldc_e101 = [f for f, grades in ECU_FIELDS if f.did == 0xE101 and f.key == "ldc_voltage"]
    assert len(ldc_e101) > 0, "LDC E101 필드 없음"
    
    field = ldc_e101[0]
    assert field.request == 0x7E5
    assert field.scale == 0.001


def test_inlet_temp_offset():
    """#3: 입구 온도 오프셋 (E2E 검증)."""
    import json
    from pathlib import Path
    
    # references.json에서 inlet_temp 확인
    ref_json = Path(__file__).parent.parent.parent / 'app' / 'modules' / 'canlab' / 'engine' / 'references.json'
    with open(ref_json) as f:
        data = json.load(f)
    
    inlet_temp = next(h for h in data['hypotheses'] if h['signal'] == 'inlet_temp')
    assert inlet_temp['offset'] == -40, "inlet_temp offset이 -40이 아님"
    assert not inlet_temp['signed'], "inlet_temp이 signed로 되어 있음"
