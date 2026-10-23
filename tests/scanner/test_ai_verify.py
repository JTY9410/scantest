"""스캔 통신 실패 AI/규칙 검증."""

from app.extensions import db
from app.modules.scans.models import Scan
from app.modules.scanner import ai_verify
from tests.conftest import csrf_token


def _scanner_scan(app, make_user, *, errors=None, steps=None):
    user_id = make_user("verify01", type="admin", password="Pw!23456")
    with app.app_context():
        scan = Scan(
            type="ice", device_type="ble", device_uid="test", tester_id=user_id,
            car_no="12가3456", car_vin="KMH0000000000001", car_model="테스트",
            bms_data={
                "source": "scanner",
                "status": "partial",
                "transport": "ble",
                "errors": errors or [],
                "steps": steps or [
                    {"header": "7E0", "command": "03", "label": "고장코드", "error": "timeout", "reply": "", "tMs": 1200},
                    {"header": "7E0", "command": "010C", "label": "RPM", "reply": "41 0C 1A F8", "tMs": 80},
                ],
                "dtcs": [],
                "wescan": {"judgments": [], "vehicle": {}, "dtc": {"enhanced": {"ecus": []}}, "sensor": {}},
            },
        )
        db.session.add(scan)
        db.session.commit()
        return scan.id


def test_rule_fallback_without_ai(app, make_user):
    scan_id = _scanner_scan(app, make_user)
    with app.app_context():
        from app.modules.accounts.models import User

        scan = db.session.get(Scan, scan_id)
        actor = db.session.get(User, scan.tester_id)
        payload = ai_verify.verify_scan(actor, scan)
        assert payload["source"] == "rules"
        assert payload["failed_count"] == 1
        assert any("시간 초과" in (i.get("issue") or "") for i in payload["items"])
        refreshed = db.session.get(Scan, scan_id)
        assert refreshed.bms_data["ai_verify"]["summary"]


def test_ai_verify_endpoint(app, admin_client, make_user):
    scan_id = _scanner_scan(app, make_user)
    # 결과 화면에 지우기 폼이 없을 수 있어 스캔 목록에서 토큰을 받는다.
    token = csrf_token(admin_client, "/admin/scan/")
    response = admin_client.post(
        f"/admin/scan/{scan_id}/ai-verify",
        json={},
        headers={"X-CSRFToken": token},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["source"] == "rules"
    assert data["failed_count"] == 1
