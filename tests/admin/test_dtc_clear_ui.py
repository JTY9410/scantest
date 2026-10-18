"""고장코드 지우기 화면 및 권한 테스트."""

import pytest
from flask import url_for

from app.modules.accounts.models import User, UserType
from app.modules.scans.models import Scan


@pytest.fixture
def admin_with_clear(app, db_session):
    """고장코드 지우기 권한이 있고 MFA가 활성화된 관리자."""
    user = User(
        tid="test_clear_admin",
        name="지우기 관리자",
        email="clear@example.com",
        password="hashed",
        type=UserType.ADMIN,
        can_clear_dtc=True,
        totp_secret_enc="encrypted_secret",
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def admin_no_clear(app, db_session):
    """고장코드 지우기 권한이 없는 관리자."""
    user = User(
        tid="test_no_clear",
        name="일반 관리자",
        email="no_clear@example.com",
        password="hashed",
        type=UserType.ADMIN,
        can_clear_dtc=False,
        totp_secret_enc="encrypted_secret",
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def scan_with_dtc(app, db_session, admin_with_clear):
    """고장코드가 있는 스캔."""
    scan = Scan(
        car_no="12가3456",
        car_maker="현대",
        car_model="아반떼",
        car_year=2020,
        tester_id=admin_with_clear.id,
        type="ice",
        bms_data={
            "source": "scanner",
            "status": "ok",
            "dtcs": [
                {"code": "P0300", "ecu": "7E8"},
                {"code": "P0301", "ecu": "7E8"},
            ],
            "ecus": [{"address": "7E8"}],
            "steps": [
                {"command": "03", "status": "ok"},
            ],
        },
    )
    db_session.add(scan)
    db_session.commit()
    return scan


def test_clear_button_visible_with_permission(client, admin_with_clear, scan_with_dtc):
    """권한이 있고 MFA가 있으면 버튼이 보인다."""
    client.force_login(admin_with_clear)
    response = client.get(url_for("scanner.result", scan_id=scan_with_dtc.id))
    assert response.status_code == 200
    assert "data-clear-dtc" in response.get_data(as_text=True)
    assert "고장코드 지우기" in response.get_data(as_text=True)


def test_clear_button_hidden_without_permission(client, admin_no_clear, scan_with_dtc):
    """권한이 없으면 버튼이 비활성화된다."""
    scan_with_dtc.tester_id = admin_no_clear.id
    client.force_login(admin_no_clear)
    response = client.get(url_for("scanner.result", scan_id=scan_with_dtc.id))
    assert response.status_code == 200
    assert "권한 없음" in response.get_data(as_text=True)


def test_clear_button_hidden_without_mfa(client, admin_with_clear, scan_with_dtc, db_session):
    """MFA가 없으면 버튼이 비활성화된다."""
    admin_with_clear.totp_secret_enc = None
    db_session.commit()
    client.force_login(admin_with_clear)
    response = client.get(url_for("scanner.result", scan_id=scan_with_dtc.id))
    assert response.status_code == 200
    assert "MFA 필요" in response.get_data(as_text=True)


def test_clear_plan_requires_permission(client, admin_no_clear, scan_with_dtc):
    """권한이 없으면 계획 발급이 거부된다."""
    client.force_login(admin_no_clear)
    response = client.post(
        url_for("scanner.clear_plan", scan_id=scan_with_dtc.id),
        json={"carNo": "12가3456", "conditions": True},
    )
    assert response.status_code == 403


def test_clear_logs_in_scan_detail(client, admin_with_clear, scan_with_dtc, db_session):
    """스캔 상세에 지우기 이력이 표시된다."""
    from app.modules.scans.models import DtcClearLog
    from app.core.time import utcnow
    from datetime import timedelta

    log = DtcClearLog(
        scan_id=scan_with_dtc.id,
        user_id=admin_with_clear.id,
        source="web",
        car_no="12가3456",
        status="ok",
        token_hash="test_hash_12345678901234567890123456789012",
        expires_at=utcnow() + timedelta(minutes=20),
        targets=["7E8"],
        result={"cleared": ["P0300"], "remaining": ["P0301"], "new": []},
        created_at=utcnow(),
    )
    db_session.add(log)
    db_session.commit()

    client.force_login(admin_with_clear)
    response = client.get(url_for("monitoring.scan_show", scan_id=scan_with_dtc.id))
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "고장코드 지우기 이력" in text
    assert "지움 1개" in text
    assert "남음 1개" in text
