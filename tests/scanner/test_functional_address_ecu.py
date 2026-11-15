"""기능주소 응답 ECU 등록 테스트 (Issue #10)."""

import pytest
from app.modules.scanner.interpret import interpret


def test_functional_address_responses_registered():
    """7DF(기능주소)에 응답한 598, 59E, 788이 ECU로 등록되는지."""
    
    # 7DF 10 01 요청에 598, 59E, 788이 응답
    steps = [
        {"id": 1, "group": "uds", "label": "기능주소 테스트", "header": None,  # 7DF는 header=None
         "command": "1001", 
         "reply": "598: 41 01 00 00\n59E: 41 01 00 00\n788: 41 01 00 00",
         "t_ms": 1000, "bus": "can"}
    ]
    
    result = interpret(steps, car={})
    
    # ECU 목록 확인
    ecu_addresses = [ecu["address"] for ecu in result["ecus"]]
    assert "598" in ecu_addresses
    assert "59E" in ecu_addresses
    assert "788" in ecu_addresses
    
    # 각 ECU의 요청 주소 확인
    for ecu in result["ecus"]:
        if ecu["address"] in ("598", "59E", "788"):
            # 기능주소 응답의 경우 request는 응답-8 또는 None
            assert ecu["request"] in (None, f"{int(ecu['address'], 16) - 8:03X}")


def test_functional_address_vs_physical():
    """기능주소와 물리주소 응답 구분."""
    
    steps = [
        # 기능주소 (7DF) → 여러 ECU 응답
        {"id": 1, "group": "uds", "label": "기능주소", "header": None,
         "command": "1001", 
         "reply": "7E8: 41 01 00 00\n7EC: 41 01 00 00",
         "t_ms": 1000, "bus": "can"},
        
        # 물리주소 (7E0) → 단일 ECU 응답
        {"id": 2, "group": "uds", "label": "물리주소", "header": "7E0",
         "command": "22F190", 
         "reply": "7E8 10 13 62 F1 90 5A 5A 5A",
         "t_ms": 2000, "bus": "can"},
    ]
    
    result = interpret(steps, car={})
    
    # 7E8과 7EC 모두 등록되어야 함
    ecu_addresses = [ecu["address"] for ecu in result["ecus"]]
    assert "7E8" in ecu_addresses
    assert "7EC" in ecu_addresses
    
    # 7E8은 물리주소(7E0)에 대한 응답도 있음
    ecu_7e8 = next(e for e in result["ecus"] if e["address"] == "7E8")
    assert "01" in ecu_7e8["services"]  # 기능주소 요청
    assert "22" in ecu_7e8["services"]  # 물리주소 요청


def test_broadcast_header_none():
    """header=None이 브로드캐스트(7DF)로 처리되는지."""
    from app.modules.scanner.interpret import BROADCAST
    
    assert BROADCAST["can11"] == "7DF"
    assert BROADCAST["can29"] == "18DB33F1"
    
    # interpret에서 header=None → BROADCAST 사용
    steps = [
        {"id": 1, "group": "pid", "label": "지원 항목", "header": None,
         "command": "0100", "reply": "7E8: 41 00 BE 1F B8 13",
         "t_ms": 1000, "bus": "can"}
    ]
    
    result = interpret(steps, car={})
    
    # 7E8이 등록되어야 함
    ecu_addresses = [ecu["address"] for ecu in result["ecus"]]
    assert "7E8" in ecu_addresses
