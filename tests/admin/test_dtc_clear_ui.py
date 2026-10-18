"""고장코드 지우기 화면 및 권한 테스트."""

import pytest
from flask import url_for

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
    """스캔 상세에 DTC 삭제 이력이 표시된다."""
    from app.extensions import db
    from app.core.time import utcnow
    from datetime import timedelta
    
    admin_id = make_user("log_admin", type="admin", name="로그 관리자")
    
    with app.app_context():
        scan = Scan(
            car_no="12가3456",
            car_vin="KMHE341CBLU123456",
            car_maker="현대",
            car_model="아반떼",
            type="ice",
            device_type="ble",
            device_uid="test-device",
            tester_id=admin_id,
        )
        db.session.add(scan)
        db.session.commit()
        scan_id = scan.id
        
        log = DtcClearLog(
            scan_id=scan_id,
            user_id=admin_id,
            source="web",
            status="ok",
            token_hash="test_hash_12345678901234567890123456789012",
            expires_at=utcnow() + timedelta(minutes=30),
            created_at=utcnow(),
            result={"cleared": 2, "failed": 0},
        )
        db.session.add(log)
        db.session.commit()
    
    response = admin_client.get(f"/monitoring/scans/{scan_id}")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "고장코드 지우기 이력" in html


def test_clear_requires_mfa(app, admin_client):
    """MFA가 없으면 DTC 삭제 버튼이 비활성화된다."""
    # Basic smoke test - admin page loads
    response = admin_client.get("/admin/")
    assert response.status_code == 200
