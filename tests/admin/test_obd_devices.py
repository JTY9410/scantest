import json
import re

from tests.conftest import api_login, csrf_token

WEB_DEVICE = {"transport": "serial", "name": "CANable 2.0", "dialect": "slcan", "chip": "slcan",
              "version": "V1013", "protocol": "6", "settings": {"bitrate": 500000}}


def _post(client, body):
    token = csrf_token(client, "/admin/obd/")
    return client.post("/admin/obd/my-devices", json=body, headers={"X-CSRFToken": token})


def _obd_config(html: str) -> dict:
    match = re.search(r'<script type="application/json" id="obd-config">(.*?)</script>', html, re.S)
    assert match, "obd-config가 없습니다"
    return json.loads(match.group(1))


def test_web_remembers_device_for_panel_and_admin_list(admin_client):
    assert admin_client.post("/admin/obd/my-devices", json=WEB_DEVICE).status_code == 400

    created = _post(admin_client, WEB_DEVICE)
    assert created.status_code == 201
    device_id = created.get_json()["id"]
    again = _post(admin_client, {**WEB_DEVICE, "version": "V1014"})
    assert again.status_code == 200 and again.get_json()["id"] == device_id

    config = _obd_config(admin_client.get("/admin/canlab/live").get_data(as_text=True))
    assert config["devices"] == [{"id": device_id, "platform": "web", "transport": "serial", "name": "CANable 2.0",
                                  "dialect": "slcan", "chip": "slcan", "version": "V1014", "serviceUuid": None,
                                  "writeUuid": None, "notifyUuid": None, "protocol": "6",
                                  "settings": {"bitrate": 500000},
                                  "lastConnectedAt": config["devices"][0]["lastConnectedAt"]}]

    html = admin_client.get("/admin/obd/").get_data(as_text=True)
    assert "연결한 진단기" in html and "CANable 2.0" in html and "slcan" in html and "운영관리자" in html

    token = csrf_token(admin_client, "/admin/obd/")
    deleted = admin_client.delete(f"/admin/obd/my-devices/{device_id}", headers={"X-CSRFToken": token})
    assert deleted.status_code == 200
    assert _obd_config(admin_client.get("/admin/canlab/live").get_data(as_text=True))["devices"] == []


def test_web_device_validation_and_other_users(admin_client, make_user):
    assert _post(admin_client, {**WEB_DEVICE, "transport": "usb"}).status_code == 422

    make_user("tester1")
    headers = api_login(admin_client, "tester1")
    app_id = admin_client.post("/api/obdDevices", json={"transport": "ble", "name": "OBDLink CX"},
                               headers=headers).get_json()["data"]["id"]

    token = csrf_token(admin_client, "/admin/obd/")
    assert admin_client.delete(f"/admin/obd/my-devices/{app_id}", headers={"X-CSRFToken": token}).status_code == 404
    assert _obd_config(admin_client.get("/admin/canlab/live").get_data(as_text=True))["devices"] == []
    assert "OBDLink CX" in admin_client.get("/admin/obd/").get_data(as_text=True)
