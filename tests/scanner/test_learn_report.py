from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.modules.accounts.models import User
from app.modules.scanner.learn import learned_requests, remember
from app.modules.scanner.plan import build_plan
from app.modules.scanner.report import basic_report
from app.modules.scans.models import MakerScanCommand, Scan


KONA = {"diag_company": "현대", "diag_model": "코나 일렉트릭", "diag_year": "2021", "diag_fuel": "전기",
        "diag_car_id": "KMHTEST0000000001"}
AVANTE = {"diag_company": "현대", "diag_model": "아반떼", "diag_year": "2019", "diag_fuel": "휘발유"}


def test_plan_has_wecar_reads_sweep_and_no_clear(app):
    with app.app_context():
        steps = build_plan(KONA)["steps"]
    plain = {(s["header"], s["command"]) for s in steps}
    assert (None, "03") in plain and (None, "0902") in plain and ("7E4", "220101") in plain
    assert ("7C6", "22B002") in plain and ("7E5", "221050") in plain
    assert ("7A0", "1902FF") in plain and ("797", "1902FF") in plain
    assert not any(cmd.startswith("ATSH") or cmd == "1902FFFFFF" for _, cmd in plain)
    assert not any(cmd[:2] in {"04", "14", "10", "27", "2E", "31"} for _, cmd in plain if not cmd.startswith("AT"))


def test_remember_only_successful_reads_and_prefers_model(app, admin):
    scan = service_scan(admin)
    remember(scan, [
        {"status": "ok", "command": "010C", "header": None},
        {"status": "ok", "command": "ATSH7E0"},
        {"status": "ok", "command": "04"},
        {"status": "ok", "command": "14FFFFFF"},
        {"status": "ok", "command": "2EF190", "header": "7E0"},
        {"status": "no_data", "command": "010D"},
        {"status": "negative", "command": "220101", "header": "7E4"},
        {"status": "device_error", "command": "0105"},
        {"status": "ok", "command": "220101", "header": "7E4"},
    ])
    db.session.commit()
    rows = {(r.model, r.header, r.command, r.hits) for r in db.session.scalars(select(MakerScanCommand))}
    assert ("코나 일렉트릭", None, "010C", 1) in rows
    assert ("코나 일렉트릭", "7E4", "220101", 1) in rows
    assert (None, None, "010C", 1) in rows
    assert not any(cmd in {"04", "14FFFFFF", "ATSH7E0", "010D", "2EF190"} for *_, cmd, _ in rows)

    remember(scan, [{"status": "ok", "command": "010C"}])
    db.session.commit()
    hits = db.session.scalar(select(MakerScanCommand.hits).where(
        MakerScanCommand.model == "코나 일렉트릭", MakerScanCommand.command == "010C"))
    assert hits == 2

    learned = learned_requests(KONA)
    assert {(r["header"], r["command"]) for r in learned} == {(None, "010C"), ("7E4", "220101")}
    avante = {(r["header"], r["command"]) for r in learned_requests(AVANTE)}
    assert avante == {(None, "010C"), ("7E4", "220101")}

    steps = build_plan(AVANTE)["steps"]
    learned_steps = [s for s in steps if s["group"] == "learned"]
    assert any(s["command"] == "220101" and s["optional"] for s in learned_steps)


def test_remember_caps_at_forty(app, admin):
    scan = service_scan(admin)
    remember(scan, [{"status": "ok", "command": f"22{i:04X}", "header": "7E4"} for i in range(45)])
    db.session.commit()
    count = db.session.scalar(select(func.count()).select_from(MakerScanCommand).where(
        MakerScanCommand.model == "코나 일렉트릭"))
    assert count == 40


def test_basic_report_shape(app):
    when = datetime(2026, 10, 18, tzinfo=UTC)
    report = basic_report(
        scan_id=7, diagnosed_at=when, car_no="12가3456", car=KONA,
        result={
            "vin": "KMHTEST0000000001",
            "values": [{"key": "odometer", "value": 12345}],
            "battery": {"soc": {"value": 80}, "pack_voltage": {"value": 360.5}, "module_temp_1": {"value": 25}},
            "cells": {"values": [{"no": 1, "voltage": 3.7}], "min": 3.7, "max": 3.7},
            "dtcs": [{"code": "P0A80", "kind": "확정", "ecu": "7EC", "desc": "배터리"}],
            "steps": [
                {"header": "7E0", "status": "no_data", "command": "1902FF"},
                {"header": "7E4", "status": "ok", "command": "220101"},
            ],
        },
        report_id=9, pdf_url="/admin/scan/7/pdf", app_version="2.0.0", app_type="web",
    )
    assert report["diagnosis_info"]["diagnosis_type"] == "BASIC"
    assert report["diagnosis_info"]["app_type"] == "web"
    assert report["vehicle"]["vehicle_number"] == "12가3456"
    assert report["vehicle"]["vin"] == "KMHTEST0000000001"
    assert report["sensor"]["ice"] is None
    assert report["sensor"]["ev"]["bms_soc"] == 80
    assert report["sensor"]["ev"]["bms_cell_voltages"] == [3.7]
    assert report["sensor"]["ev"]["bms_module_temperatures"] == [25]
    names = {e["ecu_name"]: e for e in report["dtc"]["enhanced"]["ecus"]}
    assert names["엔진"] == {"ecu_name": "엔진", "comm_status": "fail", "code_count": None}
    assert names["배터리"]["comm_status"] == "success"
    assert names["배터리"]["codes"][0]["code"] == "P0A80"

    ice = basic_report(
        scan_id=1, diagnosed_at=when, car_no="34나5678", car=AVANTE,
        result={"values": [{"key": "odometer", "value": 10}], "battery": {}, "dtcs": [], "steps": []},
        report_id=1, pdf_url=None, app_type="app",
    )
    assert ice["sensor"]["ice"] == {"vehicle_mileage": 10}
    assert ice["sensor"]["ev"] is None
    assert "vin" not in ice["vehicle"]


@pytest.fixture
def admin(app, make_user):
    make_user("scanner", type="admin")
    with app.app_context():
        yield db.session.scalar(select(User).where(User.tid == "scanner"))


def test_commands_page_filters_by_maker(admin_client, app, admin):
    with app.app_context():
        remember(service_scan(admin), [{"status": "ok", "command": "010C"}])
        db.session.commit()
    html = admin_client.get("/admin/scans/commands?maker=현대").get_data(as_text=True)
    assert "010C" in html and "코나 일렉트릭" in html
    assert "아직 기억한 명령이 없습니다" not in html
    empty = admin_client.get("/admin/scans/commands?maker=없는회사").get_data(as_text=True)
    assert "아직 기억한 명령이 없습니다" in empty


def test_api_scans_do_not_learn(client, make_user):
    from tests.conftest import api_login

    tester_id = make_user("tester1")
    headers = api_login(client, "tester1")
    response = client.post("/api/scans", headers=headers, json={
        "type": "ice", "deviceType": "obd", "deviceUid": "dev-1", "testerId": tester_id,
        "carNo": "12가3456", "carVin": "TESTVIN0000000001", "carModel": "아반떼", "carMaker": "현대",
        "raw": ["P0133"],
    })
    assert response.status_code == 201, response.get_json()
    with client.application.app_context():
        assert db.session.scalar(select(func.count()).select_from(MakerScanCommand)) == 0


def service_scan(admin) -> Scan:
    scan = Scan(type="ev", device_type="ble", device_uid="d", tester_id=admin.id, car_no="12가3456",
                car_vin="미확인", car_maker="현대", car_model="코나 일렉트릭")
    db.session.add(scan)
    db.session.flush()
    return scan
