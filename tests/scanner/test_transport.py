"""전송 계층 테스트."""

import os
import pytest
import socket
import threading
import time

from app.modules.scanner.transport import (
    TransportAdapter,
    TransportError,
    CanAdapter,
    DoIPAdapter,
    J2534Adapter,
)


# CAN 어댑터 테스트


def test_can_adapter_validates_connection_method():
    adapter = CanAdapter()

    # 올바른 방식
    adapter.connect({"method": "ble", "bus": "can11"})
    assert adapter.is_connected()

    # 잘못된 방식
    with pytest.raises(TransportError, match="지원하지 않는"):
        adapter.connect({"method": "invalid"})


def test_can_adapter_requires_client_side_connection():
    adapter = CanAdapter()
    adapter.connect({"method": "ble"})

    # 서버에서 명령을 보낼 수 없음
    with pytest.raises(TransportError, match="클라이언트"):
        adapter.send_command("0100")


def test_can_adapter_test_connection():
    adapter = CanAdapter()

    # 연결 전
    result = adapter.test_connection()
    assert not result["success"]

    # 연결 후
    adapter.connect({"method": "ble", "bus": "can11"})
    result = adapter.test_connection()
    assert result["success"]


# DoIP 어댑터 테스트


def test_doip_adapter_blocks_on_vercel(monkeypatch):
    """Vercel 환경에서는 DoIP 연결을 차단합니다."""
    monkeypatch.setenv("VERCEL", "1")

    adapter = DoIPAdapter()
    with pytest.raises(TransportError, match="차량 이더넷"):
        adapter.connect({"host": "192.168.0.20", "port": 13400})


def test_doip_adapter_validates_host():
    adapter = DoIPAdapter()

    # 빈 호스트
    with pytest.raises(TransportError, match="주소"):
        adapter.connect({"host": "", "port": 13400})

    # 메타데이터 주소 차단
    with pytest.raises(TransportError, match="주소"):
        adapter.connect({"host": "169.254.169.254", "port": 13400})


def test_doip_adapter_validates_port():
    adapter = DoIPAdapter()

    # 잘못된 포트
    with pytest.raises(TransportError, match="포트"):
        adapter.connect({"host": "192.168.0.20", "port": 99999})


def test_doip_adapter_with_mock_gateway(mock_doip_gateway):
    """모의 DoIP 게이트웨이로 라우팅 활성화와 진단 응답을 검증합니다."""
    adapter = DoIPAdapter()
    adapter.connect({"host": "127.0.0.1", "port": mock_doip_gateway.port, "timeout": 0.5})
    try:
        assert adapter.is_connected()
        info = adapter.get_protocol_info()
        assert info["name"] == "DoIP (ISO 13400)"
        assert info["bus"] == "can"

        result = adapter.send_command("0100", timeout_ms=500)
        assert result.error is None
        assert result.reply == "000010E0 06 41 00 BE 1F B8 13\r>"
        assert adapter.get_active_ecus() == [0x10E0]
    finally:
        adapter.disconnect()
    assert not adapter.is_connected()


def test_doip_routing_failure_raises(mock_doip_gateway):
    """라우팅 활성화가 거부되면 연결을 끊고 오류를 냅니다."""
    mock_doip_gateway.routing_code = 0x00
    adapter = DoIPAdapter()
    with pytest.raises(TransportError, match="라우팅 활성화 실패"):
        adapter.connect({"host": "127.0.0.1", "port": mock_doip_gateway.port, "timeout": 0.5})
    assert not adapter.is_connected()


# J2534 어댑터 테스트


def test_j2534_adapter_validates_bridge_url():
    adapter = J2534Adapter()

    # 빈 URL
    with pytest.raises(TransportError, match="URL"):
        adapter.connect({"bridge_url": ""})


@pytest.mark.parametrize("name, protocol_id", [("CAN", 1), ("KWP", 2), ("K-LINE", 3), ("J1850VPW", 4)])
def test_j2534_adapter_protocol_mapping(mock_j2534_bridge, name, protocol_id):
    """프로토콜 이름을 J2534 프로토콜 ID로 매핑해 채널을 엽니다."""
    adapter = J2534Adapter()
    adapter.connect({"bridge_url": mock_j2534_bridge.url, "protocol": name})
    try:
        assert list(mock_j2534_bridge.channels.values()) == [protocol_id]
    finally:
        adapter.disconnect()
    assert mock_j2534_bridge.channels == {}


def test_j2534_adapter_test_connection_without_connection():
    adapter = J2534Adapter()

    result = adapter.test_connection()
    assert not result["success"]


