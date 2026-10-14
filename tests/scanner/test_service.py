import pytest
from sqlalchemy import select

from app.core.errors import ServiceError
from app.extensions import db
from app.modules.accounts.models import User
from app.modules.canlab.models import CanDataset, DiagnosticReport
from app.modules.scanner import service
from app.modules.scanner.plan import build_plan
from app.modules.scans.models import Code, Scan, ScanCode, ScanDocument
from tests.canlab.synthetic import bms_0101, isotp_frames

KONA_EV = {"diag_car_id": "KMHK381GFMU000001", "diag_company": "현대", "diag_model": "코나 일렉트릭",
           "diag_year": "2021", "diag_fuel": "전기", "diag_displacement": ""}
AVANTE = {"diag_car_id": "", "diag_company": "현대", "diag_model": "아반떼", "diag_year": "2019",
          "diag_fuel": "휘발유", "diag_displacement": "1598"}


def _can_reply(source: str, payload: bytes) -> str:
    return "\r".join(f"{source} {frame.hex(' ').upper()}" for frame in isotp_frames(payload)) + "\r\r>"


def _step(command, reply, header=None, error=None, optional=False, bus=None, group="pid", t_ms=0):
    return {"command": command, "header": header, "reply": reply, "error": error, "optional": optional,
            "bus": bus, "group": group, "label": command, "tMs": t_ms}


@pytest.fixture
def admin(app, make_user):
    make_user("scanner", type="admin")
    with app.app_context():
        yield db.session.scalar(select(User).where(User.tid == "scanner"))


def test_plan_covers_obd_uds_and_maker_steps(app):
    with app.app_context():
        generic = build_plan(AVANTE)["steps"]
        ev = build_plan(KONA_EV)
    commands = [(s["header"], s["command"]) for s in generic]
    assert commands[:3] == [(None, "ATRV"), (None, "0100"), (None, "ATDPN")]
    assert {(None, "03"), (None, "07"), (None, "0A"), (None, "0902"), ("7E0", "22F190"), ("7E1", "1902FF")} \
        <= set(commands)
    assert ("7E4", "220101") not in commands
    assert len({s["id"] for s in generic}) == len(generic)
    assert all(s["bus"] == "can" for s in generic if s["header"])

    ev_commands = [(s["header"], s["command"]) for s in ev["steps"]]
    assert {("7E4", "220101"), ("7E4", "220105"), ("7E4", "2101"), ("7C6", "22F190")} <= set(ev_commands)
    assert "DoIP" in ev["notes"][0]


def test_successful_scan_saves_scan_report_and_codes(app, admin):
    db.session.add(Code(type="ice", code="P0133", unit_name="엔진", desc="O2 센서 응답 느림",
                        root_cause="센서 노화", howto_fix1="센서 교체"))
    db.session.commit()
    vin = ("7E8 10 14 49 02 01 4B 4E 41\r7E8 21 44 48 38 31 32 33 34\r"
           "7E8 22 35 36 37 38 39 30 31\r\r>")
    steps = [
        _step("ATRV", "12.4V\r\r>", group="device"),
        _step("0100", "SEARCHING...\r7E8 06 41 00 98 3B 80 13\r\r>"),
        _step("ATDPN", "A6\r\r>", group="device"),
        _step("0101", "7E8 06 41 01 81 07 E5 00\r\r>"),
        _step("010C", "7E8 04 41 0C 1A F8\r\r>", optional=True),
        _step("0902", vin, group="vehicle", optional=True),
        _step("03", "7E8 04 43 01 01 33\r\r>", group="dtc"),
        _step("07", "NO DATA\r\r>", group="dtc", optional=True),
        _step("1902FF", "NO DATA\r\r>", header="7E0", optional=True, bus="can", group="uds"),
        _step("220101", _can_reply("7EC", bms_0101(soc=37.5)), header="7E4", optional=True, bus="can",
              group="maker", t_ms=900),
    ]

    scan = service.run_scan(admin, car_no="12가 3456", car=KONA_EV, steps=steps, transport="ble",
                            device="vLinker MS")

    data = scan.bms_data
    assert scan.car_no == "12가3456" and scan.type == "ev" and scan.car_model == "코나 일렉트릭"
    assert scan.scan_vin == "KNADH812345678901" and data["vin_match"] is False
    assert data["status"] == "ok" and data["errors"] == []
    assert data["protocol"]["bus"] == "can11" and data["voltage"] == 12.4
    assert data["monitor"] == {"mil": True, "dtc_count": 1}
    assert {"key": "rpm", "label": "엔진 회전수", "unit": "rpm", "value": 1726.0} in data["values"]
    dtc = data["dtcs"][0]
    assert dtc["code"] == "P0133" and dtc["system"] == "engine" and dtc["desc"] == "O2 센서 응답 느림"
    assert dtc["howto"] == ["센서 교체"] and data["systems"]["engine"] == 1
    assert data["battery"]["soc"] == {"label": "배터리 충전 상태(BMS)", "value": 37.5, "unit": "%", "reference": True}
    assert data["counts"]["unsupported"] == 2 and scan.raw == ["P0133"]

    report = db.session.get(DiagnosticReport, data["report_id"])
    assert report.values["soc"]["rule_id"] is None and report.diagnosis["errors"] == []
    assert report.diagnosis["obd"]["dtcs"][0]["code"] == "P0133"
    dataset = db.session.get(CanDataset, data["dataset_id"])
    assert dataset.kind == "live_capture" and dataset.source == "web"
    assert dataset.content.startswith(b"# WECAR-ELM") and b"12\xea\xb0\x803456" not in dataset.content
    assert db.session.scalar(select(ScanCode.code_id).where(ScanCode.scan_id == scan.id)) is not None


