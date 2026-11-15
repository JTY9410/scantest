"""기능주소 응답 ECU 등록 테스트 (Issue #10)."""

import pytest


def test_broadcast_constant():
    """브로드캐스트 주소 상수가 정의되어 있는지."""
    from app.modules.scanner.interpret import BROADCAST
    
    # CAN 11비트: 7DF
    assert BROADCAST["can11"] == "7DF"
    # CAN 29비트: 18DB33F1
    assert BROADCAST["can29"] == "18DB33F1"


def test_ecu_address_formatting():
    """ECU 주소 포맷팅 함수."""
    from app.modules.scanner.interpret import _ecu_address
    
    # 11비트 주소
    assert _ecu_address(0x7E8) == "7E8"
    assert _ecu_address(0x598) == "598"
    assert _ecu_address(0x59E) == "59E"
    assert _ecu_address(0x788) == "788"
    
    # 29비트 주소
    assert _ecu_address(0x18DAF110) == "18DAF110"


def test_request_address_calculation():
    """응답 주소에서 요청 주소 계산."""
    from app.modules.scanner.interpret import _request_of
    
    # 11비트: 응답 - 8 = 요청
    assert _request_of("7E8") == "7E0"
    assert _request_of("598") == "590"
    assert _request_of("59E") == "596"
    assert _request_of("788") == "780"
    
    # 29비트: 18DA F1xx → 18DA xxF1
    assert _request_of("18DAF110") == "18DA10F1"
