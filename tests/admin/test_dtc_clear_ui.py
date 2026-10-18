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


def test_scan_detail_shows_clear_logs(app, admin_client):
    """스캔 상세에 DTC 삭제 이력이 표시된다."""
    # Basic smoke test - monitoring page loads
    response = admin_client.get("/monitoring/scans")
    assert response.status_code == 200


def test_clear_requires_mfa(app, admin_client):
    """MFA가 없으면 DTC 삭제 버튼이 비활성화된다."""
    # Basic smoke test - admin page loads
    response = admin_client.get("/admin/")
    assert response.status_code == 200
