"""통합 테스트: mock 서버로 전체 스캔 흐름 검증.

DoIP mock 게이트웨이와 J2534 mock 브리지를 사용하여
전송 계층 → 스캔 실행 → 해석 → 리포트까지 전체 흐름을 테스트합니다.
"""

import pytest
import threading
import time
import sys
import os

# 통합 테스트는 실제 서버 실행이 필요하므로 스킵
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def mock_doip_gateway():
    """DoIP mock 게이트웨이를 백그라운드에서 실행합니다."""
    # mock 서버 import
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bridge"))
    from bridge.mock_doip_gateway import MockDoIPGateway

    gateway = MockDoIPGateway(host="127.0.0.1", port=13401)  # 기본 포트 피하기
    gateway.start()

    yield gateway

    gateway.stop()


@pytest.fixture(scope="module")
def mock_j2534_bridge():
    """J2534 mock 브리지를 백그라운드에서 실행합니다."""
    pytest.skip("J2534 mock 브리지는 FastAPI 서버이므로 pytest fixture로 실행 불가")
    # 수동으로 bridge/mock_server.py를 실행해야 함
    yield


def test_doip_full_scan_flow(mock_doip_gateway):
    """DoIP로 전체 스캔 흐름을 테스트합니다."""
    pytest.skip("Mock 게이트웨이 연결 안정성 확보 후 활성화")

    from app.modules.scanner.transport import DoIPAdapter

    adapter = DoIPAdapter()

    # 연결
    adapter.connect({"host": "127.0.0.1", "port": 13401, "timeout": 5.0})

    try:
        # 기본 명령들 실행
        commands = [
            ("0100", "PID 지원"),
            ("0101", "MIL 상태"),
            ("03", "DTC"),
        ]

        for command, label in commands:
            result = adapter.send_command(command, timeout_ms=2000)
            assert result.reply is not None, f"{label} 명령이 응답을 받지 못했습니다"
            assert result.error is None, f"{label} 명령이 오류를 반환했습니다: {result.error}"

        # 프로토콜 정보
        info = adapter.get_protocol_info()
        assert info["name"] == "DoIP (ISO 13400)"

    finally:
        adapter.disconnect()


def test_transport_layer_blocks_unsafe_commands():
    """전송 계층이 안전하지 않은 명령을 차단합니다."""
    from app.modules.scanner.ethernet import _blocked

    # 차단되어야 하는 명령
    blocked = [
        "10",  # 진단 세션
        "1001",  # 진단 세션 변경
        "27",  # 보안 접근
        "2701",
        "2E",  # 데이터 쓰기
        "2EF190414243",
        "31",  # 루틴
        "3101FF00",
        "04",  # OBD DTC 지우기
        "14",  # UDS DTC 지우기
        "14FFFFFF",
    ]

    for cmd in blocked:
        assert _blocked(cmd), f"명령 {cmd}이(가) 차단되지 않았습니다"

    # 허용되어야 하는 명령
    allowed = [
        "0100", "0101", "010C", "010D",  # OBD 모드 01
        "03", "07", "0A",  # DTC 읽기
        "22F190", "22F187", "22F188",  # UDS 읽기
        "1902FF", "190209",  # UDS DTC 상태
    ]

    for cmd in allowed:
        assert not _blocked(cmd), f"명령 {cmd}이(가) 잘못 차단되었습니다"


def test_vercel_environment_blocks_vehicle_network(monkeypatch):
    """Vercel 환경에서 차량 네트워크 접근을 차단합니다."""
    from app.modules.scanner.ethernet import vehicle_network_blocked
    from app.modules.scanner.transport import DoIPAdapter

    # 일반 환경: 허용
    assert not vehicle_network_blocked()

    # Vercel 환경: 차단
    monkeypatch.setenv("VERCEL", "1")
    assert vehicle_network_blocked()

    # DoIP 어댑터도 차단
    adapter = DoIPAdapter()
    with pytest.raises(Exception, match="차량 이더넷"):
        adapter.connect({"host": "192.168.0.1", "port": 13400})


def test_j2534_parse_validates_commands():
    """J2534 로그 파싱이 명령을 검증합니다."""
    from app.modules.scanner.ethernet import parse_j2534
    from app.core.errors import ServiceError

    # 정상 명령
    steps = parse_j2534("""
E400 0100 41 00 BE 1F B8 13
7E8 0101 41 01 00 07 65 04
7E8 03 43 01 03 04 5B C2
""")
    assert len(steps) == 3
    assert steps[0]["command"] == "0100"
    assert steps[1]["header"] == "000007E8"
    assert steps[2]["command"] == "03"

    # 차단된 명령 (쓰기)
    with pytest.raises(ServiceError, match="쓰기|세션|보안"):
        parse_j2534("7E0 2EF190414243 62F190414243")

    # 빈 입력
    with pytest.raises(ServiceError, match="단계 기록"):
        parse_j2534("")

    # 잘못된 형식
    with pytest.raises(ServiceError, match="주소|명령|응답"):
        parse_j2534("invalid line")


if __name__ == "__main__":
    # 수동 실행용
    pytest.main([__file__, "-v", "-s"])
