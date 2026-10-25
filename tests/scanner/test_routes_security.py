"""전송 계층 라우트의 보안·입력 검증 테스트 (83f7e78에서 삭제된 테스트 복구, 기대값은 정확한 단일 상태 코드).

모든 POST는 CSRF 토큰을 함께 보낸다. 토큰이 없으면 CSRF 400이 먼저 나서
권한·입력 검증을 실제로 시험하지 못하기 때문이다.
"""

import pytest

from tests.conftest import csrf_token

TEST_URL = "/admin/scan/test-transport"
RUN_URL = "/admin/scan/run-with-transport"
DOIP = {"transport": "doip", "config": {"host": "127.0.0.1", "port": 13400}}
RUN = {"carNo": "12가3456", **DOIP}


def _token(client, url: str = "/admin/scan/") -> dict:
    return {"X-CSRFToken": csrf_token(client, url)}


def _post(client, url: str, body, *, token_url: str = "/admin/scan/"):
    return client.post(url, json=body, headers=_token(client, token_url))


@pytest.mark.parametrize("url, body", [(TEST_URL, DOIP), (RUN_URL, RUN)])
def test_transport_routes_require_login(client, url, body) -> None:
    response = client.post(url, json=body, headers=_token(client, "/admin/login"))
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


@pytest.mark.parametrize("url, body", [(TEST_URL, DOIP), (RUN_URL, RUN)])
def test_transport_routes_reject_non_admin(client, make_user, url, body) -> None:
    """관리자가 아닌 계정은 관리자 세션으로 인정되지 않아(load_user) 로그인 화면으로 보낸다."""
    user_id = make_user("tester1", type="tester")
    token = _token(client, "/admin/login")
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
    response = client.post(url, json=body, headers=token)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


@pytest.mark.parametrize("url, body", [(TEST_URL, DOIP), (RUN_URL, RUN)])
def test_transport_routes_require_csrf(admin_client, url, body) -> None:
    response = admin_client.post(url, json=body)
    assert response.status_code == 400


def test_test_transport_validates_input(admin_client) -> None:
    cases = [
        ({"config": {"host": "127.0.0.1"}}, "전송 방식을 선택하세요."),
        ({"transport": "invalid", "config": {}}, "서버 측 테스트를 지원하지 않는 방식입니다."),
        ({"transport": "ble", "config": {}}, "서버 측 테스트를 지원하지 않는 방식입니다."),
        ({"transport": "doip", "config": "127.0.0.1"}, "연결 설정을 확인하세요."),
        ({"transport": "doip", "config": {"host": "127.0.0.1", "port": "13400"}}, "포트 번호를 확인하세요."),
        ({"transport": "doip", "config": {"host": "127.0.0.1", "port": True}}, "포트 번호를 확인하세요."),
        ({"transport": "j2534_can", "config": {"bridge_url": "ftp://127.0.0.1/x"}}, "J2534 브리지 URL을 확인하세요."),
    ]
    for body, message in cases:
        response = _post(admin_client, TEST_URL, body)
        assert response.status_code == 400, body
        assert response.get_json()["message"] == message, body


def test_run_with_transport_validates_input(admin_client, no_car_lookup) -> None:
    cases = [
        ({"transport": "doip", "config": {"host": "127.0.0.1"}}, "차량번호를 입력해주세요."),
        ({"carNo": "12가3456", "config": {}}, "전송 방식을 선택하세요."),
        ({"carNo": "12가3456", "transport": "invalid"}, "지원하지 않는 전송 방식입니다."),
        ({"carNo": "12가3456", "transport": "doip", "config": []}, "연결 설정을 확인하세요."),
        ({"carNo": "12가3456", "transport": "doip", "config": {}}, "DoIP 게이트웨이 주소를 입력하세요."),
    ]
    for body, message in cases:
        response = _post(admin_client, RUN_URL, body)
        assert response.status_code == 400, body
        assert response.get_json()["message"] == message, body


