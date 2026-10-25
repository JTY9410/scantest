"""배포(Vercel) 환경에서는 서버 측 차량 전송(DoIP·J2534)을 막고, 주소 정책도 더 엄격하다.

스캔은 휴대폰(브라우저·앱)에서 하므로 운영 서버가 차량 망으로 나갈 일이 없다.
Mac 등 비-Vercel 환경에서는 LAN·루프백을 그대로 허용한다.
"""

import pytest

from app.modules.scanner.transport import DoIPAdapter, J2534Adapter, TransportError
from app.modules.scanner.transport.base import SERVER_TRANSPORT_BLOCKED, check_target_host
from tests.conftest import csrf_token


@pytest.fixture
def on_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")


def test_j2534_blocked_on_vercel(on_vercel):
    adapter = J2534Adapter()
    with pytest.raises(TransportError) as info:
        adapter.connect({"bridge_url": "http://8.8.8.8:5000"})
    assert info.value.message == SERVER_TRANSPORT_BLOCKED
    assert not adapter.is_connected()


def test_doip_blocked_on_vercel(on_vercel):
    with pytest.raises(TransportError, match="차량 이더넷"):
        DoIPAdapter().connect({"host": "8.8.8.8", "port": 13400})


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "10.0.0.5", "192.168.0.20", "172.16.1.1",
                                  "::1", "fc00::1", "169.254.169.254", "224.0.0.1", "0.0.0.0", "100.64.0.1"])
def test_vercel_blocks_non_public_addresses(on_vercel, host):
    with pytest.raises(TransportError, match="게이트웨이 주소"):
        check_target_host(host, 80)


def test_vercel_allows_public_literal_address(on_vercel):
    assert check_target_host("8.8.8.8", 80) == "8.8.8.8"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "10.0.0.5", "192.168.0.20"])
def test_non_vercel_keeps_lan_and_loopback(monkeypatch, host):
    monkeypatch.delenv("VERCEL", raising=False)
    assert check_target_host(host, 80) == host


@pytest.mark.parametrize("host", ["169.254.169.254", "224.0.0.1", "0.0.0.0", "fe80::1"])
def test_non_vercel_still_blocks_metadata_link_local_multicast(monkeypatch, host):
    monkeypatch.delenv("VERCEL", raising=False)
    with pytest.raises(TransportError):
        check_target_host(host, 80)


def test_non_vercel_j2534_connects_to_local_bridge(monkeypatch, mock_j2534_bridge):
    monkeypatch.delenv("VERCEL", raising=False)
    adapter = J2534Adapter()
    adapter.connect({"bridge_url": mock_j2534_bridge.url})
    try:
        assert adapter.is_connected()
    finally:
        adapter.disconnect()


@pytest.mark.parametrize("transport, config", [
    ("j2534_can", {"bridge_url": "http://127.0.0.1:5000"}),
    ("doip", {"host": "192.168.0.20", "port": 13400}),
])
def test_routes_block_server_transport_on_vercel(admin_client, monkeypatch, no_car_lookup, transport, config):
    token = {"X-CSRFToken": csrf_token(admin_client, "/admin/scan/")}
    monkeypatch.setenv("VERCEL", "1")
    response = admin_client.post("/admin/scan/test-transport", json={"transport": transport, "config": config},
                                 headers=token)
    assert response.status_code == 400
    message = response.get_json()["message"]
    assert message in (SERVER_TRANSPORT_BLOCKED,
                       "이 서버는 차량 이더넷에 연결할 수 없습니다. 차량과 같은 망의 로컬 서버에서 실행하세요.")
    assert "127.0.0.1" not in message and "192.168" not in message

    response = admin_client.post("/admin/scan/run-with-transport",
                                 json={"carNo": "12가3456", "transport": transport, "config": config}, headers=token)
    assert response.status_code == 400
    assert response.get_json()["message"] == message
