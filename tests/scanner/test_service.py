import pytest
from sqlalchemy import select

from app.core.errors import ServiceError
from app.extensions import db
from app.modules.accounts.models import User
from app.modules.canlab import service as canlab_service
from app.modules.canlab.engine import obdb
from app.modules.canlab.engine.search import Layout
from app.modules.canlab.models import CanDataset, DecodeRule, DiagnosticReport, LogicStatus, RuleStatus, ScanLogic
from app.modules.scanner import service
from app.modules.scanner.plan import build_plan
from app.modules.scans.models import Code, MakerScanCommand, Scan, ScanCode, ScanDocument
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
    assert data["monitor"]["mil"] is True and data["monitor"]["dtc_count"] == 1
    assert {"key": "rpm", "label": "엔진 회전수", "unit": "rpm", "value": 1726.0} in data["values"]
    dtc = data["dtcs"][0]
    assert dtc["code"] == "P0133" and dtc["system"] == "engine" and dtc["desc"] == "O2 센서 응답 느림"
    assert dtc["howto"] == ["센서 교체"] and data["systems"]["engine"] == 1
    assert data["battery"]["soc"] == {"label": "배터리 충전 상태(BMS)", "value": 37.5, "unit": "%", "reference": True,
                                      "source": "7E4 22 0101", "origin": "OBDb Hyundai-Kona-Electric",
                                      "range": [0, 100], "outlier": False}
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


def test_plan_conditions_and_expansion(app):
    with app.app_context():
        legacy = build_plan(AVANTE)["steps"]
        steps = build_plan(AVANTE, expand=True)["steps"]
    by_command = {(s["header"], s["command"]): s for s in steps}

    assert not any("expand" in s for s in legacy)
    assert {"010C", "0105"} <= {s["command"] for s in legacy}
    assert [s for s in legacy if s["command"] == "010C"][0]["when"] == {"pid": "0C"}
    assert by_command[(None, "0120")]["when"] == {"pid": "20"}
    assert by_command[(None, "0100")]["timeout"] == 30000
    assert by_command[(None, "0141")]["when"] == {"pid": "41"}
    assert by_command[(None, "0908")]["when"] == {"info09": "08"}
    assert by_command[(None, "020C00")]["when"] == {"dtc": True, "pid02": "0C"}
    assert by_command[(None, "0620")]["when"] == {"mid": "20"} and by_command[(None, "0620")]["bus"] == "can"

    pids = by_command[(None, "01")]
    assert pids["expand"] == "pids" and "0C" in pids["pids"] and "41" not in pids["pids"]
    assert not any(s["command"] == "010C" for s in steps)
    assert by_command[(None, "06")]["expand"] == "mids"
    snapshot = by_command[("7E0", "1904")]
    assert snapshot["expand"] == "dtcs" and snapshot["limit"] == 3 and snapshot["header29"] == "18DA10F1"
    assert by_command[("7E1", "1902FF")]["header29"] == "18DA18F1"
    assert "header29" not in by_command[("7E2", "1902FF")]


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


