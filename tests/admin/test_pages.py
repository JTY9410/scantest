from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core import audit
from app.extensions import db
from app.modules.reports.models import Applog, CarMismatchReport
from app.modules.scans.models import Code, Scan, ScanCode
from tests.conftest import csrf_token


@pytest.fixture
def sample_data(app, admin_client, make_user, make_company):
    company_id = make_company("ACME", "에이씨엠이")
    tester_id = make_user("kim01", name="김테스터", company_id=company_id)
    with app.app_context():
        code = Code(type="ev", code="P0A80", unit_name="BMS", desc="배터리 교체 필요")
        scan = Scan(type="ev", device_type="obd", device_uid="u1", tester_id=tester_id,
                    company_id=company_id, car_no="12가3456", car_vin="KMH0000000000001",
                    car_model="아이오닉5", car_distance=12345, car_battery_capacity=Decimal("72.6"))
        db.session.add_all([code, scan])
        db.session.flush()
        db.session.add(ScanCode(type="ev", scan_id=scan.id, code_id=code.id))
        db.session.add(Applog(timestamp=datetime.now(UTC), user_id=tester_id, type="error",
                              message="블루투스 연결 실패", desc="stack"))
        db.session.add(CarMismatchReport(user_id=tester_id, car_no="12가3456",
                                         api_vin="A" * 17, scan_vin="B" * 17))
        audit.record("테스트 기록", "Scan", scan.id, user_id=tester_id, changes={"메모": "한글"})
        db.session.commit()
        return {"scan_id": scan.id, "code_id": code.id, "company_id": company_id}


PAGES = [
    ("/admin/", "대시보드"),
    ("/admin/members/", "김테스터"),
    ("/admin/scans", "12가3456"),
    ("/admin/scans?type=ev&start=2020-01-01&end=2099-12-31", "12가3456"),
    ("/admin/reports", "12가3456"),
    ("/admin/applogs?type=error", "블루투스 연결 실패"),
    ("/admin/activities", "테스트 기록"),
    ("/admin/companies", "에이씨엠이"),
    ("/admin/codes?type=ev&q=P0A", "P0A80"),
    ("/admin/codes/new", "진단코드 등록"),
    ("/admin/companies/new", "회사 등록"),
    ("/admin/ai", "AI 연결"),
    ("/admin/ai/gemini", "Google Gemini"),
    ("/admin/obd/", "OBD2 연결"),
    ("/admin/obd/new", "OBD2 프로필 등록"),
    ("/admin/car-info", "차량정보 조회"),
    ("/admin/scan/", "차량번호 조회하기"),
    ("/admin/account", "2단계 인증"),
]


@pytest.mark.parametrize(("url", "expected"), PAGES)
def test_admin_pages_render(sample_data, admin_client, url, expected):
    response = admin_client.get(url)

    assert response.status_code == 200, url
    html = response.get_data(as_text=True)
    assert expected in html
    assert "755-81-02354" in html, "공통 푸터가 없습니다"
    assert response.headers["Cache-Control"] == "no-store"


def test_scan_detail_and_activity_json_keep_korean(sample_data, admin_client):
    detail = admin_client.get(f"/admin/scans/{sample_data['scan_id']}").get_data(as_text=True)
    assert "P0A80" in detail and "12,345 km" in detail

    activities = admin_client.get("/admin/activities").get_data(as_text=True)
    assert "&#34;메모&#34;: &#34;한글&#34;" in activities or '"메모": "한글"' in activities


def test_company_and_code_can_be_created_and_edited(app, sample_data, admin_client):
    token = csrf_token(admin_client, "/admin/companies/new")
    created = admin_client.post("/admin/companies/new",
                                data={"csrf_token": token, "code": "NEWCO", "name": "새회사"})
    assert created.status_code == 302

    duplicate = admin_client.post("/admin/companies/new",
                                  data={"csrf_token": token, "code": "NEWCO", "name": "중복"})
    assert "이미 사용 중인 기업코드입니다." in duplicate.get_data(as_text=True)

    edited = admin_client.post(f"/admin/codes/{sample_data['code_id']}/edit",
                               data={"csrf_token": token, "type": "ev", "code": "P0A80",
                                     "unit_name": "BMS", "desc": "설명 수정"})
    assert edited.status_code == 302
    with app.app_context():
        assert db.session.get(Code, sample_data["code_id"]).desc == "설명 수정"


def test_member_filter_links_from_detail(sample_data, admin_client):
    html = admin_client.get("/admin/scans?user_id=2").get_data(as_text=True)

    assert "회원: 김테스터 (kim01)" in html and "12가3456" in html


def test_missing_scan_shows_error_page(sample_data, admin_client):
    response = admin_client.get("/admin/scans/9999")

    assert response.status_code == 404
    assert "스캔 기록을 찾을 수 없습니다." in response.get_data(as_text=True)


def test_public_endpoints(client):
    assert client.get("/").headers["Location"].endswith("/admin/")
    assert client.get("/up").get_json() == {"status": "ok"}

    worker = client.get("/service-worker.js")
    assert worker.headers["Cache-Control"] == "no-cache"
    assert "__ASSET_VERSION__" not in worker.get_data(as_text=True)
    assert 'startsWith("/static/")' in worker.get_data(as_text=True)

    manifest = client.get("/static/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.get_json()["scope"] == "/admin/"
    assert "max-age=31536000" not in manifest.headers.get("Cache-Control", "")

    versioned = client.get("/static/js/app.js?v=abc")
    assert "max-age=31536000" in versioned.headers["Cache-Control"]


def test_install_hint_flag_only_on_first_page_after_login(admin_client):
    first = admin_client.get("/admin/").get_data(as_text=True)
    second = admin_client.get("/admin/").get_data(as_text=True)

    assert 'data-first-login="true"' in first
    assert 'data-first-login="false"' in second
