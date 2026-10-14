from sqlalchemy import select

from app.core.audit import Activity
from app.extensions import db
from app.modules.obd.models import ObdProfile
from tests.conftest import api_login, csrf_token

BLE_FORM = {
    "name": "vLinker MC+ BLE",
    "transport": "ble",
    "device_name_prefix": "vLinker",
    "service_uuid": "FFF0",
    "write_uuid": "0000FFF2-0000-1000-8000-00805F9B34FB",
    "notify_uuid": "fff1",
    "init_commands": "at z\nATE0\n\nAT SP 6",
    "request_header": "7e4",
    "response_header": "7EC",
    "read_commands": "22 01 01\n220102",
    "response_timeout_ms": "2000",
    "enabled": "y",
}


def _create(client, **overrides):
    token = csrf_token(client, "/admin/obd/new")
    return client.post("/admin/obd/new", data={"csrf_token": token, **BLE_FORM, **overrides})


def test_admin_creates_ble_profile_with_normalized_commands(app, admin_client):
    response = _create(admin_client)

    assert response.status_code == 302
    with app.app_context():
        profile = db.session.scalar(select(ObdProfile))
        assert profile.service_uuid == "fff0"
        assert profile.write_uuid == "0000fff2-0000-1000-8000-00805f9b34fb"
        assert profile.init_commands == ["ATZ", "ATE0", "ATSP6"]
        assert profile.request_header == "7E4"
        assert profile.read_commands == ["220101", "220102"]
        action = select(Activity.relation_type).where(Activity.relation == "ObdProfile")
        assert db.session.scalar(action) == "OBD2 프로필 등록"

    listing = admin_client.get("/admin/obd/").get_data(as_text=True)
    assert "vLinker MC+ BLE" in listing and "7E4 → 7EC" in listing


def test_invalid_profile_input_is_rejected_with_reason(admin_client):
    missing_uuid = _create(admin_client, service_uuid="", write_uuid="", notify_uuid="")
    assert "BLE 연결에는 서비스·쓰기·알림 UUID가 모두 필요합니다." in missing_uuid.get_data(as_text=True)

    bad_command = _create(admin_client, init_commands="ATZ\nrm -rf /")
    assert "AT 또는 ST로 시작하는 어댑터 명령만" in bad_command.get_data(as_text=True)

    bad_read = _create(admin_client, read_commands="22010")
    assert "16진수 바이트" in bad_read.get_data(as_text=True)

    one_header = _create(admin_client, response_header="")
    assert "요청·응답 헤더는 함께 입력하세요." in one_header.get_data(as_text=True)

    assert _create(admin_client).status_code == 302
    duplicate = _create(admin_client)
    assert "이미 사용 중인 프로필 이름입니다." in duplicate.get_data(as_text=True)


def test_classic_profile_drops_ble_uuids(app, admin_client):
    response = _create(admin_client, name="ELM327 클래식", transport="classic")

    assert response.status_code == 302
    with app.app_context():
        profile = db.session.scalar(select(ObdProfile))
        assert (profile.service_uuid, profile.write_uuid, profile.notify_uuid) == (None, None, None)


def test_stale_edit_is_rejected(app, admin_client):
    _create(admin_client)
    with app.app_context():
        profile_id = db.session.scalar(select(ObdProfile.id))
    url = f"/admin/obd/{profile_id}/edit"
    token = csrf_token(admin_client, url)

    first = admin_client.post(url, data={"csrf_token": token, **BLE_FORM, "version": "1",
                                         "device_name_prefix": "OBDII"})
    stale = admin_client.post(url, data={"csrf_token": token, **BLE_FORM, "version": "1"})

    assert first.status_code == 302
    assert stale.status_code == 409
    assert "다른 관리자가 먼저 이 프로필을 수정했습니다." in stale.get_data(as_text=True)


def test_app_api_lists_only_enabled_profiles(app, client, admin_client, make_user):
    _create(admin_client)
    _create(admin_client, name="꺼진 프로필", enabled="")
    make_user("tester01")

    assert client.get("/api/obdProfiles").status_code == 401

    response = client.get("/api/obdProfiles", headers=api_login(client, "tester01"))

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert [p["name"] for p in data] == ["vLinker MC+ BLE"]
    assert data[0] == {
        "id": data[0]["id"],
        "name": "vLinker MC+ BLE",
        "transport": "ble",
        "deviceNamePrefix": "vLinker",
        "serviceUuid": "fff0",
        "writeUuid": "0000fff2-0000-1000-8000-00805f9b34fb",
        "notifyUuid": "fff1",
        "initCommands": ["ATZ", "ATE0", "ATSP6"],
        "requestHeader": "7E4",
        "responseHeader": "7EC",
        "readCommands": ["220101", "220102"],
        "responseTimeoutMs": 2000,
        "dialect": "elm327",
        "canBitrate": None,
        "updatedAt": data[0]["updatedAt"],
    }


def test_slcan_profile_takes_bitrate_and_no_adapter_commands(app, admin_client):
    rejected = _create(admin_client, name="WiCAN", dialect="slcan", init_commands="ATZ", can_bitrate="500000")
    assert rejected.status_code == 200
    assert "slcan 진단기는 AT·ST 초기화 명령을 받지 않습니다." in rejected.get_data(as_text=True)

    saved = _create(admin_client, name="WiCAN", dialect="slcan", init_commands="", can_bitrate="500000")
    assert saved.status_code == 302
    with app.app_context():
        profile = db.session.scalar(select(ObdProfile).where(ObdProfile.name == "WiCAN"))
        assert profile.dialect == "slcan" and profile.can_bitrate == 500000 and profile.init_commands == []

    elm = _create(admin_client, name="ELM 고정 속도", can_bitrate="500000")
    assert elm.status_code == 302
    with app.app_context():
        assert db.session.scalar(select(ObdProfile.can_bitrate).where(ObdProfile.name == "ELM 고정 속도")) is None
