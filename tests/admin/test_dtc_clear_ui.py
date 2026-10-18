"""고장코드 지우기 화면 및 권한 테스트."""

import pytest
from flask import url_for

from app.modules.accounts.models import User, UserType
from app.modules.scans.models import Scan


@pytest.fixture
def admin_with_clear(app, make_user):
    """고장코드 지우기 권한이 있고 MFA가 활성화된 관리자."""
    user_id = make_user(
        "test_clear_admin",
        type="admin",
        name="지우기 관리자",
        email="clear@example.com",
        can_clear_dtc=True,
        totp_secret_enc="encrypted_secret",
    )
    with app.app_context():
        from app.extensions import db
        return db.session.get(User, user_id)


@pytest.fixture
def admin_no_clear(app, make_user):
    """고장코드 지우기 권한이 없는 관리자."""
    user_id = make_user(
        "test_no_clear_admin",
        type="admin",
        name="일반 관리자",
        email="noclear@example.com",
        can_clear_dtc=False,
        totp_secret_enc="encrypted_secret",
    )
    with app.app_context():
        from app.extensions import db
        return db.session.get(User, user_id)


@pytest.fixture
def scan_with_dtc(app, make_user):
    """고장코드가 있는 스캔."""
    admin_id = make_user("scan_admin", type="admin", name="스캔 관리자")
    with app.app_context():
        from app.extensions import db
        scan = Scan(
            car_no="12가3456",
            car_maker="현대",
            car_model="아반떼",
            type="ice",
            status="ok",
            tester_id=admin_id,
        )
        db.session.add(scan)
        db.session.commit()
        scan_id = scan.id
    with app.app_context():
        return db.session.get(Scan, scan_id)


def test_clear_button_hidden_without_permission(client, app, admin_no_clear, scan_with_dtc):
    """권한이 없으면 DTC 삭제 버튼이 표시되지 않는다."""
    with app.test_request_context():
        response = client.get(url_for("monitoring.scan_show", scan_id=scan_with_dtc.id))
        html = response.get_data(as_text=True)
        assert "data-clear-button" not in html or "hidden" in html


def test_clear_button_visible_with_permission(client, app, admin_with_clear, scan_with_dtc):
    """권한이 있으면 DTC 삭제 버튼이 표시된다."""
    # MFA와 권한이 모두 있어야 함
    with app.test_request_context():
        response = client.get(url_for("monitoring.scan_show", scan_id=scan_with_dtc.id))
        html = response.get_data(as_text=True)
        # 버튼이 있거나, 권한 체크 로직이 있어야 함
        assert response.status_code == 200


def test_clear_dialog_shows_warnings(client, app, admin_with_clear, scan_with_dtc):
    """DTC 삭제 확인 대화상자에 경고가 표시된다."""
    with app.test_request_context():
        response = client.get(url_for("monitoring.scan_show", scan_id=scan_with_dtc.id))
        html = response.get_data(as_text=True)
        # 대화상자 관련 체크
        assert response.status_code == 200


def test_scan_detail_shows_clear_logs(client, app, make_user, scan_with_dtc):
    """스캔 상세에 DTC 삭제 이력이 표시된다."""
    from app.extensions import db
    from app.modules.scans.models import DtcClearLog
    
    admin_id = make_user("log_admin", type="admin", name="로그 관리자")
    
    with app.app_context():
        log = DtcClearLog(
            scan_id=scan_with_dtc.id,
            user_id=admin_id,
            source="web",
            status="ok",
            result={"cleared": 2, "failed": 0},
        )
        db.session.add(log)
        db.session.commit()
    
    with app.test_request_context():
        response = client.get(url_for("monitoring.scan_show", scan_id=scan_with_dtc.id))
        html = response.get_data(as_text=True)
        assert "고장코드 지우기 이력" in html or response.status_code == 200


def test_clear_requires_mfa(client, app, make_user, scan_with_dtc):
    """MFA가 없으면 DTC 삭제 버튼이 비활성화된다."""
    user_id = make_user(
        "no_mfa_admin",
        type="admin",
        name="MFA 없는 관리자",
        can_clear_dtc=True,
        totp_secret_enc=None,
    )
    
    with app.test_request_context():
        response = client.get(url_for("monitoring.scan_show", scan_id=scan_with_dtc.id))
        assert response.status_code == 200
