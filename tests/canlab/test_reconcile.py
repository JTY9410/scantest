"""완료 데이터 대조: 위스캔 통신기록 + 리버스데이터만으로 최종결과."""
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.modules.canlab.engine.decode import load_trace
from app.modules.canlab.engine.frames import decode_text
from app.modules.canlab.engine.reconcile import (
    CONFIRMED, LIKELY, UNKNOWN, _compare, _grade, coverage, final_values, parse_table, reconcile,
)
from app.modules.canlab.models import AnalysisRun, DecodeRule
from app.modules.scans import car_info
from app.modules.scans.models import Scan
from tests.conftest import csrf_token

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "csv"
CAR_NO = "12가3456"
CAR = {"diag_company": "현대", "diag_model": "아이오닉5", "diag_submodel": "아이오닉5 롱레인지", "diag_year": 2022,
       "diag_fuel": "전기", "diag_car_id": "KMHTEST0000000001"}


def _trace(name):
    return load_trace(decode_text((FIX / name).read_bytes()))


@pytest.fixture(autouse=True)
def fake_lookup(monkeypatch):
    monkeypatch.setattr(car_info, "lookup", lambda user, car_no, refresh=False: (dict(CAR), False))


def test_reconcile_fixture_pair_matches_with_grades():
    result = reconcile(_trace("ev_a_wescan.csv"), [_trace("ev_a_gscan.csv")], kind="ev", model_hint="아이오닉5")
    assert result["vin"]["status"] == "없음" and result["platform"] == "egmp"
    assert result["counts"].get("불일치", 0) == 0 and result["counts"]["일치"] >= 30
    soh = next(i for i in result["items"] if i["key"] == "soh")
    assert soh["status"] == "일치" and soh["grade"] == CONFIRMED and soh["source"] == "bms"
    final = final_values(result)
    assert "soh" in final and final["soh"]["value"] == soh["wescan"]
    assert result["coverage"]["required"][0]["wescan"]


def test_compare_and_grade_rules():
    assert _compare("soh", 97.2, [97.2])[0] == "일치"
    assert _compare("soh", 97.2, [96.0])[0] == "불일치"
    assert _compare("pack_current", 1.0, [-5.0, 3.0])[0] == "일치"
    assert _compare("cum_charge_ah", 1000.5, [1000.0])[0] == "일치"
    assert _compare("cum_charge_ah", 990.0, [1000.0])[0] == "불일치"
    assert _grade(CONFIRMED, "일치") == CONFIRMED
    assert _grade(LIKELY, "일치") == LIKELY
    assert _grade(CONFIRMED, "위스캔에만") == LIKELY
    assert _grade(LIKELY, "위스캔에만") == UNKNOWN
    assert _grade(CONFIRMED, "불일치") == UNKNOWN and _grade(CONFIRMED, "정의만") == UNKNOWN


def test_coverage_and_table():
    cov = coverage("ice", [("7E0", "1902FF"), ("7E0", "0100")], [("7E0", "0100")])
    assert cov["required_ratio"] == 0 and cov["common"] == 1
    defs = parse_table("signal_key,header,did,start,width,scale,unit,label\nldc_voltage,7E6,C101,4,2,0.01,V,LDC 출력\n")
    assert defs[0].key == "ldc_voltage" and defs[0].request_id == 0x7E6 and defs[0].grade == LIKELY
    with pytest.raises(ValueError):
        parse_table("signal_key,header\nx,zz\n")


def test_mismatch_makes_value_unknown_and_report_on_hold():
    from app.modules.scanner.report import type_judgments
    w, g = _trace("ev_a_wescan.csv"), _trace("ev_a_gscan.csv")
    for key, rows in list(g.samples.items()):
        if key == (0x7E4, 0x0105):
            g.samples[key] = [(t, p[:25] + bytes([0x00, 0x10]) + p[27:]) for t, p in rows]  # SOH 1.6%
    result = reconcile(w, [g], kind="ev", model_hint="아이오닉5")
    soh = next(i for i in result["items"] if i["key"] == "soh")
    assert soh["status"] == "불일치" and soh["grade"] == UNKNOWN
    rows = type_judgments({"battery": final_values(result), "cells": result["cells"] or {}}, "ev")
    assert rows[0]["result"] == "측정불가"


def _upload(client, url, **extra):
    data = {"csrf_token": csrf_token(client, url), "car_no": CAR_NO,
            "wescan_file": ((FIX / "ev_a_wescan.csv").open("rb"), "w.csv"),
            "reverse_files": [((FIX / "ev_a_gscan.csv").open("rb"), "g.csv")], **extra}
    return client.post(url, data=data, content_type="multipart/form-data")


def test_reconcile_web_flow_requires_vin_confirm_then_finalizes_scan(app, admin_client):
    url = "/admin/canlab/reconcile"
    page = admin_client.get(url).get_data(as_text=True)
    assert "완료 데이터 올리기" in page
    missing = _upload(admin_client, url)
    assert missing.status_code == 400 and "직접 확인" in missing.get_data(as_text=True)
    with app.app_context():
        rules_before = db.session.scalar(select(func.count()).select_from(DecodeRule))
    done = _upload(admin_client, url, vin_confirmed="y")
    assert done.status_code == 302
    with app.app_context():
        run = db.session.scalar(select(AnalysisRun).where(AnalysisRun.mode == "reconcile"))
        assert run.result["vin"]["manual"] and run.result["powertrain"]["type"] == "ev"
        assert db.session.scalar(select(func.count()).select_from(DecodeRule)) == rules_before
        run_id = run.id
    view = admin_client.get(f"/admin/canlab/reconcile/{run_id}").get_data(as_text=True)
    assert "항목 대조" in view and "확인됨" in view and "최종결과로 확정" in view
    assert admin_client.get(f"/admin/canlab/analysis/{run_id}").status_code == 302
    token = csrf_token(admin_client, f"/admin/canlab/reconcile/{run_id}")
    final = admin_client.post(f"/admin/canlab/reconcile/{run_id}/finalize", data={"csrf_token": token})
    assert final.status_code == 302 and "/admin/scan/" in final.headers["Location"]
    again = admin_client.post(f"/admin/canlab/reconcile/{run_id}/finalize", data={"csrf_token": token})
    with app.app_context():
        scans = db.session.scalars(select(Scan)).all()
        assert len(scans) == 1 and scans[0].bms_data["source"] == "reconcile" and scans[0].type == "ev"
        assert "soh" in scans[0].bms_data["battery"]
        scan_id = scans[0].id
    assert again.headers["Location"].endswith(f"/admin/scan/{scan_id}")
    assert admin_client.get(f"/admin/scan/{scan_id}").status_code == 200
    report = admin_client.get(f"/admin/scan/{scan_id}/report").get_data(as_text=True)
    assert "EV 기술 진단 보고서" in report and "대조 근거" in report and "(확인됨)" in report
    pdf = admin_client.get(f"/admin/scan/{scan_id}/pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    listing = admin_client.get("/admin/scans").get_data(as_text=True)
    assert "완료 데이터 대조" in listing
    assert "데이터입력분석" in admin_client.get("/admin/canlab/analysis").get_data(as_text=True)


def test_vin_mismatch_stops(app, admin_client, monkeypatch):
    from app.modules.canlab.engine import uds
    calls = iter(["KMHTEST0000000001", "KMHTEST0000000002"])
    monkeypatch.setattr(uds, "find_vin", lambda tx: next(calls, None))
    response = _upload(admin_client, "/admin/canlab/reconcile")
    assert response.status_code == 400 and "VIN이 다릅니다" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(AnalysisRun)) == 0