@pytest.mark.parametrize("transport", ["j2534_kline", "j2534_j1850"])
def test_unverified_transports_are_rejected(admin_client, no_car_lookup, transport) -> None:
    body = {"transport": transport, "config": {"bridge_url": "http://127.0.0.1:1"}}
    response = _post(admin_client, TEST_URL, body)
    assert response.status_code == 400
    assert "검증되지 않아" in response.get_json()["message"]

    response = _post(admin_client, RUN_URL, {"carNo": "12가3456", **body})
    assert response.status_code == 400
    assert "검증되지 않았습니다" in response.get_json()["message"]


@pytest.mark.parametrize("host", [
    "169.254.169.254", "169.254.1.1", "metadata.google.internal", "0.0.0.0", "224.0.0.1",
    "fe80::1", "::ffff:169.254.169.254", "bad host!",
])
def test_doip_blocks_ssrf_targets(admin_client, host) -> None:
    response = _post(admin_client, TEST_URL, {"transport": "doip", "config": {"host": host, "port": 13400}})
    assert response.status_code == 400
    assert response.get_json()["message"] == "게이트웨이 주소를 확인하세요."


@pytest.mark.parametrize("url", ["http://169.254.169.254/", "http://metadata.google.internal:80",
                                 "http://user:pw@127.0.0.1:5000"])
def test_j2534_blocks_ssrf_targets(admin_client, url) -> None:
    response = _post(admin_client, TEST_URL, {"transport": "j2534_can", "config": {"bridge_url": url}})
    assert response.status_code == 400
    assert response.get_json()["message"] in ("게이트웨이 주소를 확인하세요.", "J2534 브리지 URL을 확인하세요.")


def test_connection_failure_does_not_leak_exception_details(admin_client) -> None:
    # 닫힌 포트: OSError 원문(errno, 주소 등)이 응답에 실리면 안 된다
    response = _post(admin_client, TEST_URL, {"transport": "doip", "config": {"host": "127.0.0.1", "port": 1, "timeout": 0.5}})
    assert response.status_code == 400
    body = response.get_json()
    assert body == {"success": False, "message": "게이트웨이에 연결하지 못했습니다.", "details": {}}

    response = _post(admin_client, TEST_URL, {"transport": "j2534_can", "config": {"bridge_url": "http://127.0.0.1:1"}})
    assert response.status_code == 400
    body = response.get_json()
    assert body["message"] == "브리지와 통신하지 못했습니다."
    assert "Errno" not in str(body) and "refused" not in str(body).lower()


def test_unexpected_error_returns_generic_500(admin_client, monkeypatch) -> None:
    from app.modules.scanner import service

    def boom(*_args, **_kwargs):
        raise RuntimeError("secret-internal-detail")

    monkeypatch.setattr(service, "run_scan_with_transport", boom)
    response = _post(admin_client, RUN_URL, RUN)
    assert response.status_code == 500
    assert response.get_json() == {"message": "스캔 실행 중 오류가 발생했습니다."}
    assert "secret-internal-detail" not in response.get_data(as_text=True)


def test_test_transport_with_mock_doip(admin_client, mock_doip_gateway) -> None:
    body = {"transport": "doip", "config": {"host": "127.0.0.1", "port": mock_doip_gateway.port, "timeout": 0.5}}
    response = _post(admin_client, TEST_URL, body)
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["message"] == "DoIP 연결 테스트 성공"


def test_test_transport_with_mock_j2534(admin_client, mock_j2534_bridge) -> None:
    response = _post(admin_client, TEST_URL, {"transport": "j2534_can", "config": {"bridge_url": mock_j2534_bridge.url}})
    assert response.status_code == 200
    assert response.get_json()["success"] is True
    assert mock_j2534_bridge.channels == {} and mock_j2534_bridge.devices == set()


def test_run_with_transport_with_mock_doip(admin_client, mock_doip_gateway, no_car_lookup) -> None:
    body = {"carNo": "12가3456", "transport": "doip",
            "config": {"host": "127.0.0.1", "port": mock_doip_gateway.port, "timeout": 0.5}}
    response = _post(admin_client, RUN_URL, body)
    assert response.status_code == 201
    data = response.get_json()
    assert data["url"] == f"/admin/scan/{data['id']}"
