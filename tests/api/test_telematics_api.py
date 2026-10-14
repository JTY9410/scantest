import re

import httpx
from sqlalchemy import select

from app.extensions import db
from app.modules.canlab.models import CanDataset
from app.modules.obd.models import TelematicsDevice
from app.modules.scans import car_info
from app.modules.scans.models import Scan
from tests.conftest import csrf_token

DTO = {"diag_car_id": "KNAXX000000000000", "diag_company": "기아", "diag_model": "EV6", "diag_year": 2022,
       "diag_fuel": "전기", "diag_displacement": ""}


def _register(admin_client, serial="LTE-0001") -> str:
    token = csrf_token(admin_client, "/admin/obd/")
    response = admin_client.post("/admin/obd/devices", data={
        "csrf_token": token, "device-serial": serial, "device-name": "1호 단말기", "device-company_id": "0"})
    assert response.status_code == 201
    return re.search(r"data-device-token>([^<]+)<", response.get_data(as_text=True)).group(1)


def test_device_token_is_shown_once_and_hashed(app, admin_client):
    token = _register(admin_client)
    with app.app_context():
        device = db.session.scalar(select(TelematicsDevice))
        assert token not in device.token_hash and device.token_last4 == token[-4:]
    listing = admin_client.get("/admin/obd/").get_data(as_text=True)
    assert token not in listing and "LTE-0001" in listing
    duplicate = admin_client.post("/admin/obd/devices", data={
        "csrf_token": csrf_token(admin_client, "/admin/obd/"), "device-serial": "LTE-0001",
        "device-company_id": "0"})
    assert duplicate.status_code == 409


def test_plan_and_capture_with_device_token(app, client, admin_client, monkeypatch):
    calls = []

    def fake(url, data, timeout):
        calls.append(data["car_no"])
        return httpx.Response(200, json={"status": "ok", "msg": "정상", "dto": DTO})

    monkeypatch.setattr(car_info.httpx, "post", fake)
    token = _register(admin_client)
    headers = {"Authorization": f"Device {token}"}

    plan = client.get("/api/telematics/plan?carNo=12가 3456", headers=headers)
    assert plan.status_code == 200
    body = plan.get_json()
    assert body["carNo"] == "12가3456" and body["car"]["diagModel"] == "EV6"
    assert any(s["header"] == "7E4" and s["command"] == "220101" for s in body["steps"])

    steps = [{"command": "ATDPN", "reply": "A6", "group": "device"},
             {"command": "0100", "reply": "7E8 06 41 00 98 3B 80 13"},
             {"command": "03", "reply": None, "error": "timeout", "group": "dtc"}]
    response = client.post("/api/telematics/captures", json={"carNo": "12가3456", "steps": steps},
                           headers=headers)
    assert response.status_code == 201, response.get_json()
    data = response.get_json()
    assert data["status"] == "partial" and data["errors"][0]["statusLabel"] == "시간 초과"
    assert calls == ["12가3456"]
    with app.app_context():
        scan = db.session.get(Scan, data["id"])
        assert scan.device_type == "lte" and "LTE-0001" in scan.device_uid and scan.type == "ev"
        assert db.session.get(CanDataset, scan.bms_data["dataset_id"]).source == "lte"
        assert db.session.scalar(select(TelematicsDevice.last_seen_at)) is not None


def test_bad_or_disabled_token_is_rejected(app, client, admin_client):
    token = _register(admin_client)
    assert client.get("/api/telematics/plan", headers={"Authorization": "Device wrong"}).status_code == 401
    assert client.get("/api/telematics/plan", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    with app.app_context():
        device_id = db.session.scalar(select(TelematicsDevice.id))
    admin_client.post(f"/admin/obd/devices/{device_id}/toggle",
                      data={"csrf_token": csrf_token(admin_client, "/admin/obd/")})
    response = client.get("/api/telematics/plan", headers={"Authorization": f"Device {token}"})
    assert response.status_code == 401 and response.get_json()["message"] == "단말기 인증에 실패했습니다."
