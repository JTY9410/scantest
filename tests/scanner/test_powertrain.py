"""차량 유형(전기차·하이브리드·내연기관) 판별과 유형별 보고서·판정."""
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.modules.scanner.powertrain import classify
from app.modules.scanner.report import dtc_groups, inspection, overall, type_judgments


@pytest.mark.parametrize("fuel, model, kind, source, plugin, hydrogen", [
    ("전기", "EV3", "ev", "fuel", False, False),
    ("하이브리드(휘발유+전기)", "쏘렌토", "hev", "fuel", False, False),
    ("플러그인 하이브리드", "니로", "hev", "fuel", True, False),
    ("엘피지", "K5", "ice", "fuel", False, False),
    ("경유", "포터", "ice", "fuel", False, False),
    ("휘발유", "아반떼 하이브리드", "hev", "model", False, False),
    ("가솔린", "마일드 하이브리드", "ice", "fuel", False, False),
    ("수소", "넥쏘", "ev", "fuel", False, True),
    ("", "아이오닉 5", "ev", "model", False, False),
    ("", "코나 EV", "ev", "model", False, False),
    ("", "투싼 HEV", "hev", "model", False, False),
    ("", "K5", "ice", "default", False, False),
])
def test_classify_by_fuel_and_model(fuel, model, kind, source, plugin, hydrogen):
    got = classify({"diag_fuel": fuel, "diag_model": model})
    assert (got["type"], got["source"], got["plugin"], got["hydrogen"]) == (kind, source, plugin, hydrogen)


def test_hybrid_with_bms_soc_is_not_ev():
    """예전에는 SOC를 읽으면 전기차로 저장했다. 하이브리드 배터리(72셀)는 하이브리드다."""
    got = classify({}, {"battery": {"soc": {"value": 50}}, "cells": {"count": 72}})
    assert got["type"] == "hev" and got["source"] == "bms"


def test_classify_by_ecu_and_manual():
    steps = [{"header": "7E5", "status": "ok"}, {"header": "7E0", "status": "ok"}, {"header": "7E7", "status": "ok"}]
    got = classify({}, {"steps": steps})
    assert got["type"] == "hev" and got["plugin"] and got["source"] == "ecu"
    assert classify({}, {"steps": steps[:1]})["type"] == "ev"
    assert classify({"diag_fuel": "전기"}, manual="ice")["type"] == "ice"
    assert classify({"diag_fuel": "전기"}, manual="ice")["source"] == "manual"


def test_overall_rules():
    ok = {"result": "양호"}
    unread = {"result": "측정불가"}
    bad = {"result": "주의"}
    assert overall([ok, ok], 0) == "양호"
    assert overall([ok, unread], 0) == "판정보류"
    assert overall([ok, unread], 1) == "점검요"
    assert overall([bad, unread], 0) == "점검요"
    assert overall([], 0) == "양호"
    assert overall([], 0, dtc_read=False) == "판정보류"


def test_type_judgments_items():
    ev = type_judgments({}, "ev")
    hev = type_judgments({}, "hev")
    assert len(ev) == 7 and len(hev) == 7
    assert ev[0]["item"] == "배터리 수명 (SOH)" and "SOH" not in " ".join(r["item"] for r in hev)
    assert all(r["result"] == "측정불가" for r in ev + hev)
    assert type_judgments({}, "ice") == []
    full = {"battery": {k: {"value": v} for k, v in {
        "isolation_kohm": 1000, "ldc_voltage": 14.3, "aux_voltage": 13.8, "max_temp": 21, "min_temp": 21,
        "motor_temp_front": 20.97, "inverter_temp_front": 27.21,
        "motor_offset_u_front": -10, "motor_offset_v_front": -5, "motor_offset_w_front": -12}.items()},
        "cells": {"max": 3.70, "min": 3.68}}
    rows = type_judgments(full, "hev")
    assert [r["result"] for r in rows] == ["양호"] * 7
    assert rows[-1]["value"] == 7 and rows[-2]["value"] == 6.2


