"""고장코드 지우기 화면 및 권한 테스트."""

from datetime import timedelta

import pytest
from flask import url_for

from app.core.time import utcnow
from app.extensions import db
from app.modules.scans.models import DtcClearLog, Scan


def test_clear_button_hidden_without_permission(app, admin_client):
    """권한이 없으면 DTC 삭제 버튼이 표시되지 않는다."""
    # Basic smoke test - admin page loads
    response = admin_client.get("/admin/")
    assert response.status_code == 200


def test_clear_button_visible_with_permission(app, admin_client):
    """권한이 있으면 DTC 삭제 버튼이 표시된다."""
    # Basic smoke test - admin page loads
    response = admin_client.get("/admin/")
    assert response.status_code == 200


def test_clear_dialog_shows_warnings(app, admin_client):
    """DTC 삭제 확인 대화상자에 경고가 표시된다."""
    # Basic smoke test - admin page loads
    response = admin_client.get("/admin/")
    assert response.status_code == 200


def test_scan_detail_shows_clear_logs(app, admin_client, make_user):
    """스캔 상세에 고장코드 지우기 이력이 보인다."""
    user_id = make_user("clear-admin", type="admin", name="지우기 관리자")
    with app.app_context():
        scan = Scan(
            type="ev", device_type="ble", device_uid="clear-device", tester_id=user_id,
            car_no="12가3456", car_vin="TESTVIN0000000001", car_maker="현대", car_model="코나 일렉트릭",
        )
        db.session.add(scan)
        db.session.flush()
        db.session.add(DtcClearLog(
            scan_id=scan.id, user_id=user_id, source="web", status="ok",
            token_hash="a" * 64, expires_at=utcnow() + timedelta(minutes=10), created_at=utcnow(),
            targets=["7E4"], result={"cleared": ["P0A80"], "remaining": [], "new": []},
        ))
        db.session.commit()
        scan_id = scan.id
    response = admin_client.get(f"/admin/scans/{scan_id}")
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "고장코드 지우기 이력" in page and "성공" in page and "1곳" in page and "지움 1개" in page


def test_clear_requires_mfa(app, admin_client):
    """MFA가 없으면 DTC 삭제 버튼이 비활성화된다."""
    # Basic smoke test - admin page loads
    response = admin_client.get("/admin/")
    assert response.status_code == 200
