import httpx
from sqlalchemy import select

from app.extensions import db
from app.modules.scans import car_info
from app.modules.scans.models import Scan, ScanDocument
from tests.conftest import api_login

DTO = {"diag_car_id": "KMHK381GFMU000001", "diag_company": "현대", "diag_model": "코나 일렉트릭",
       "diag_year": 2021, "diag_fuel": "전기", "diag_displacement": ""}


def _fake_post(monkeypatch, body):
    calls = []

    def fake(url, data, timeout):
        calls.append(data)
        return httpx.Response(200, json=body)

    monkeypatch.setattr(car_info.httpx, "post", fake)
    return calls


def test_scan_plan_uses_car_info_and_web_plan(client, make_user, monkeypatch):
    calls = _fake_post(monkeypatch, {"status": "ok", "msg": "정상 처리되었습니다.", "dto": DTO})
    make_user("tester1")
    headers = api_login(client, "tester1")

    assert client.get("/api/scanPlan?carNo=12가3456").status_code == 401
    response = client.get("/api/scanPlan?carNo=12가 3456", headers=headers)

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["carNo"] == "12가3456" and data["car"]["diagModel"] == "코나 일렉트릭"
    assert data["lookupError"] is None and len(calls) == 1
    steps = data["steps"]
    assert [s["command"] for s in steps[:3]] == ["ATRV", "0100", "ATDPN"]
    assert any(s.get("expand") == "pids" for s in steps)
    assert any(s["command"] == "220101" and s["header"] == "7E4" for s in steps)
    assert any(s.get("header29") == "18DA10F1" for s in steps)


def test_scan_plan_without_car_info_still_returns_generic_plan(client, make_user, monkeypatch):
    _fake_post(monkeypatch, {"status": "fail", "msg": "일제한 초과"})
    make_user("tester1")
    headers = api_login(client, "tester1")

    data = client.get("/api/scanPlan?carNo=12가3456", headers=headers).get_json()["data"]

    assert data["car"] is None and data["lookupError"]
    assert data["steps"][0]["command"] == "ATRV"
    assert not any(s["command"] == "220101" for s in data["steps"])

    missing = client.get("/api/scanPlan", headers=headers)
    assert missing.status_code == 400 and missing.get_json()["message"] == "차량번호를 입력해주세요."


def test_scan_run_saves_scan_and_returns_pdf_url(app, client, make_user):
    make_user("tester1")
    headers = api_login(client, "tester1")
    body = {
        "carNo": "12가3456", "car": DTO, "transport": "ble", "device": "vLinker MC+", "dialect": "stn",
        "steps": [
            {"command": "ATRV", "reply": "12.4V\r\r>", "group": "device"},
            {"command": "0100", "reply": "7E8 06 41 00 98 3B 80 13\r\r>"},
            {"command": "ATDPN", "reply": "A6\r\r>", "group": "device"},
            {"command": "03", "reply": "7E8 04 43 01 01 33\r\r>", "group": "dtc"},
            {"command": "07", "reply": None, "error": "timeout", "group": "dtc"},
        ],
    }

    assert client.post("/api/scanRuns", json=body).status_code == 401
    response = client.post("/api/scanRuns", headers=headers, json=body)

    assert response.status_code == 201, response.get_json()
    payload = response.get_json()
    assert payload["message"] == "생성되었습니다."
    data = payload["data"]
    assert data["status"] == "partial" and data["errors"][0]["command"] == "07"
    assert data["errors"][0]["statusLabel"] and data["pdfUrl"] == f"/api/scans/{data['id']}/pdf?download=1"
    with app.app_context():
        scan = db.session.get(Scan, data["id"])
        assert scan.car_no == "12가3456" and scan.device_type == "ble" and scan.raw == ["P0133"]
        assert scan.bms_data["dialect"] == "stn"
        assert db.session.scalar(select(ScanDocument.scan_id)) == scan.id

    pdf = client.get(data["pdfUrl"], headers=headers)
    assert pdf.status_code == 200 and pdf.mimetype == "application/pdf" and pdf.data.startswith(b"%PDF")
    legacy = client.get(f"/api/scans/{data['id']}/pdf", headers=headers)
    assert legacy.get_json() == {"message": "PDF가 성공적으로 생성되었습니다. [테스트!]", "scanId": str(data["id"])}

    make_user("tester2")
    other = api_login(client, "tester2")
    assert client.get(data["pdfUrl"], headers=other).status_code in (403, 404)


def test_scan_run_validates_input(client, make_user):
    make_user("tester1")
    headers = api_login(client, "tester1")

    no_steps = client.post("/api/scanRuns", headers=headers, json={"carNo": "12가3456", "transport": "ble"})
    assert no_steps.status_code == 400 and no_steps.get_json()["message"] == "스캔 단계 결과가 없습니다."

    bad = client.post("/api/scanRuns", headers=headers, json={
        "carNo": "12가3456", "transport": "ble", "steps": [{"command": "rm -rf", "reply": ""}]})
    assert bad.status_code == 400 and "명령 또는 주소" in bad.get_json()["message"]

    transport = client.post("/api/scanRuns", headers=headers, json={
        "carNo": "12가3456", "transport": "usb", "steps": [{"command": "03", "reply": "NO DATA"}]})
    assert transport.status_code == 400 and transport.get_json()["message"] == "연결 방식을 확인하세요."
