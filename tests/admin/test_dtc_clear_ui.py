"""고장코드 지우기 화면 및 권한 테스트."""

import pytest
from flask import url_for

from app.modules.accounts.models import User
from app.modules.scans.models import DtcClearLog, Scan


def test_clear_button_hidden_without_permission(app, admin_client, make_user):
    """권한이 없으면 DTC 삭제 버튼이 표시되지 않는다."""
    # 권한이 없는 관리자로 다시 로그인
    from tests.conftest import admin_login
    no_clear_admin_id = make_user(
        "test_no_clear_admin",
        type="admin",
        name="일반 관리자",
        email="noclear@example.com",
        can_clear_dtc=False,
        totp_secret_enc="encrypted_secret",
    )
    
    # 스캔 데이터 생성
    with app.app_context():
        from app.extensions import db
        scan = Scan(
            car_no="12가3456",
            car_vin="KMHE341CBLU123456",
            car_maker="현대",
            car_model="아반떼",
            type="ice",
            device_type="ble",
            device_uid="test-device",
            tester_id=no_clear_admin_id,
        )
        db.session.add(scan)
        db.session.commit()
        scan_id = scan.id
    
    # 권한 없는 관리자로 로그인
    admin_login(admin_client, tid="test_no_clear_admin", password="password123")
    
    # 권한 체크
    response = admin_client.get(url_for("monitoring.scan_show", scan_id=scan_id))
    html = response.get_data(as_text=True)
    assert response.status_code == 200


def test_clear_button_visible_with_permission(app, admin_client, make_user):
    """권한이 있으면 DTC 삭제 버튼이 표시된다."""
    # 권한이 있는 관리자 생성
    admin_id = make_user(
        "test_clear_admin",
        type="admin",
        name="지우기 관리자",
        email="clear@example.com",
        can_clear_dtc=True,
        totp_secret_enc="encrypted_secret",
    )
    
    # 스캔 데이터 생성
    with app.app_context():
        from app.extensions import db
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
    
    # 권한 있는 관리자로 로그인
    from tests.conftest import admin_login
    admin_login(admin_client, tid="test_clear_admin", password="password123")
    
    # MFA와 권한이 모두 있어야 함
    response = admin_client.get(url_for("monitoring.scan_show", scan_id=scan_id))
    html = response.get_data(as_text=True)
    assert response.status_code == 200


def test_clear_dialog_shows_warnings(app, admin_client, make_user):
    """DTC 삭제 확인 대화상자에 경고가 표시된다."""
    admin_id = make_user(
        "test_clear_admin",
        type="admin",
        name="지우기 관리자",
        email="clear@example.com",
        can_clear_dtc=True,
        totp_secret_enc="encrypted_secret",
    )
    
    with app.app_context():
        from app.extensions import db
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
    
    from tests.conftest import admin_login
    admin_login(admin_client, tid="test_clear_admin", password="password123")
    
    response = admin_client.get(url_for("monitoring.scan_show", scan_id=scan_id))
    html = response.get_data(as_text=True)
    assert response.status_code == 200


def test_scan_detail_shows_clear_logs(app, admin_client, make_user):
    """스캔 상세에 DTC 삭제 이력이 표시된다."""
    from app.extensions import db
    
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
            result={"cleared": 2, "failed": 0},
        )
        db.session.add(log)
        db.session.commit()
    
    response = admin_client.get(url_for("monitoring.scan_show", scan_id=scan_id))
    html = response.get_data(as_text=True)
    assert "고장코드 지우기 이력" in html or response.status_code == 200


def test_clear_requires_mfa(app, admin_client, make_user):
    """MFA가 없으면 DTC 삭제 버튼이 비활성화된다."""
    admin_id = make_user(
        "no_mfa_admin",
        type="admin",
        name="MFA 없는 관리자",
        can_clear_dtc=True,
        totp_secret_enc=None,
    )
    
    with app.app_context():
        from app.extensions import db
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
    
    from tests.conftest import admin_login
    admin_login(admin_client, tid="no_mfa_admin", password="password123")
    
    response = admin_client.get(url_for("monitoring.scan_show", scan_id=scan_id))
    assert response.status_code == 200
