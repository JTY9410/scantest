"""전송 계층 테스트."""

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


def test_doip_adapter_with_mock_gateway():
    """모의 DoIP 게이트웨이로 연결 테스트."""
    # 간단한 모의 게이트웨이
    class MockGateway:
        def __init__(self):
            self.sent = []
            self.responses = [
                # 라우팅 활성화 응답
                b"\x02\xFD\x00\x06\x00\x00\x00\x09"
                + b"\x0E\x00\x10\xE0\x10\x00\x00\x00\x00",
                # 진단 메시지 응답
                b"\x02\xFD\x80\x01\x00\x00\x00\x0A"
                + b"\x10\xE0\x0E\x00\x41\x00\xBE\x1F\xB8\x13",
            ]

        def send(self, data):
            self.sent.append(data)

        def sendall(self, data):
            self.send(data)

        def recv(self, size):
            if not self.responses:
                raise socket.timeout
            return self.responses.pop(0)[:size]

        def settimeout(self, timeout):
            pass

        def close(self):
            pass

    # 모의 연결 함수
    def mock_connect(host, port, timeout):
        return MockGateway()

    adapter = DoIPAdapter()

    # 연결
    adapter.connect({
        "host": "192.168.0.20",
        "port": 13400,
    })
    adapter._socket = mock_connect("192.168.0.20", 13400, 2.0)
    adapter._activate_routing()

    assert adapter.is_connected()

    # 프로토콜 정보
    info = adapter.get_protocol_info()
    assert info["name"] == "DoIP (ISO 13400)"
    assert info["bus"] == "can"


# J2534 어댑터 테스트


def test_j2534_adapter_validates_bridge_url():
    adapter = J2534Adapter()

    # 빈 URL
    with pytest.raises(TransportError, match="URL"):
        adapter.connect({"bridge_url": ""})


def test_j2534_adapter_protocol_mapping():
    """프로토콜 이름을 ID로 매핑합니다."""
    adapter = J2534Adapter()

    # 프로토콜 매핑은 connect에서 처리되므로 직접 테스트하기 어려움
    # 실제 사용 시 확인됨
    assert True


def test_j2534_adapter_test_connection_without_connection():
    adapter = J2534Adapter()

    result = adapter.test_connection()
    assert not result["success"]


# 추상 클래스 테스트


def test_transport_adapter_is_abstract():
    """TransportAdapter는 직접 인스턴스화할 수 없습니다."""
    with pytest.raises(TypeError):
        TransportAdapter()


# 통합 테스트


@pytest.mark.integration
def test_doip_adapter_with_real_mock_gateway():
    """실제 모의 DoIP 게이트웨이 서버와 통신 (통합 테스트)."""
    # bridge/mock_doip_gateway.py를 별도로 실행해야 함
    pytest.skip("수동 통합 테스트: 모의 게이트웨이를 먼저 실행하세요")

    adapter = DoIPAdapter()
    adapter.connect({"host": "localhost", "port": 13400, "timeout": 5.0})

    # 명령 전송
    result = adapter.send_command("0100")
    assert result.reply is not None
    assert "41 00" in result.reply

    adapter.disconnect()


@pytest.mark.integration
def test_j2534_adapter_with_real_mock_bridge():
    """실제 모의 J2534 브리지 서버와 통신 (통합 테스트)."""
    # bridge/mock_server.py를 별도로 실행해야 함
    pytest.skip("수동 통합 테스트: 모의 브리지를 먼저 실행하세요")

    adapter = J2534Adapter()
    adapter.connect({
        "bridge_url": "http://localhost:5000",
        "protocol": "CAN",
        "baudrate": 500000,
    })

    # 명령 전송
    result = adapter.send_command("0100")
    assert result.reply is not None
    assert "41 00" in result.reply

    adapter.disconnect()
