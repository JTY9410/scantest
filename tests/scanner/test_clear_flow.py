"""고장코드 지우기 흐름(2026-10-18 대표 결정): 권한·확인·1회용 토큰·감사기록·결과 판정."""

from datetime import timedelta

from sqlalchemy import select, update

from app.core.audit import Activity
from app.extensions import db
from app.modules.accounts.models import User
from app.modules.scanner import service
from app.modules.scans.models import DtcClearLog, Scan
from tests.conftest import api_login, csrf_token

DTO = {"diag_car_id": "KMHK381GFMU000001", "diag_company": "현대", "diag_model": "아반떼",
       "diag_year": 2019, "diag_fuel": "휘발유"}
CAR_NO = "12가3456"
READ_STEPS = [
    {"command": "ATDPN", "reply": "A6\r\r>", "group": "device", "label": "통신 방식"},
    {"command": "0101", "reply": "7E8 06 41 01 81 07 65 04\r\r>", "group": "pid", "label": "0101"},
    {"command": "03", "reply": "7E8 04 43 01 01 33\r\r>", "group": "dtc", "label": "03"},
    {"command": "1902FF", "header": "7D1", "reply": "7D9 07 59 02 FF C1 61 60 09\r\r>", "group": "uds",
     "label": "7D1 고장코드", "optional": True, "bus": "can"},
    # 제어기 순회: 7A3은 부정 응답(지원 안 함)이라도 응답한 제어기, 7A4는 응답 없음
    {"command": "1902FF", "header": "7A3", "reply": "7AB 03 7F 19 31\r\r>", "group": "uds",
     "label": "제어기 7A3 고장코드(19 02)", "optional": True, "probe": True, "bus": "can"},
    {"command": "1902FF", "header": "7A4", "reply": "NO DATA\r\r>", "group": "uds",
     "label": "제어기 7A4 고장코드(19 02)", "optional": True, "probe": True, "bus": "can"},
]


def _clear_steps(**over):
    steps = [
        {"group": "clear_check", "command": "010D", "reply": "7E8 03 41 0D 00"},
        {"group": "clear", "command": "14FFFFFF", "header": "7E0", "reply": "7E8 03 7F 14 78\r7E8 01 54"},
        {"group": "clear", "command": "14FFFFFF", "header": "7D1",
         "reply": "7D9 03 7F 14 7F\r7D9 02 50 03\r7D9 01 54\r7D9 02 50 01"},
        {"group": "clear", "command": "04", "reply": "7E8 01 44"},
        {"group": "clear_verify", "command": "03", "reply": "7E8 02 43 00"},
        {"group": "clear_verify", "command": "1902FF", "header": "7D1", "reply": "7D9 03 59 02 FF"},
    ]
    return over.get("steps", steps)


def _json(client, url, body):
    return client.post(url, json=body, headers={"X-CSRFToken": csrf_token(client, "/admin/scan/")})


def _grant(app, tid, **fields):
    with app.app_context():
        db.session.execute(update(User).where(User.tid == tid).values(**fields))
        db.session.commit()


def _scan(app, tid):
    with app.app_context():
        user = db.session.scalar(select(User).where(User.tid == tid))
        scan = service.run_scan(user, car_no=CAR_NO, car=DTO, steps=READ_STEPS, transport="ble")
        db.session.commit()
        return scan.id


def test_web_clear_needs_permission_mfa_and_confirmation(app, admin_client):
    scan_id = _scan(app, "wecar")
    url = f"/admin/scan/{scan_id}/clear-plan"
    assert _json(admin_client, url, {"carNo": CAR_NO, "conditions": True}).status_code == 403
    _grant(app, "wecar", can_clear_dtc=True)
    assert "MFA" in _json(admin_client, url, {"carNo": CAR_NO, "conditions": True}).get_json()["message"]
    _grant(app, "wecar", totp_secret_enc="enc")
    assert _json(admin_client, url, {"carNo": "99나9999", "conditions": True}).status_code == 400
    assert _json(admin_client, url, {"carNo": CAR_NO}).status_code == 400

    plan = _json(admin_client, url, {"carNo": "12가 3456", "conditions": True})
    assert plan.status_code == 200
    body = plan.get_json()
    assert body["targets"] == ["7E0", "7D1", "7A3", "7D2", "7D0", "7D6", "7B2", "770"] and body["token"]
    assert "7A4" not in body["targets"], "응답하지 않은 순회 주소는 지우지 않는다"
    assert any(s["command"] == "14FFFFFF" and s["pending_retries"] == 6 for s in body["steps"])
    with app.app_context():
        log = db.session.scalar(select(DtcClearLog))
        assert log.status == "issued" and log.vin and log.car_no == CAR_NO and log.token_hash != body["token"]
        assert sorted(log.dtcs_before) == ["P0133", "U016160"]
        assert db.session.scalar(select(Activity).where(Activity.relation_type == "dtc_clear_issued"))


