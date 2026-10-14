from sqlalchemy import select

from app.extensions import db
from app.modules.obd.models import ObdDevice
from tests.conftest import api_login

DEVICE = {
    "transport": "ble",
    "name": "WiCAN-1A2B",
    "dialect": "slcan",
    "chip": "slcan",
    "version": "V1013",
    "serviceUuid": "6E400001-B5A3-F393-E0A9-E50E24DCCA9E",
    "writeUuid": "6e400002-b5a3-f393-e0a9-e50e24dcca9e",
    "notifyUuid": "6e400003-b5a3-f393-e0a9-e50e24dcca9e",
    "protocol": "6",
    "settings": {"bitrate": 500000},
}


def test_app_remembers_device_and_updates_same_name(app, client, make_user):
    make_user("tester1")
    headers = api_login(client, "tester1")

    assert client.get("/api/obdDevices").status_code == 401
    assert client.post("/api/obdDevices", json=DEVICE).status_code == 401

    created = client.post("/api/obdDevices", json=DEVICE, headers=headers)
    assert created.status_code == 201
    device_id = created.get_json()["data"]["id"]

    again = client.post("/api/obdDevices", json={**DEVICE, "version": "V1014", "protocol": "7"}, headers=headers)
    assert again.status_code == 200
    assert again.get_json()["data"]["id"] == device_id

    data = client.get("/api/obdDevices", headers=headers).get_json()["data"]
    assert data == [{
        "id": device_id,
        "platform": "app",
        "transport": "ble",
        "name": "WiCAN-1A2B",
        "dialect": "slcan",
        "chip": "slcan",
        "version": "V1014",
        "serviceUuid": "6e400001-b5a3-f393-e0a9-e50e24dcca9e",
        "writeUuid": "6e400002-b5a3-f393-e0a9-e50e24dcca9e",
        "notifyUuid": "6e400003-b5a3-f393-e0a9-e50e24dcca9e",
        "protocol": "7",
        "settings": {"bitrate": 500000},
        "lastConnectedAt": data[0]["lastConnectedAt"],
    }]
    with app.app_context():
        assert db.session.scalar(select(db.func.count()).select_from(ObdDevice)) == 1


def test_devices_are_per_user_and_delete_only_own(client, make_user):
    make_user("tester1")
    make_user("tester2")
    first = api_login(client, "tester1")
    second = api_login(client, "tester2")
    device_id = client.post("/api/obdDevices", json=DEVICE, headers=first).get_json()["data"]["id"]

    assert client.get("/api/obdDevices", headers=second).get_json()["data"] == []
    assert client.delete(f"/api/obdDevices/{device_id}", headers=second).status_code == 404

    deleted = client.delete(f"/api/obdDevices/{device_id}", headers=first)
    assert deleted.status_code == 200
    assert deleted.get_json()["message"] == "삭제되었습니다."
    assert client.get("/api/obdDevices", headers=first).get_json()["data"] == []


def test_device_input_is_validated(client, make_user):
    make_user("tester1")
    headers = api_login(client, "tester1")

    wrong_transport = client.post("/api/obdDevices", json={**DEVICE, "transport": "usb"}, headers=headers)
    assert wrong_transport.status_code == 422
    assert "transport" in wrong_transport.get_json()["errors"]

    wrong_dialect = client.post("/api/obdDevices", json={**DEVICE, "dialect": "j2534"}, headers=headers)
    assert wrong_dialect.status_code == 422

    no_name = client.post("/api/obdDevices", json={**DEVICE, "name": " "}, headers=headers)
    assert no_name.status_code == 422

    wrong_uuid = client.post("/api/obdDevices", json={**DEVICE, "serviceUuid": "not-a-uuid"}, headers=headers)
    assert wrong_uuid.status_code == 422
