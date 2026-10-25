"""전송 계층 통합 테스트 (모의 서버 포함).

run_scan_with_transport(), 라우트 엔드포인트, 전체 흐름을 검증한다.
모의 DoIP 게이트웨이·J2534 브리지는 tests/scanner/conftest.py의 fixture를 쓴다.
기대 상태 코드는 각 경우의 정확한 단일 값이며, 예외를 삼키지 않는다.
"""

from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import db
from app.core.errors import ServiceError
from app.modules.accounts.models import User
from app.modules.scanner import service
from app.modules.scanner.service import run_scan_with_transport
from app.modules.scans.models import Scan
from tests.conftest import csrf_token


def _headers(client: FlaskClient, url: str = "/admin/scan/") -> dict:
    return {"X-CSRFToken": csrf_token(client, url)}


# === run_scan_with_transport() ===

def test_run_scan_with_transport_doip(app: Flask, mock_doip_gateway, make_user: Any, no_car_lookup) -> None:
    admin_id = make_user("admin", type="admin")
    with app.app_context():
        scan = run_scan_with_transport(
            db.session.get(User, admin_id), car_no="12가3456", transport="doip",
            transport_config={"host": "127.0.0.1", "port": mock_doip_gateway.port, "timeout": 0.5},
        )
        saved = db.session.get(Scan, scan.id)
        assert saved.car_no == "12가3456"
        assert saved.device_type == "doip"
        steps = service.scan_result(saved)["steps"]
        assert steps
        assert any(step["command"] == "0100" and "41 00 BE 1F B8 13" in step["raw"] for step in steps)


def test_run_scan_with_transport_j2534(app: Flask, mock_j2534_bridge, make_user: Any, no_car_lookup) -> None:
    admin_id = make_user("admin2", type="admin")
    with app.app_context():
        scan = run_scan_with_transport(
            db.session.get(User, admin_id), car_no="12가3456", transport="j2534_can",
            transport_config={"bridge_url": mock_j2534_bridge.url},
        )
        saved = db.session.get(Scan, scan.id)
        assert saved.car_no == "12가3456"
        assert saved.device_type == "j2534"
        assert saved.device_uid == f"J2534 CAN ({mock_j2534_bridge.url})"
        steps = service.scan_result(saved)["steps"]
        assert any(step["command"] == "0100" and "41 00 BE 1F B8 13" in step["raw"] for step in steps)


def test_run_scan_with_transport_gateway_down_raises_service_error(app: Flask, make_user: Any, no_car_lookup) -> None:
    admin_id = make_user("admin3", type="admin")
    with app.app_context():
        with pytest.raises(ServiceError) as info:
            run_scan_with_transport(
                db.session.get(User, admin_id), car_no="12가3456", transport="doip",
                transport_config={"host": "127.0.0.1", "port": 1, "timeout": 0.5},
            )
        assert info.value.status == 400
        assert info.value.message == "게이트웨이에 연결하지 못했습니다."
        assert db.session.query(Scan).count() == 0


# === 라우트 테스트 ===

def test_test_transport_requires_admin(client: FlaskClient) -> None:
    """비로그인은 로그인 화면으로 보낸다 (CSRF 토큰을 넣어 권한 검사까지 닿게 한다)."""
    response = client.post(
        "/admin/scan/test-transport",
        json={"transport": "doip", "config": {"host": "127.0.0.1"}},
        headers=_headers(client, "/admin/login"),
    )
    assert response.status_code == 302


def test_test_transport_validates_transport(admin_client: FlaskClient) -> None:
    response = admin_client.post(
        "/admin/scan/test-transport",
        json={"transport": "invalid_transport", "config": {}},
        headers=_headers(admin_client),
    )
    assert response.status_code == 400
    assert response.get_json()["message"] == "서버 측 테스트를 지원하지 않는 방식입니다."


def test_test_transport_rejects_unverified(admin_client: FlaskClient) -> None:
    response = admin_client.post(
        "/admin/scan/test-transport",
        json={"transport": "j2534_kline", "config": {"bridge_url": "http://127.0.0.1:1"}},
        headers=_headers(admin_client),
    )
    assert response.status_code == 400
    assert "검증되지 않아" in response.get_json()["message"]


def test_run_with_transport_requires_admin(client: FlaskClient) -> None:
    response = client.post(
        "/admin/scan/run-with-transport",
        json={"carNo": "12가3456", "transport": "doip", "config": {"host": "127.0.0.1"}},
        headers=_headers(client, "/admin/login"),
    )
    assert response.status_code == 302


def test_run_with_transport_validates_input(admin_client: FlaskClient) -> None:
    response = admin_client.post("/admin/scan/run-with-transport",
                                 json={"transport": "doip", "config": {}}, headers=_headers(admin_client))
    assert response.status_code == 400
    assert response.get_json()["message"] == "차량번호를 입력해주세요."

    response = admin_client.post("/admin/scan/run-with-transport",
                                 json={"carNo": "12가3456", "config": {}}, headers=_headers(admin_client))
    assert response.status_code == 400
    assert response.get_json()["message"] == "전송 방식을 선택하세요."


def test_run_with_transport_with_mock_doip(
    admin_client: FlaskClient, mock_doip_gateway, no_car_lookup,
) -> None:
    response = admin_client.post(
        "/admin/scan/run-with-transport",
        json={"carNo": "12가3456", "transport": "doip",
              "config": {"host": "127.0.0.1", "port": mock_doip_gateway.port, "timeout": 0.5}},
        headers=_headers(admin_client),
    )
    assert response.status_code == 201
    scan_id = response.get_json()["id"]
    page = admin_client.get(f"/admin/scan/{scan_id}")
    assert page.status_code == 200
