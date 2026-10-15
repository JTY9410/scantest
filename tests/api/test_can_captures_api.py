from sqlalchemy import select

from app.extensions import db
from app.modules.canlab.engine.search import Layout
from app.modules.canlab.models import CanDataset, DecodeRule, DiagnosticReport, RuleStatus
from app.modules.scans import car_info
from tests.canlab.synthetic import bms_0101, isotp_frames
from tests.conftest import api_login


def _reply(response_id: int, payload: bytes) -> str:
    """ELM327(ATH1·ATS1)이 돌려주는 응답 문자열."""
    lines = [f"{response_id:03X} " + " ".join(f"{b:02X}" for b in frame) for frame in isotp_frames(payload)]
    return "\r".join(lines) + "\r\r"


def _activate(app, signal_key: str, layout: Layout):
    with app.app_context():
        db.session.add(DecodeRule(signal_key=signal_key, revision=1, status=RuleStatus.ACTIVE,
                                  confidence=0.9, evidence={}, formula=layout.formula(),
                                  **{k: v for k, v in layout.to_dict().items()}))
        db.session.commit()


CAPTURE = {
    "vehicle": "그랜저 HEV",
    "deviceName": "vLinker MC+",
    "exchanges": [
        {"tMs": 120, "header": "7E4", "command": "220101",
         "reply": _reply(0x7EC, bms_0101(soc=37.5, voltage=256.5, current=5.5, cell_max=3.56))},
        {"tMs": 480, "header": "7E4", "command": "1902FF", "reply": "7EC 03 59 02 FF\r\r"},
        {"tMs": 700, "header": "7E4", "command": "220105", "reply": "NO DATA\r\r"},
    ],
}


def test_capture_requests_follow_active_rules(app, client, make_user):
    make_user("tester1")
    headers = api_login(client, "tester1")
    assert client.get("/api/canCaptureRequests", headers=headers).get_json() == {"data": []}

    _activate(app, "soc", Layout(0x7E4, 0x0101, 4, 1, scale=0.5))
    body = client.get("/api/canCaptureRequests", headers=headers).get_json()

    assert body["data"] == [
        {"header": "7E4", "command": "220101"},
        {"header": "7E4", "command": "1902FF"},
        {"header": "7E4", "command": "22F190"},
    ]


def test_capture_requests_with_car_no_use_that_cars_rules(app, client, make_user, monkeypatch):
    cars = {"12가3456": {"diag_company": "기아", "diag_model": "EV6"},
            "34나5678": {"diag_company": "현대", "diag_model": "아이오닉5"}}

    def lookup(user, car_no, refresh=False):
        if car_no not in cars:
            raise car_info.CarInfoError("조회 결과 없음", 404, "not_found")
        return cars[car_no], True

    monkeypatch.setattr(car_info, "lookup", lookup)
    make_user("tester1")
    headers = api_login(client, "tester1")
    with app.app_context():
        layout = Layout(0x7E4, 0x0101, 4, 1, scale=0.5)
        db.session.add(DecodeRule(signal_key="soc", revision=1, status=RuleStatus.ACTIVE, confidence=0.9,
                                  evidence={}, formula=layout.formula(), maker="기아", model="EV6",
                                  **layout.to_dict()))
        db.session.commit()

    def requests(car_no=None):
        query = {"carNo": car_no} if car_no else {}
        return client.get("/api/canCaptureRequests", headers=headers, query_string=query).get_json()["data"]

    assert {"header": "7E4", "command": "220101"} in requests("12가3456")
    assert requests("34나5678") == []
    fallback = requests()
    assert {"header": "7E4", "command": "220101"} in fallback and requests("99하9999") == fallback


def test_capture_upload_returns_result_sheet_from_active_rules(app, client, make_user):
    make_user("tester1")
    _activate(app, "soc", Layout(0x7E4, 0x0101, 4, 1, scale=0.5))
    _activate(app, "pack_voltage", Layout(0x7E4, 0x0101, 12, 2, scale=0.1))
    headers = api_login(client, "tester1")

    response = client.post("/api/canCaptures", headers=headers, json=CAPTURE)

    assert response.status_code == 201
    body = response.get_json()
    assert body["message"] == "생성되었습니다."
    data = body["data"]
    assert data["kind"] == "live_capture" and data["vehicle"] == "그랜저 HEV"
    assert data["transactions"] == 3 and data["dids"] == ["7E4 0101"]
    assert data["report"]["values"]["soc"] == {"label": "배터리 충전 상태(BMS)", "value": 37.5, "unit": "%"}
    assert data["report"]["values"]["packVoltage"]["value"] == 256.5
    assert data["report"]["dtcs"] == [] and data["report"]["dtcCheckedEcus"] == ["7E4"]
    with app.app_context():
        dataset = db.session.scalar(select(CanDataset))
        assert (dataset.source, dataset.kind) == ("app", "live_capture")
        content = db.session.scalar(select(CanDataset.content))
        assert content.decode().startswith("# WECAR-ELM 1\n# vehicle: 그랜저 HEV\n")
        assert db.session.scalar(select(DiagnosticReport.dataset_id)) == dataset.id


def test_capture_upload_validates_input(client, make_user):
    make_user("tester1")
    headers = api_login(client, "tester1")

    assert client.post("/api/canCaptures", json=CAPTURE).status_code == 401

    missing = client.post("/api/canCaptures", headers=headers, json={"exchanges": CAPTURE["exchanges"]})
    assert missing.status_code == 422 and "vehicle" in missing.get_json()["errors"]

    bad = client.post("/api/canCaptures", headers=headers,
                      json={"vehicle": "x", "exchanges": [{"header": "7E4", "command": "ZZ", "reply": ""}]})
    assert bad.status_code == 422
    assert bad.get_json()["message"] == "exchanges[0]의 header·command는 16진수여야 합니다."

    silent = client.post("/api/canCaptures", headers=headers,
                         json={"vehicle": "x", "exchanges": [{"header": "7E4", "command": "220101", "reply": "NO DATA"}]})
    assert silent.status_code == 400
    assert "진단 요청·응답을 찾지 못했습니다" in silent.get_json()["message"]