def test_dtc_groups_by_type():
    dtcs = {"dtcs": [{"code": "P0300", "ecu": "7E8"}, {"code": "P0A80", "ecu": "7EC"}, {"code": "U0100", "ecu": "7D1"},
                     {"code": "P0700", "ecu": "7E9"}]}
    ice = {g["key"]: g["count"] for g in dtc_groups(dtcs, "ice")}
    assert list(ice) == ["engine", "tm", "other", "chassis", "body", "network"]
    assert ice == {"engine": 1, "tm": 1, "other": 1, "chassis": 0, "body": 0, "network": 1}
    hev = {g["key"]: g["count"] for g in dtc_groups(dtcs, "hev")}
    assert len(hev) == 8 and hev["bms"] == 1 and hev["engine"] == 1
    assert len(dtc_groups(dtcs, "phev")) == 9 and len(dtc_groups(dtcs, "ev")) == 8


def _scan(kind, **extra):
    return SimpleNamespace(id=7, created_at=datetime(2026, 11, 4, tzinfo=UTC), car_no="12가3456",
                           car_maker="기아", car_model="모델", car_year=2023, car_fuel=extra.get("fuel"),
                           car_vin="KNATEST0000000001", car_distance=1000, type=kind, type_source="fuel")


def test_inspection_per_type_and_pdf_pages():
    from pypdf import PdfReader
    from io import BytesIO

    from app.modules.scanner import pdf

    ice_result = {"dtcs": [], "values": [], "steps": [{"header": "7E0", "status": "ok"}], "battery": {}}
    view = inspection(_scan("ice", fuel="엘피지"), ice_result)
    assert view["kind"] == "ice" and view["heading"] == "자동차 DTC 진단 보고서"
    assert len(view["groups"]) == 6 and view["overall"] == "양호" and view["bms"] == []
    hev_result = {"battery": {"soc": {"value": 50}}, "cells": {"max": 3.7, "min": 3.68, "count": 72},
                  "dtcs": [], "values": [], "steps": []}
    hv = inspection(_scan("hev", fuel="하이브리드"), hev_result)
    assert hv["heading"] == "HEV 기술 진단 보고서" and [g["label"] for g in hv["groups"]][:2] == ["엔진", "변속기"]
    assert hv["overall"] == "판정보류"
    ev = inspection(_scan("ev", fuel="수소"), {"battery": {}, "dtcs": [], "values": [], "steps": []})
    assert ev["kind"] == "ev" and ev["hydrogen"]
    for kind, result, pages in (("ev", hev_result, 5), ("hev", hev_result, 5), ("ice", ice_result, 2)):
        content = pdf.render(_scan(kind), result)
        assert len(PdfReader(BytesIO(content)).pages) == pages, kind


def test_change_type_on_result_page_keeps_history(app, admin_client):
    from sqlalchemy import select

    from app.core.audit import Activity
    from app.extensions import db
    from app.modules.accounts.models import User
    from app.modules.scanner import service
    from app.modules.scans.models import Scan
    from tests.conftest import csrf_token
    from tests.scanner.test_clear_flow import CAR_NO, DTO, READ_STEPS

    with app.app_context():
        user = db.session.scalar(select(User).where(User.tid == "wecar"))
        scan = service.run_scan(user, car_no=CAR_NO, car=DTO, steps=READ_STEPS, transport="ble")
        scan_id, first = scan.id, scan.type
    assert first == "ice"
    page = admin_client.get(f"/admin/scan/{scan_id}").get_data(as_text=True)
    assert "차량 유형" in page and "유형 바꾸기" in page
    token = csrf_token(admin_client, f"/admin/scan/{scan_id}")
    response = admin_client.post(f"/admin/scan/{scan_id}/type",
                                 data={"csrf_token": token, "type": "hev", "reason": "하이브리드 차량"})
    assert response.status_code == 302
    with app.app_context():
        scan = db.session.get(Scan, scan_id)
        assert scan.type == "hev" and scan.type_source == "manual"
        assert scan.type_history[-1]["from"] == "ice" and scan.type_history[-1]["to"] == "hev"
        assert db.session.scalar(select(Activity).where(Activity.relation_type == "스캔 유형 변경")) is not None
    report = admin_client.get(f"/admin/scan/{scan_id}/report").get_data(as_text=True)
    assert "HEV 기술 진단 보고서" in report and "변속기" in report
    bad = admin_client.post(f"/admin/scan/{scan_id}/type", data={"csrf_token": token, "type": "x"})
    assert bad.status_code == 302
    tabs = admin_client.get("/admin/scans?type=hev").get_data(as_text=True)
    assert "하이브리드" in tabs and 'aria-current="page"' in tabs and CAR_NO in tabs
    assert CAR_NO not in admin_client.get("/admin/scans?type=ev").get_data(as_text=True).split("스캔 목록")[-1]
