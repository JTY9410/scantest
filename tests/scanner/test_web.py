import httpx

from app.modules.scans import car_info
from tests.conftest import csrf_token

DTO = {"diag_car_id": "KPBXH3AP1GP000000", "diag_company": "KG 모빌리티", "diag_model": "티볼리",
       "diag_year": 2016, "diag_fuel": "경유", "diag_displacement": 1597, "diag_capacity": ""}


def _fake_post(monkeypatch, body):
    def fake(url, data, timeout):
        return httpx.Response(200, json=body)

    monkeypatch.setattr(car_info.httpx, "post", fake)


def _json(client, url, body):
    token = csrf_token(client, "/admin/scan/")
    return client.post(url, json=body, headers={"X-CSRFToken": token})


def test_scan_page_menu_and_dashboard_button(admin_client):
    html = admin_client.get("/admin/scan/").get_data(as_text=True)
    assert "차량번호 조회하기" in html and "블루투스 클래식·USB" in html and 'id="scanner-config"' in html
    assert html.index("스캔하기</span>") < html.index("운영 데이터")
    dashboard = admin_client.get("/admin/").get_data(as_text=True)
    assert 'href="/admin/scan/"' in dashboard


def test_lookup_success_and_failure(admin_client, monkeypatch):
    _fake_post(monkeypatch, {"status": "ok", "msg": "정상 처리되었습니다.", "dto": DTO})
    response = _json(admin_client, "/admin/scan/lookup", {"carNo": "12가 3456"})
    data = response.get_json()
    assert response.status_code == 200 and data["car_no"] == "12가3456"
    assert data["car"]["diag_capacity"] is None and data["car"]["diag_model"] == "티볼리"

    _fake_post(monkeypatch, {"status": "fail", "msg": "일제한 초과"})
    response = _json(admin_client, "/admin/scan/lookup", {"carNo": "34나5678"})
    assert response.status_code == 400
    assert response.get_json()["kind"] == "quota" and response.get_json()["detail"] == "일제한 초과"


def test_scanner_requires_admin_and_csrf(client, admin_client):
    assert admin_client.post("/admin/scan/lookup", json={"carNo": "12가3456"}).status_code == 400
    assert client.application.test_client().get("/admin/scan/").status_code in (302, 401, 403)


def test_run_then_result_page_shows_wescan_format(admin_client):
    plan = _json(admin_client, "/admin/scan/plan", {"car": DTO}).get_json()
    assert plan["steps"][0]["command"] == "ATRV"
    replies = {"ATRV": "12.3V", "0100": "7E8 06 41 00 98 3B 80 13", "ATDPN": "A6",
               "03": "7E8 04 43 01 01 33"}
    steps = [dict(s, reply=replies.get(s["command"]), error=None if s["command"] in replies else "skipped",
                  reason=None if s["command"] in replies else "사용자가 스캔을 중지했습니다.")
             for s in plan["steps"]]
    steps[-1].update(error="timeout", reason=None, reply=None)
    response = _json(admin_client, "/admin/scan/run", {"carNo": "12가3456", "car": DTO, "steps": steps,
                                                      "transport": "serial", "device": "USB 진단기"})
    assert response.status_code == 201, response.get_json()
    saved = response.get_json()
    assert saved["status"] == "partial"

    html = admin_client.get(saved["url"]).get_data(as_text=True)
    assert "위스캔 결과" in html and "P0133" in html and "진단 요약" in html
    assert "오류 기록" in html and "시간 초과" in html and "ISO 15765-4 CAN" in html
    show = admin_client.get(f"/admin/scans/{saved['id']}").get_data(as_text=True)
    assert "위스캔 결과" in show and "스캔 오류 1건" in show


def test_run_rejects_bad_input(admin_client):
    response = _json(admin_client, "/admin/scan/run", {"carNo": "12가3456", "steps": [], "transport": "ble"})
    assert response.status_code == 400 and response.get_json()["message"]
    response = _json(admin_client, "/admin/scan/run", {"carNo": "12가3456", "steps": [{"command": "03"}],
                                                      "transport": "carrier-pigeon"})
    assert response.status_code == 400