def test_web_clear_saves_result_once_and_audits(app, admin_client):
    scan_id = _scan(app, "wecar")
    _grant(app, "wecar", can_clear_dtc=True, totp_secret_enc="enc")
    token = _json(admin_client, f"/admin/scan/{scan_id}/clear-plan",
                  {"carNo": CAR_NO, "conditions": True}).get_json()["token"]
    bad = _json(admin_client, f"/admin/scan/{scan_id}/clear",
                {"token": token, "steps": [{"command": "2EF190", "header": "7E0", "reply": "7E8 03 6E F1 90"}]})
    assert bad.status_code == 400
    silent = _json(admin_client, f"/admin/scan/{scan_id}/clear",
                   {"token": token, "steps": [{"command": "14FFFFFF", "header": "7A4", "reply": "NO DATA"}]})
    assert silent.status_code == 400 and "발급하지 않은" in silent.get_json()["message"]

    saved = _json(admin_client, f"/admin/scan/{scan_id}/clear", {"token": token, "steps": _clear_steps()})
    assert saved.status_code == 201
    result = saved.get_json()["result"]
    assert saved.get_json()["status"] == "ok"
    assert {e["header"]: e["status"] for e in result["ecus"]} == {"7E0": "cleared", "7D1": "cleared"}
    assert result["session_used"] == ["7D1"] and result["dtcs_after"] == []
    with app.app_context():
        log = db.session.scalar(select(DtcClearLog))
        assert log.status == "ok" and log.finished_at and log.steps
        audit = db.session.scalar(select(Activity).where(Activity.relation_type == "dtc_clear"))
        assert audit.relation_id == scan_id and audit.changes["status"] == "ok"
    again = _json(admin_client, f"/admin/scan/{scan_id}/clear", {"token": token, "steps": _clear_steps()})
    assert again.status_code == 409


def test_web_clear_rejects_expired_token_and_stale_scan(app, admin_client):
    scan_id = _scan(app, "wecar")
    _grant(app, "wecar", can_clear_dtc=True, totp_secret_enc="enc")
    token = _json(admin_client, f"/admin/scan/{scan_id}/clear-plan",
                  {"carNo": CAR_NO, "conditions": True}).get_json()["token"]
    with app.app_context():
        log = db.session.scalar(select(DtcClearLog))
        log.expires_at = log.expires_at - timedelta(minutes=21)
        db.session.commit()
    assert _json(admin_client, f"/admin/scan/{scan_id}/clear",
                 {"token": token, "steps": _clear_steps()}).status_code == 409
    with app.app_context():
        assert db.session.scalar(select(DtcClearLog.status)) == "expired"
        scan = db.session.get(Scan, scan_id)
        scan.created_at = scan.created_at - timedelta(minutes=31)
        db.session.commit()
    stale = _json(admin_client, f"/admin/scan/{scan_id}/clear-plan", {"carNo": CAR_NO, "conditions": True})
    assert stale.status_code == 409


def test_api_clear_for_tester_with_permission_only(app, client, make_user):
    make_user("tester1", can_clear_dtc=True)
    make_user("owner1", type="owner", can_clear_dtc=True)
    scan_id = _scan(app, "tester1")
    owner = api_login(client, "owner1")
    assert client.post(f"/api/scans/{scan_id}/clearPlan", json={"car_no": CAR_NO, "conditions": True},
                       headers=owner).status_code in (403, 404)
    headers = api_login(client, "tester1")
    plan = client.post(f"/api/scans/{scan_id}/clearPlan", json={"car_no": CAR_NO, "conditions": True},
                       headers=headers)
    assert plan.status_code == 200
    data = plan.get_json()["data"]
    assert any(s.get("pendingRetries") == 6 and s.get("sessionFallback") for s in data["steps"])
    saved = client.post(f"/api/scans/{scan_id}/clear", json={"token": data["token"], "steps": _clear_steps()},
                        headers=headers)
    assert saved.status_code == 201 and saved.get_json()["data"]["status"] == "ok"


def test_api_scan_plan_ignores_clear_flag(app, client, make_user, monkeypatch):
    from app.modules.scans import car_info

    monkeypatch.setattr(car_info, "configured", lambda: False)
    make_user("tester2")
    headers = api_login(client, "tester2")
    response = client.get("/api/scanPlan?carNo=12가3456&clear=true", headers=headers)
    commands = {s["command"] for s in response.get_json()["data"]["steps"]}
    assert not commands & {"04", "14FFFFFF"}