def test_failed_scan_keeps_every_error(app, admin):
    steps = [
        _step("ATRV", None, error="timeout", group="device"),
        _step("0100", "SEARCHING...\rUNABLE TO CONNECT\r\r>"),
        _step("ATDPN", "0\r\r>", group="device"),
        _step("03", None, error="disconnected", group="dtc"),
        _step("22F190", None, header="7E0", error="skipped", optional=True, bus="can", group="uds"),
    ]
    scan = service.run_scan(admin, car_no="12가3456", car=None, steps=steps, transport="serial",
                            lookup_error="일일 조회 한도를 넘었습니다.")

    data = scan.bms_data
    assert data["status"] == "failed" and scan.car_model == "미확인" and scan.type == "ice"
    errors = {(e["group"], e["command"]): e for e in data["errors"]}
    assert errors[("lookup", None)]["message"] == "일일 조회 한도를 넘었습니다."
    assert errors[("device", "ATRV")]["status"] == "timeout"
    assert "UNABLE TO CONNECT" in errors[("pid", "0100")]["message"]
    assert errors[("dtc", "03")]["status"] == "disconnected"
    assert ("uds", "22F190") not in errors
    report = db.session.get(DiagnosticReport, data["report_id"])
    assert len(report.diagnosis["errors"]) == len(data["errors"])