def test_merged_dtcs_per_ecu_values_and_extended_reads(app, admin):
    snapshot = bytes.fromhex("5904" "013300" "09" "01" "01" "DD01" "0012")
    kwp = b"\x61\x01" + bms_0101(soc=55.0)[3:]
    steps = [
        _step("0100", "7E8 06 41 00 98 3B 80 13\r7E9 06 41 00 80 00 00 01\r\r>"),
        _step("ATDPN", "A6\r\r>", group="device"),
        _step("0101", "7E8 06 41 01 81 07 65 21\r\r>"),
        _step("010C0D05", "7E8 08 41 0C 1A F8 0D 32 05 7B\r7E9 03 41 05 50\r\r>", optional=True),
        _step("03", "7E8 04 43 01 01 33\r\r>", group="dtc"),
        _step("0A", "7E8 04 4A 01 01 33\r\r>", group="dtc", optional=True),
        _step("0621", _can_reply("7E8", bytes.fromhex("4621800B019000640" "3E8")), group="monitor", optional=True,
              bus="can"),
        _step("0908", _can_reply("7E8", bytes.fromhex("490814" "0010" "0020" "0005" "000A" "0000" "0000")),
              group="vehicle", optional=True),
        _step("1902FF", _can_reply("7E8", bytes.fromhex("5902FF" "013300" "09")), header="7E0", optional=True,
              bus="can", group="uds"),
        _step("1904013300FF", _can_reply("7E8", snapshot), header="7E0", optional=True, bus="can", group="uds"),
        _step("22F195", "7E8 03 7F 22 78\r7E8 03 7F 22 78\r\r>", header="7E0", optional=True, bus="can",
              group="uds"),
        _step("2101", _can_reply("7EC", kwp), header="7E4", optional=True, bus="can", group="maker"),
    ]
    data = service.run_scan(admin, car_no="34나5678", car=KONA_EV, steps=steps, transport="ble").bms_data

    assert len(data["dtcs"]) == 1
    dtc = data["dtcs"][0]
    assert dtc["ecu"] == "7E8" and dtc["code"] == "P013300" and dtc["kind"] == "현재"
    assert dtc["kinds"] == ["현재", "확정", "영구"] and len(dtc["sources"]) == 3

    assert data["primary_ecu"] == "7E8"
    assert [v["key"] for v in data["values"]] == ["rpm", "speed", "coolant_temp"]
    assert data["ecu_values"][0]["ecu"] == "7E9" and data["ecu_values"][0]["values"][0]["value"] == 40
    assert data["monitor"]["mil"] and {"name": "촉매", "complete": False} in data["monitor"]["tests"]
    assert data["monitor_tests"][0]["passed"] and data["monitor_tests"][0]["ecu"] == "7E8"
    assert data["iumpr"]["monitors"][0]["ratio"] == 0.5
    assert data["snapshots"][0]["code"] == "P013300" and data["snapshots"][0]["did"] == "DD01"
    assert [e["request"] for e in data["ecus"] if e["address"] == "7E8"] == ["7E0"]
    assert data["battery"]["soc"]["value"] == 55.0 and data["battery"]["soc"]["source"] == "7E4 21 01"

    statuses = {s["command"]: s["status"] for s in data["steps"]}
    assert statuses["22F195"] == "pending" and not any(e["command"] == "22F195" for e in data["errors"])


def test_obdb_model_match_plan_and_cells(app, admin):
    assert obdb.match(KONA_EV)["repo"] == "Hyundai-Kona-Electric"
    assert obdb.match({"diag_model": "니로 EV"})["repo"] == "Kia-Niro-EV"
    assert obdb.match({"diag_model": "더 뉴 니로"})["repo"] == "Kia-Niro"
    assert obdb.match({"diag_model": "아이오닉 5"})["repo"] == "Hyundai-IONIQ-5"
    assert obdb.match(AVANTE) is None
    assert obdb.plan_dids(AVANTE) == ["0101", "0105"]
    with app.app_context():
        commands = [s["command"] for s in build_plan(KONA_EV)["steps"] if s["header"] == "7E4"]
    assert {"220101", "220105", "220102", "22010C"} <= set(commands)

    cells = bytes.fromhex("620102" + "FFFFFFFF") + bytes([200] * 30 + [199, 130, 0])
    steps = [
        _step("ATDPN", "A6\r\r>", group="device"),
        _step("220102", _can_reply("7EC", cells), header="7E4", optional=True, bus="can", group="maker"),
    ]
    data = service.run_scan(admin, car_no="34나5678", car=KONA_EV, steps=steps, transport="ble").bms_data
    assert data["cells"]["count"] == 31 and data["cells"]["min"] == 3.98 and data["cells"]["max"] == 4.0
    assert data["cells"]["spread_mv"] == 20 and data["cells"]["origin"] == "OBDb Hyundai-Kona-Electric"
    assert data["cells"]["range"] == [2.8, 4.2] and data["cells"]["outliers"] == [{"no": 32, "voltage": 2.6}]
    assert any("OBDb" in note and "CC BY-SA 4.0" in note for note in data["notes"])


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


def _activate_logic() -> ScanLogic:
    """스캔 로직 v1: 명령 220101·220105, 수식 SOC(0101 b4)·최대 온도(0105 b3)."""
    rules = []
    for key, layout in (("soc", Layout(0x7E4, 0x0101, 4, 1, scale=0.5)), ("max_temp", Layout(0x7E4, 0x0105, 3, 1))):
        rule = DecodeRule(signal_key=key, revision=1, status=RuleStatus.ACTIVE, confidence=0.9, evidence={},
                          formula=layout.formula(), **layout.to_dict())
        db.session.add(rule)
        db.session.flush()
        rules.append({"signal_key": key, "rule_id": rule.id, "revision": 1, "formula": rule.formula})
    logic = ScanLogic(revision=1, status=LogicStatus.ACTIVE, rules=rules, diff={}, commands=[
        {"header": "7E4", "command": "220101", "label": "BMS 0101"},
        {"header": "7E4", "command": "220105", "label": "BMS 0105"}])
    db.session.add(logic)
    db.session.commit()
    return logic