# 추상 클래스 테스트


def test_transport_adapter_is_abstract():
    """TransportAdapter는 직접 인스턴스화할 수 없습니다."""
    with pytest.raises(TypeError):
        TransportAdapter()


# 안전 정책 테스트 - DoIP


def test_doip_blocks_blocked_services():
    """DoIP가 차단된 서비스를 보내지 못합니다."""
    # 차단된 명령 목록
    blocked_commands = [
        "10 01",  # 진단 세션 변경
        "27 01",  # 보안 접근
        "2E F190 41424344",  # 데이터 쓰기
        "31 01 FF00",  # 루틴 제어
    ]

    adapter = DoIPAdapter()
    # 연결되지 않은 상태에서도 검증 가능한 명령 형식 확인

    # 실제로는 ethernet.py의 _blocked 함수가 plan.py에서 사용됨
    from app.modules.scanner.ethernet import _blocked

    for command in blocked_commands:
        assert _blocked(command.replace(" ", "")), f"명령 {command}이(가) 차단되지 않았습니다"

    # 허용된 명령
    allowed_commands = ["0100", "03", "22F190", "1902FF"]
    for command in allowed_commands:
        assert not _blocked(command), f"명령 {command}이(가) 잘못 차단되었습니다"


def test_doip_blocks_dtc_clear():
    """DoIP가 DTC 지우기를 차단합니다."""
    from app.modules.scanner.ethernet import _blocked

    # OBD DTC 지우기
    assert _blocked("04")

    # UDS DTC 지우기
    assert _blocked("14FFFFFF")
    assert _blocked("14")


# 안전 정책 테스트 - J2534


def test_j2534_parse_blocks_blocked_services():
    """J2534 로그 파싱이 차단된 서비스를 거부합니다."""
    from app.modules.scanner.ethernet import parse_j2534
    from app.core.errors import ServiceError

    # 쓰기 명령
    with pytest.raises(ServiceError, match="쓰기"):
        parse_j2534("7E0 2EF190414243 62F190414243")

    # 세션 변경
    with pytest.raises(ServiceError, match="세션|쓰기"):
        parse_j2534("7E0 1001 5001")

    # 보안 접근
    with pytest.raises(ServiceError, match="세션|보안|쓰기"):
        parse_j2534("7E0 2701 6701")


# SSRF 방지 테스트


def test_doip_blocks_metadata_address():
    """DoIP가 메타데이터 주소를 차단합니다."""
    adapter = DoIPAdapter()

    with pytest.raises(TransportError, match="주소"):
        adapter.connect({"host": "169.254.169.254", "port": 13400})


def test_doip_blocks_on_vercel_deployment(monkeypatch):
    """Vercel 환경에서 DoIP를 차단합니다."""
    monkeypatch.setenv("VERCEL", "1")

    adapter = DoIPAdapter()
    with pytest.raises(TransportError, match="차량 이더넷"):
        adapter.connect({"host": "192.168.0.1", "port": 13400})


def test_ethernet_vehicle_network_blocked_check(monkeypatch):
    """ethernet.vehicle_network_blocked가 Vercel을 감지합니다."""
    from app.modules.scanner.ethernet import vehicle_network_blocked

    # 일반 환경
    assert not vehicle_network_blocked()

    # Vercel 환경
    monkeypatch.setenv("VERCEL", "1")
    assert vehicle_network_blocked()


# 통합 테스트 (fixture가 모의 서버를 임시 포트로 띄운다)


@pytest.mark.integration
def test_doip_adapter_with_real_mock_gateway(mock_doip_gateway):
    """실제 모의 DoIP 게이트웨이 서버와 통신 (통합 테스트)."""
    adapter = DoIPAdapter()
    adapter.connect({"host": "localhost", "port": mock_doip_gateway.port, "timeout": 2.0})

    # 명령 전송
    result = adapter.send_command("0100")
    assert result.reply is not None
    assert "41 00" in result.reply

    adapter.disconnect()


@pytest.mark.integration
def test_j2534_adapter_with_real_mock_bridge(mock_j2534_bridge):
    """실제 모의 J2534 브리지 서버와 통신 (통합 테스트)."""
    adapter = J2534Adapter()
    adapter.connect({
        "bridge_url": mock_j2534_bridge.url,
        "protocol": "CAN",
        "baudrate": 500000,
    })

    # 명령 전송
    result = adapter.send_command("0100")
    assert result.reply is not None
    assert "41 00" in result.reply

    adapter.disconnect()