def test_interpretation_crash_is_recorded(app, admin, monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(service, "interpret", broken)
    scan = service.run_scan(admin, car_no="12가3456", car=AVANTE, steps=[_step("03", "NO DATA")],
                            transport="ble")
    assert scan.bms_data["status"] == "failed"
    assert scan.bms_data["errors"][0]["status"] == "server_error"
    assert "ValueError" in scan.bms_data["errors"][0]["message"]
    assert db.session.scalar(select(Scan.id).where(Scan.id == scan.id))


def test_kline_vehicle_skips_can_only_steps(app, admin):
    steps = [
        _step("0100", "SEARCHING...\r48 6B 10 41 00 BE 1F B8 10 A9\r\r>"),
        _step("ATDPN", "A3\r\r>", group="device"),
        _step("03", "48 6B 10 43 01 33 00 00 00 00 E2\r\r>", group="dtc"),
        _step("22F190", "NO DATA", header="7E0", optional=True, bus="can", group="uds"),
    ]
    data = service.run_scan(admin, car_no="34나5678", car=AVANTE, steps=steps, transport="serial").bms_data
    assert data["protocol"]["bus"] == "serial" and [d["code"] for d in data["dtcs"]] == ["P0133"]
    skipped = [s for s in data["steps"] if s["command"] == "22F190"][0]
    assert skipped["status"] == "skipped" and data["status"] == "ok"


def test_plan_has_freeze_cvn_and_app_uds_steps(app):
    with app.app_context():
        steps = build_plan(AVANTE)["steps"]
    commands = [(s["header"], s["command"]) for s in steps]
    assert {(None, "0906"), (None, "020200"), (None, "020C00"), (None, "190209"), (None, "190204"),
            (None, "1915"), ("7E0", "22F187"), ("7E0", "22F195")} <= set(commands)
    assert all(s["group"] == "freeze" and s["optional"] for s in steps if s["command"].startswith("02"))


def test_freeze_frame_cvn_permanent_dtc_and_ecu_ident(app, admin):
    part = "62F187" + "91000-AB12".encode().hex()
    steps = [
        _step("0100", "7E8 06 41 00 98 3B 80 13\r\r>"),
        _step("ATDPN", "A6\r\r>", group="device"),
        _step("0906", "7E8 07 49 06 01 1A 2B 3C 4D\r\r>", group="vehicle", optional=True),
        _step("020200", "7E8 05 42 02 00 01 43\r\r>", group="freeze", optional=True),
        _step("020C00", "7E8 05 42 0C 00 0F A0\r\r>", group="freeze", optional=True),
        _step("0205", None, error="skipped", group="freeze", optional=True),
        _step("1915", "7E8 07 59 15 FF 01 01 00 08\r\r>", optional=True, bus="can", group="uds"),
        _step("22F187", _can_reply("7E8", bytes.fromhex(part)), header="7E0", optional=True, bus="can",
              group="uds"),
        _step("010D", None, error="skipped", optional=True),
    ]
    steps[5]["reason"] = "저장된 고장코드가 없어 건너뛰었습니다."
    steps[-1]["reason"] = "차량이 지원하지 않는 항목이라 보내지 않았습니다."
    data = service.run_scan(admin, car_no="34나5678", car=AVANTE, steps=steps, transport="ble").bms_data

    assert data["cvns"] == ["1A2B3C4D"]
    assert data["freeze_frame"]["dtc"] == "P0143"
    assert data["freeze_frame"]["values"][0]["value"] == 1000.0
    permanent = [d for d in data["dtcs"] if d["source"] == "UDS 19 15"]
    assert permanent[0]["code"] == "P010100" and permanent[0]["kind"] == "영구"
    assert [e for e in data["ecus"] if e["address"] == "7E8"][0]["part_no"] == "91000-AB12"
    statuses = {s["command"]: s["status"] for s in data["steps"]}
    assert statuses["0205"] == "skipped" and statuses["010D"] == "unsupported"


def test_scan_saves_result_pdf(app, admin):
    scan = service.run_scan(admin, car_no="12가3456", car=AVANTE, steps=[_step("03", "7E8 04 43 01 01 33\r\r>")],
                            transport="ble")
    document = db.session.scalar(select(ScanDocument).where(ScanDocument.scan_id == scan.id))
    assert document.content.startswith(b"%PDF") and document.size == len(document.content)
    assert document.filename.startswith("위스캔-12가3456-") and document.filename.endswith(".pdf")
    assert service.scan_document(scan).id == document.id


def test_pdf_failure_still_saves_scan_and_retries_later(app, admin, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("font missing")

    monkeypatch.setattr(service.pdf, "render", broken)
    scan = service.run_scan(admin, car_no="12가3456", car=AVANTE,
                            steps=[_step("03", "7E8 04 43 01 01 33\r\r>")], transport="ble",
                            client_error="블루투스 연결이 끊겼습니다.")
    data = scan.bms_data
    statuses = {e["status"] for e in data["errors"]}
    assert {"client_error", "pdf_error"} <= statuses and data["status"] == "partial"
    assert db.session.scalar(select(ScanDocument.id).where(ScanDocument.scan_id == scan.id)) is None
    with pytest.raises(ServiceError):
        service.scan_document(scan)

    monkeypatch.undo()
    assert service.scan_document(scan).content.startswith(b"%PDF")


@pytest.mark.parametrize("bad", [
    [{"command": "0100; rm", "reply": ""}],
    [{"command": "010", "reply": ""}],
    [{"command": "0100", "header": "7E0X"}],
    [],
])
def test_bad_steps_are_rejected(bad):
    with pytest.raises(ServiceError):
        service.clean_steps(bad)
