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
    assert "차량번호 조회하기" in html and "블루투스 클래식·USB" in html and "data-scan-config" in html
    assert html.index("스캔하기</span>") < html.index("운영 데이터")
    assert html.index("진단기 연결") < html.index("data-scan-flow")
    assert "차량정보 조회 인증키가 없어" not in html
    dashboard = admin_client.get("/admin/").get_data(as_text=True)
    # 대시보드 스캔하기는 같은 페이지의 연결을 쓰는 카드 안 흐름이다(이동하면 블루투스 연결이 끊긴다).
    assert "data-scan-jump" in dashboard and "data-scan-flow" in dashboard
    assert 'href="/admin/scan/">스캔하기' not in dashboard


def test_missing_car_info_key_is_warned(admin_client, monkeypatch):
    monkeypatch.setitem(admin_client.application.config, "CAR_INFO_API_KEY", None)
    for url in ("/admin/scan/", "/admin/"):
        assert "차량정보 조회 인증키가 없어 조회가 실패합니다" in admin_client.get(url).get_data(as_text=True)


def test_lookup_failure_is_audited(admin_client, monkeypatch):
    from sqlalchemy import select

    from app.core.audit import Activity
    from app.extensions import db

    _fake_post(monkeypatch, {"status": "fail", "msg": "일제한 초과"})
    assert _json(admin_client, "/admin/scan/lookup", {"carNo": "34나5678"}).status_code == 400
    with admin_client.application.app_context():
            activity = db.session.scalar(select(Activity).where(Activity.relation_type == "차량정보 조회 실패"))
    assert activity.changes["kind"] == "quota" and activity.changes["car_no"] == "34나5678"


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
               "0101": "7E8 06 41 01 81 07 65 04", "03": "7E8 04 43 01 01 33"}
    steps = [dict(s, reply=replies.get(s["command"]), error=None if s["command"] in replies else "skipped",
                  reason=None if s["command"] in replies else "사용자가 스캔을 중지했습니다.")
             for s in plan["steps"]]
    steps[-1].update(error="timeout", reason=None, reply=None)
    response = _json(admin_client, "/admin/scan/run", {"carNo": "12가3456", "car": DTO, "steps": steps,
                                                      "transport": "serial", "device": "USB 진단기",
                                                      "dialect": "slcan"})
    assert response.status_code == 201, response.get_json()
    saved = response.get_json()
    assert saved["status"] == "partial"
    unknown = _json(admin_client, "/admin/scan/run", {"carNo": "12가3456", "car": DTO, "steps": steps,
                                                     "transport": "serial", "dialect": "j2534"})
    assert unknown.status_code == 201
    from app.extensions import db
    from app.modules.scans.models import Scan

    with admin_client.application.app_context():
        assert db.session.get(Scan, saved["id"]).bms_data["dialect"] == "slcan"
        assert db.session.get(Scan, unknown.get_json()["id"]).bms_data["dialect"] is None

    html = admin_client.get(saved["url"]).get_data(as_text=True)
    assert "위스캔 결과" in html and "P0133" in html and "진단 요약" in html
    assert "오류 기록" in html and "시간 초과" in html and "ISO 15765-4 CAN" in html
    assert "분석 요약" in html and "배출 점검(레디니스)" in html and "불꽃 점화" in html
    show = admin_client.get(f"/admin/scans/{saved['id']}").get_data(as_text=True)
    assert "위스캔 결과" in show and "스캔 오류 1건" in show and f"/admin/scan/{saved['id']}/pdf" in show
    assert "/admin/canlab/datasets/" in show and "/admin/canlab/compare?dataset_id=" in show
    assert f"scan_id={saved['id']}" in show

    assert "data-pdf-auto" not in html
    assert "data-pdf-auto" in admin_client.get(f"{saved['url']}?pdf=1").get_data(as_text=True)
    pdf = admin_client.get(f"/admin/scan/{saved['id']}/pdf")
    assert pdf.status_code == 200 and pdf.mimetype == "application/pdf" and pdf.data.startswith(b"%PDF")
    assert "attachment" in pdf.headers["Content-Disposition"] and "filename*=UTF-8''" in pdf.headers[
        "Content-Disposition"]


def test_run_rejects_bad_input(admin_client):
    response = _json(admin_client, "/admin/scan/run", {"carNo": "12가3456", "steps": [], "transport": "ble"})
    assert response.status_code == 400 and response.get_json()["message"]
    response = _json(admin_client, "/admin/scan/run", {"carNo": "12가3456", "steps": [{"command": "03"}],
                                                      "transport": "carrier-pigeon"})
    assert response.status_code == 400