LOGIC_STEPS = [
    _step("ATDPN", "A6\r\r>", group="device"),
    _step("220101", _can_reply("7EC", bms_0101(soc=37.5)), header="7E4", optional=True, bus="can", group="rule"),
    _step("220105", "NO DATA\r\r>", header="7E4", optional=True, bus="can", group="rule"),
]


def test_scan_logic_problems_are_recorded(app, admin):
    logic = _activate_logic()
    with app.app_context():
        labels = {s["label"] for s in build_plan(AVANTE)["steps"] if s["group"] == "rule"}
    assert {"스캔 로직: BMS 0101", "스캔 로직: BMS 0105"} <= labels

    data = service.run_scan(admin, car_no="12가3456", car=AVANTE, steps=LOGIC_STEPS, transport="ble").bms_data

    problems = {e["label"]: e for e in data["errors"] if e["group"] == "logic"}
    assert set(problems) == {"BMS 0105", "배터리 최대 온도"}
    assert problems["BMS 0105"]["command"] == "220105" and problems["BMS 0105"]["status_label"] == "로직 문제"
    assert "v1" in problems["배터리 최대 온도"]["message"]
    assert data["battery"]["soc"]["value"] == 37.5 and data["status"] == "partial"
    assert data["scan_logic"] == {"id": logic.id, "revision": 1}

    other = service.run_scan(admin, car_no="12가3456", car=AVANTE, steps=[_step("03", "NO DATA")],
                             transport="ble").bms_data
    assert not any(e["group"] == "logic" for e in other["errors"])


def test_result_page_pops_up_logic_problems_and_handles_deleted_report(app, admin_client):
    from tests.conftest import csrf_token

    with app.app_context():
        _activate_logic()
    token = csrf_token(admin_client, "/admin/scan/")
    steps = [{k: v for k, v in s.items() if k != "tMs"} for s in LOGIC_STEPS]
    saved = admin_client.post("/admin/scan/run", headers={"X-CSRFToken": token}, json={
        "carNo": "12가3456", "car": AVANTE, "steps": steps, "transport": "ble"}).get_json()

    html = admin_client.get(saved["url"]).get_data(as_text=True)
    assert "data-auto-open" in html and "스캔 로직 문제 2건" in html and "v1" in html
    assert "/admin/canlab/reports/" in html

    with app.app_context():
        canlab_service.reset_all()
    html = admin_client.get(saved["url"]).get_data(as_text=True)
    assert "결과지 삭제됨" in html and "/admin/canlab/reports/" not in html


@pytest.mark.parametrize("bad", [
    [{"command": "0100; rm", "reply": ""}],
    [{"command": "010", "reply": ""}],
    [{"command": "0100", "header": "7E0X"}],
    [],
])
def test_bad_steps_are_rejected(bad):
    with pytest.raises(ServiceError):
        service.clean_steps(bad)


def test_read_plan_never_clears(app):
    """2026-10-18: 지우기는 scanner/clear.py의 별도 흐름으로만. 읽기 계획에는 04·14·10이 없다."""
    with app.app_context():
        commands = {s["command"] for s in build_plan(AVANTE)["steps"]}
    assert not commands & {"04", "14FFFFFF", "1003", "1001"}


def test_wescan_report_and_learned_command(app, admin):
    steps = [
        _step("ATDPN", "A6\r\r>", group="device"),
        _step("010C", "7E8 04 41 0C 0C 80", group="pid"),
        _step("03", "NO DATA", optional=True, group="dtc"),
        _step("220101", _can_reply("7EC", bms_0101(soc=80.5, voltage=759.0)), header="7E4",
              optional=True, bus="can", group="maker"),
        _step("22AABB", _can_reply("7ED", bytes.fromhex("62AABB01")), header="7E5",
              optional=True, bus="can", group="uds"),
    ]
    scan = service.run_scan(admin, car_no="49마5814", car=KONA_EV, steps=steps, transport="ble")
    report = scan.bms_data["wescan"]
    assert report["diagnosis_info"]["diagnosis_type"] == "BASIC"
    assert report["vehicle"]["manufacturer"] == "현대"
    assert report["sensor"]["ev"]["bms_soc"] == 80.5 or report["sensor"]["ev"].get("bms_pack_voltage")
    assert report["sensor"]["ice"] is None
    with app.app_context():
        remembered = db.session.scalars(select(MakerScanCommand.command)).all()
        assert "22AABB" in remembered and "03" not in remembered and "ATDPN" not in remembered
        learned = {s["command"] for s in build_plan(KONA_EV)["steps"] if s["group"] == "learned"}
    assert "22AABB" in learned
