import io
import json
import re

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.core.audit import Activity
from app.extensions import db
from app.modules.canlab import ai, references, service
from app.modules.canlab.engine.frames import elm_from_exchanges
from app.modules.canlab.engine.search import Layout
from app.modules.canlab.models import (
    AnalysisRun,
    CanDataset,
    CanReference,
    DecodeRule,
    DiagnosticReport,
    GroundTruthValue,
    LogicStatus,
    ReferenceStatus,
    RuleChange,
    RuleIncident,
    RuleStatus,
    ScanLogic,
    ScanWescanCompare,
)
from app.modules.obd.models import ObdProfile
from app.modules.scanner.plan import build_plan
from app.modules.scans import car_info
from tests.canlab.synthetic import bms_0101, bms_session, exchange, isotp_frames, trc
from tests.conftest import csrf_token

CAR_NO = "12가3456"
CARS = {
    CAR_NO: {"diag_company": "기아", "diag_model": "EV6", "diag_submodel": "EV6 롱레인지", "diag_grade": "어스",
             "diag_year": 2023, "diag_registred_date": "2023-03-02", "diag_car_id": "KNACTESTVIN000123"},
    "34나5678": {"diag_company": "기아", "diag_model": "니로", "diag_submodel": "니로 EV", "diag_grade": "프레스티지",
                "diag_year": 2022, "diag_registred_date": "2022-05-10", "diag_car_id": "KNACTESTVIN000456"},
}
EV6 = {"diag_company": "기아", "diag_model": "EV6"}
NIRO = {"diag_company": "기아", "diag_model": "니로"}
IONIQ5 = {"diag_company": "현대", "diag_model": "아이오닉5"}


@pytest.fixture(autouse=True)
def fake_car_lookup(monkeypatch):
    """차량정보 조회(외부 API)를 대신한다. 모르는 번호는 조회 실패."""
    def lookup(user, car_no, refresh=False):
        car_no = car_info.normalize_car_no(car_no)
        if car_no not in CARS:
            raise car_info.CarInfoError("조회 결과 없음", 404, "not_found")
        return dict(CARS[car_no]), False

    monkeypatch.setattr(car_info, "lookup", lookup)

TRUTHS = """배터리 충전 상태(BMS) | 94.5 | %
배터리 팩 전압 | 785.5 | V
배터리 팩 전류 | -12.3 | A
최대 셀 전압 | 4.08 | V
최소 셀 전압 | 4.06 | V
고객 메모 | 확인 필요 |
"""


def _pdf() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (240, 120), "white").save(buffer, "PDF")
    return buffer.getvalue()


def _text_pdf(*lines: str) -> bytes:
    from reportlab.pdfgen.canvas import Canvas

    from app.modules.scanner.pdf import FONT, _fonts

    _fonts()
    buffer = io.BytesIO()
    canvas = Canvas(buffer)
    canvas.setFont(FONT, 11)
    for number, line in enumerate(lines):
        canvas.drawString(72, 760 - number * 20, line)
    canvas.save()
    return buffer.getvalue()


def _wecan_trace() -> str:
    return trc(exchange(0x7E4, b"\x22\x01\x01", bms_0101(soc=37.5, voltage=256.5, current=5.5,
                                                          cell_max=3.56, cell_min=3.54)))


def _upload(client, content: bytes, filename: str, kind: str, vehicle: str = "EV6 시험차"):
    token = csrf_token(client, "/admin/canlab/datasets")
    return client.post("/admin/canlab/datasets", content_type="multipart/form-data", data={
        "csrf_token": token, "file": (io.BytesIO(content), filename), "kind": kind, "vehicle": vehicle,
    })


def _dataset_id(response) -> int:
    return int(re.search(r"/datasets/(\d+)", response.headers["Location"]).group(1))


def _post(client, url: str, page: str, **data):
    return client.post(url, data={"csrf_token": csrf_token(client, page), **data})


def _reverse_trace() -> str:
    """리버스 기록: 같은 BMS 응답(온도만 다름)과 위스캔에 없는 22 0105 요청."""
    return trc(exchange(0x7E4, b"\x22\x01\x01", bms_0101(max_temp=30))
               + exchange(0x7E4, b"\x22\x01\x05", b"\x62\x01\x05" + bytes(20)))


def _ingest(client, car_no: str = CAR_NO, wescan: bytes = None, values: str = TRUTHS,
            reverse: list[tuple[bytes, str]] | None = None, **extra):
    """데이터입력분석: 차량번호 + 위스캔 통신기록·최종값 + 리버스데이터를 올리고 추출하기."""
    token = csrf_token(client, "/admin/canlab/analysis")
    wescan = bms_session(count=1).encode() if wescan is None else wescan
    reverse = [(_reverse_trace().encode(), "reverse.trc")] if reverse is None else reverse
    return client.post("/admin/canlab/analysis", content_type="multipart/form-data", data={
        "csrf_token": token, "car_no": car_no, "wescan_file": (io.BytesIO(wescan), "wescan.trc"),
        "values_text": values, "reverse_files": [(io.BytesIO(c), name) for c, name in reverse], **extra,
    })


def _run_id(response) -> int:
    return int(re.fullmatch(r"/admin/canlab/analysis/(\d+)", response.headers["Location"]).group(1))


def _ids(app) -> dict:
    with app.app_context():
        rows = {d.kind: d.id for d in db.session.scalars(select(CanDataset))}
    return {"wescan": rows["wecan_trc"], "reverse": rows["gscan_trc"]}


def _rule(signal_key: str, start: int, maker: str | None = None, model: str | None = None) -> DecodeRule:
    layout = Layout(0x7E4, 0x0101, start, 1)
    rule = DecodeRule(signal_key=signal_key, revision=1, status=RuleStatus.ACTIVE, confidence=0.9, evidence={},
                      formula=layout.formula(), maker=maker, model=model, **layout.to_dict())
    db.session.add(rule)
    return rule


def _draft(client, run_id: int) -> int:
    page = f"/admin/canlab/analysis/{run_id}"
    response = _post(client, f"{page}/apply", page)
    assert response.status_code == 302
    return int(re.search(r"/logics/(\d+)", response.headers["Location"]).group(1))


def _confirm(app, client, logic_id: int, **choices):
    with app.app_context():
        version = db.session.get(ScanLogic, logic_id).version
    page = f"/admin/canlab/logics/{logic_id}"
    return _post(client, f"{page}/confirm", page, version=str(version),
                 **{f"choice-{k}": v for k, v in choices.items()})


@pytest.fixture
def analysed(app, admin_client):
    """기아 EV6 차량번호로 위스캔 데이터(최종값 포함)와 리버스 데이터를 올리고 역산 분석까지 마친 상태(적용 전)."""
    response = _ingest(admin_client)
    assert response.status_code == 302
    return _ids(app) | {"run": _run_id(response)}


@pytest.fixture
def trained(app, admin_client, analysed):
    """역산 결과를 기본안 그대로 스캔 로직으로 적용한 상태."""
    logic_id = _draft(admin_client, analysed["run"])
    assert _confirm(app, admin_client, logic_id).status_code == 302
    return analysed | {"logic": logic_id}


def test_canlab_pages_are_admin_only(client, make_user):
    assert client.get("/admin/canlab/").status_code == 302
    make_user("tester1", type="tester")
    token = csrf_token(client, "/admin/login")
    client.post("/admin/login", data={"csrf_token": token, "tid": "tester1", "password": "password123"})
    assert client.get("/admin/canlab/datasets").status_code in (302, 403)


def test_upload_summarises_trace_and_masks_vin(app, admin_client):
    response = _upload(admin_client, bms_session(count=2).encode(), "gscan.trc", "gscan_trc")

    assert response.status_code == 302
    html = admin_client.get(response.headers["Location"]).get_data(as_text=True)
    assert "TESTVIN0000******" in html and "TESTVIN0000123456" not in html
    assert "BMS(배터리 관리)" in html and "0101" in html
    with app.app_context():
        dataset = db.session.scalar(select(CanDataset))
        assert dataset.summary["transactions"] >= 4 and dataset.summary["dtc_count"] == 1
        assert db.session.scalar(select(Activity.relation_type).where(Activity.relation == "CanDataset")) == "CAN 데이터 등록"


def test_upload_rejects_duplicates_wrong_files_and_oversize(app, admin_client, monkeypatch):
    content = bms_session(count=1).encode()
    _upload(admin_client, content, "a.trc", "gscan_trc")

    duplicate = _upload(admin_client, content, "copy.trc", "gscan_trc")
    assert duplicate.status_code == 409 and "이미 등록된 파일입니다" in duplicate.get_data(as_text=True)

    wrong = _upload(admin_client, b"not a pdf", "result.pdf", "gscan_pdf")
    assert wrong.status_code == 400 and "PDF 파일이어야" in wrong.get_data(as_text=True)

    garbage = _upload(admin_client, b"hello\nworld\n", "x.trc", "wecan_trc")
    assert garbage.status_code == 400 and "진단 요청·응답을 찾지 못했습니다" in garbage.get_data(as_text=True)

    monkeypatch.setitem(app.config, "CANLAB_MAX_UPLOAD_BYTES", 100)
    big = _upload(admin_client, bms_session(count=3).encode(), "big.trc", "gscan_trc")
    assert big.status_code == 413


def test_pdf_page_image_and_manual_truths(app, admin_client):
    pdf_id = _dataset_id(_upload(admin_client, _pdf(), "result.pdf", "gscan_pdf"))
    page = f"/admin/canlab/datasets/{pdf_id}"

    image = admin_client.get(f"{page}/pages/1.jpg")
    assert image.status_code == 200 and image.mimetype == "image/jpeg"
    assert image.headers["Cache-Control"] == "private, max-age=600"
    assert admin_client.get(f"{page}/pages/9.jpg").status_code == 404

    _post(admin_client, f"{page}/truths/add", page, text=TRUTHS)
    with app.app_context():
        truths = db.session.scalars(select(GroundTruthValue).order_by(GroundTruthValue.id)).all()
        assert [t.signal_key for t in truths] == ["soc", "pack_voltage", "pack_current", "max_cell_v", "min_cell_v"]
        assert all(t.confirmed and t.source == "manual" for t in truths)


def test_ai_ocr_adds_unconfirmed_values_then_admin_confirms(app, admin_client, monkeypatch):
    pdf_id = _dataset_id(_upload(admin_client, _pdf(), "result.pdf", "gscan_pdf"))
    page = f"/admin/canlab/datasets/{pdf_id}"
    monkeypatch.setattr(ai, "read_table", lambda image=None, page_text=None: (
        [{"label": "배터리 팩 전압", "value": "785.5", "unit": "V"},
         {"label": "모르는 항목", "value": "1", "unit": ""}], "openai"))

    response = _post(admin_client, f"{page}/pages/1/ocr", page)
    assert response.status_code == 302
    with app.app_context():
        rows = db.session.scalars(select(GroundTruthValue).order_by(GroundTruthValue.id)).all()
        assert [(r.signal_key, r.confirmed, r.source) for r in rows] == [
            ("pack_voltage", False, "ai_ocr"), (None, False, "ai_ocr")]
        first, second = rows[0].id, rows[1].id

    _post(admin_client, f"{page}/truths", page, **{
        f"value-{first}": "785.6", f"key-{first}": "pack_voltage", f"confirmed-{first}": "on",
        f"value-{second}": "1", f"key-{second}": "", f"delete-{second}": "on"})
    with app.app_context():
        rows = db.session.scalars(select(GroundTruthValue)).all()
        assert [(r.value_text, r.confirmed) for r in rows] == [("785.6", True)]


def test_ocr_without_ai_connection_explains_how_to_enable(admin_client):
    pdf_id = _dataset_id(_upload(admin_client, _pdf(), "result.pdf", "gscan_pdf"))
    page = f"/admin/canlab/datasets/{pdf_id}"

    response = _post(admin_client, f"{page}/pages/1/ocr", page)
    html = admin_client.get(response.headers["Location"]).get_data(as_text=True)
    assert "CAN 분석" in html and "용도를 켜세요" in html


def test_input_page_has_vehicle_lookup_and_three_uploads(admin_client):
    html = admin_client.get("/admin/canlab/analysis").get_data(as_text=True)

    assert ">데이터입력분석<" in html and ">디코딩 규칙<" in html and "위스캔값 입력" not in html
    assert 'data-lookup-url="/admin/scan/lookup"' in html and "js/components/canlab-input.js" in html
    assert "차량 조회" in html and "위스캔 통신기록" in html and "위스캔 최종값" in html and "리버스데이터" in html
    assert 'name="reverse_files"' in html and "multiple" in html and "올리고 추출하기" in html
    assert admin_client.get("/admin/canlab/wescan").status_code == 404
    assert admin_client.get("/admin/canlab/reverse").status_code == 404


def test_scanner_lookup_gives_vehicle_details_for_input_page(admin_client):
    token = csrf_token(admin_client, "/admin/canlab/analysis")
    body = admin_client.post("/admin/scan/lookup", json={"carNo": CAR_NO}, headers={"X-CSRFToken": token}).get_json()
    assert body["car_no"] == CAR_NO
    assert (body["car"]["diag_company"], body["car"]["diag_model"], body["car"]["diag_year"]) == ("기아", "EV6", 2023)


def test_ingest_extracts_vehicle_commands_and_analyses(app, admin_client, analysed):
    with app.app_context():
        wescan = db.session.get(CanDataset, analysed["wescan"])
        reverse = db.session.get(CanDataset, analysed["reverse"])
        for dataset in (wescan, reverse):
            assert (dataset.maker, dataset.model) == ("기아", "EV6")
            assert dataset.summary["car"] == {"car_no": CAR_NO, "maker": "기아", "model": "EV6",
                                              "submodel": "EV6 롱레인지", "grade": "어스", "year": 2023,
                                              "registered": "2023-03-02"}
        commands = {(c["header"], c["command"]): c for c in wescan.summary["commands"]}
        assert commands[("7E4", "220101")]["sendable"] is True and commands[("7E4", "22010A")]["negative"].startswith("31 ")
        assert [c["command"] for c in reverse.summary["commands"]] == ["220101", "220105"]
        assert [t.signal_key for t in sorted(wescan.truths, key=lambda t: t.id)][:5] == [
            "soc", "pack_voltage", "pack_current", "max_cell_v", "min_cell_v"]

        assert db.session.scalar(select(DecodeRule.id)) is None
        run = db.session.get(AnalysisRun, analysed["run"])
        assert (run.maker, run.model, run.vehicle["car_no"]) == ("기아", "EV6", CAR_NO)
        assert run.reverse_dataset_ids == [analysed["reverse"]] and run.truth_dataset_id == analysed["wescan"]
        assert [r["command"] for r in run.interpretation] == ["220101", "220105"]
        assert any(v["signal_key"] == "max_temp" and v["value"] == 30 for v in run.interpretation[0]["values"])
        assert [c["command"] for c in run.commands["common"]] == ["220101"]
        assert run.commands["common"][0]["structure"]["same_length"] is True
        assert [c["command"] for c in run.commands["reverse_only"]] == ["220105"]
        assert "22010A" in [c["command"] for c in run.commands["wescan_only"]]
        assert run.result["soc"]["status"] == "확정" and run.result["soc"]["formula"] == "b4(무부호 8비트) × 0.5"
        assert db.session.scalar(select(Activity.relation_type).where(
            Activity.relation_type == "데이터입력분석 등록")) is not None

    html = admin_client.get(f"/admin/canlab/analysis/{analysed['run']}").get_data(as_text=True)
    assert "1. 리버스 명령·결과 해석" in html and "2. 위스캔 통신기록 대조" in html and "3. 위스캔 최종값 일치" in html
    assert "b12~b13" in html and "def decode_soc" in html and "EV6 롱레인지" in html and "2023-03-02" in html
    assert "KNACTESTVIN000123" not in html
    assert 'action="/admin/canlab/analysis/%d/apply"' % analysed["run"] in html and "디코딩 규칙 후보 만들기" in html
    assert "차종 기아 EV6" in admin_client.get("/admin/canlab/analysis").get_data(as_text=True)


def test_ingest_requires_known_vehicle_and_valid_reverse_files(app, admin_client):
    unknown = _ingest(admin_client, car_no="99하9999")
    assert unknown.status_code == 404 and "차량정보 조회 실패" in unknown.get_data(as_text=True)

    no_reverse = _ingest(admin_client, reverse=[])
    assert no_reverse.status_code == 400 and "리버스데이터를 하나 이상" in no_reverse.get_data(as_text=True)

    garbage = _ingest(admin_client, reverse=[(b"hello\nworld\n", "bad.trc")])
    assert garbage.status_code == 400 and "진단 요청·응답을 찾지 못했습니다" in garbage.get_data(as_text=True)
    with app.app_context():
        assert db.session.scalar(select(func.count(CanDataset.id))) == 0
        assert db.session.scalar(select(AnalysisRun.id)) is None


def test_ingest_again_reuses_uploaded_files(app, admin_client, analysed):
    response = _ingest(admin_client)

    assert response.status_code == 302 and _run_id(response) != analysed["run"]
    with app.app_context():
        assert db.session.scalar(select(func.count(CanDataset.id))) == 2
        assert db.session.scalar(select(func.count(GroundTruthValue.id))) == 5


def test_wescan_values_from_csv_file_and_missing_values(app, admin_client):
    csv = "배터리 충전 상태(BMS),94.5,%\n배터리 팩 전압,785.5,V\n".encode()
    response = _ingest(admin_client, values="", values_file=(io.BytesIO(csv), "values.csv"))
    assert response.status_code == 302
    with app.app_context():
        assert {t.signal_key for t in db.session.scalars(select(GroundTruthValue))} == {"soc", "pack_voltage"}

    missing = _ingest(admin_client, wescan=bms_session(count=2).encode(), values="메모만 있음")
    assert missing.status_code == 400 and "위스캔 최종값을" in missing.get_data(as_text=True)


def test_text_pdf_values_are_confirmed_before_analysis(app, admin_client):
    pdf = _text_pdf("위스캔 진단 결과", "배터리 충전 상태(BMS) 94.5 %", "배터리 팩 전압 785.5 V")
    response = _ingest(admin_client, values="최소 셀 전압 | 4.06 | V", values_file=(io.BytesIO(pdf), "result.pdf"))

    assert response.status_code == 302 and "/admin/canlab/analysis/pending/" in response.headers["Location"]
    pending = response.headers["Location"]
    html = admin_client.get(pending).get_data(as_text=True)
    assert "최종값 확인" in html and "확정하고 분석" in html and "reverse.trc" in html
    with app.app_context():
        rows = db.session.scalars(select(GroundTruthValue).order_by(GroundTruthValue.id)).all()
        assert [(r.signal_key, r.confirmed, r.source, r.page) for r in rows] == [
            ("min_cell_v", True, "manual", None),
            ("soc", False, "pdf_text", 1), ("pack_voltage", False, "pdf_text", 1)]
        assert db.session.scalar(select(AnalysisRun.id)) is None
        form = {f"value-{r.id}": r.value_text for r in rows} | {f"key-{r.id}": r.signal_key for r in rows}
        form |= {f"confirmed-{r.id}": "on" for r in rows}

    done = _post(admin_client, pending, pending, **form)
    assert done.status_code == 302 and _run_id(done)
    with app.app_context():
        assert all(t.confirmed for t in db.session.scalars(select(GroundTruthValue)))
        assert set(db.session.get(AnalysisRun, _run_id(done)).result) == {"soc", "pack_voltage", "min_cell_v"}


def test_wescan_values_from_image_pdf_use_ai(app, admin_client, monkeypatch):
    no_ai = _ingest(admin_client, values="", values_file=(io.BytesIO(_pdf()), "scan.pdf"))
    assert no_ai.status_code == 400 and "PDF에 글자가 없어 AI 판독이 필요합니다" in no_ai.get_data(as_text=True)
    with app.app_context():
        assert db.session.scalar(select(func.count(CanDataset.id))) == 0

    monkeypatch.setattr(ai, "read_table", lambda image=None, page_text=None: (
        [{"label": "배터리 팩 전압", "value": "785.5", "unit": "V"},
         {"label": "고객 메모", "value": "확인 필요", "unit": ""}], "openai"))
    response = _ingest(admin_client, values="", values_file=(io.BytesIO(_pdf()), "scan.pdf"))

    assert response.status_code == 302 and "/pending/" in response.headers["Location"]
    with app.app_context():
        rows = db.session.scalars(select(GroundTruthValue)).all()
        assert [(r.signal_key, r.confirmed, r.source, r.page) for r in rows] == [("pack_voltage", False, "ai_ocr", 1)]


def test_apply_shows_before_after_and_confirm_changes_scan_logic(app, admin_client, analysed):
    logic_id = _draft(admin_client, analysed["run"])
    html = admin_client.get(f"/admin/canlab/logics/{logic_id}").get_data(as_text=True)
    assert "변경 전" in html and "변경 후" in html and "AI 최적안 받기" in html
    assert 'name="choice-sig:soc"' in html and "고른 항목으로 적용 확정" in html
    with app.app_context():
        logic = db.session.get(ScanLogic, logic_id)
        items = {i["key"]: i for i in logic.diff["items"]}
        assert logic.status == LogicStatus.DRAFT and service.active_logic() is None
        assert (logic.maker, logic.model) == ("기아", "EV6")
        assert items["sig:soc"]["change"] == "added" and items["sig:soc"]["default"] == "after"
        assert items["cmd:7E4:220101"]["change"] == "added"
        assert "cmd:7E4:220105" not in items
        assert db.session.scalar(select(DecodeRule.id)) is None
        backtest = logic.diff["backtest"]
        assert backtest["scope"] == "차종 기아 EV6" and len(backtest["datasets"]) == 2
        assert backtest["signals"]["soc"] | {"verdict": None} == {
            "datasets": 2, "with_truth": 1, "before_match": 0, "after_match": 1, "before_read": 0,
            "after_read": 2, "verdict": None}
        assert backtest["signals"]["soc"]["verdict"] == "개선"
    assert "과거 데이터 비교" in html and "차종 기아 EV6에 적용합니다" in html

    response = _confirm(app, admin_client, logic_id, **{"cmd:7E4:22010A": "exclude"})

    assert response.status_code == 302
    with app.app_context():
        logic = db.session.get(ScanLogic, logic_id)
        assert logic.status == LogicStatus.ACTIVE and service.active_logic(EV6).id == logic_id
        assert service.active_logic().id == logic_id and service.active_logic(IONIQ5) is None
        commands = [(c["header"], c["command"]) for c in logic.commands]
        assert ("7E4", "220101") in commands and ("7E4", "22010A") not in commands
        assert {r["signal_key"] for r in logic.rules} >= {"soc", "pack_voltage", "pack_current"}
        active = {r.signal_key: r for r in db.session.scalars(
            select(DecodeRule).where(DecodeRule.status == RuleStatus.ACTIVE))}
        assert active["soc"].formula == "b4(무부호 8비트) × 0.5" and active["pack_current"].signed is True
        assert {(r.maker, r.model) for r in active.values()} == {("기아", "EV6")}
        assert db.session.get(AnalysisRun, analysed["run"]).activated_count == len(active)
        steps = [s for s in build_plan({})["steps"] if s["group"] == "rule"]
        logic_step = next(s for s in steps if s["command"] == "220101")
        assert logic_step["header"] == "7E4" and logic_step["label"].startswith("스캔 로직:")
        assert sum(1 for s in steps if (s["header"], s["command"]) == ("7E4", "220101")) == 1
        actions = db.session.scalars(select(Activity.relation_type).where(Activity.relation == "ScanLogic")).all()
        assert actions == ["디코딩 규칙 후보", "디코딩 규칙 후보 적용"]
        change = db.session.scalar(select(RuleChange))
        assert (change.action, change.maker, change.model, change.logic_id) == ("apply", "기아", "EV6", logic_id)
        assert change.before == {"logic_id": None, "logic_revision": None, "rules": []}
        assert {r["signal_key"] for r in change.after["rules"]} == set(active)

    again = _confirm(app, admin_client, logic_id)
    assert again.status_code == 409


def test_confirm_with_stale_version_is_rejected(app, admin_client, analysed):
    logic_id = _draft(admin_client, analysed["run"])
    page = f"/admin/canlab/logics/{logic_id}"
    response = _post(admin_client, f"{page}/confirm", page, version="99")
    assert response.status_code == 409 and "다른 관리자가 먼저 바꿨습니다" in response.get_data(as_text=True)


def test_advise_without_ai_shows_rule_based_default(app, admin_client, analysed):
    logic_id = _draft(admin_client, analysed["run"])
    page = f"/admin/canlab/logics/{logic_id}"

    response = _post(admin_client, f"{page}/advise", page)

    html = admin_client.get(response.headers["Location"]).get_data(as_text=True)
    assert "AI를 쓸 수 없어 규칙 기반 기본안" in html and "기본안을 표시합니다" in html
    with app.app_context():
        assert db.session.get(ScanLogic, logic_id).ai_advice["provider"] is None


def test_ai_advice_is_shown_as_recommendation(app, admin_client, analysed, monkeypatch):
    logic_id = _draft(admin_client, analysed["run"])
    page = f"/admin/canlab/logics/{logic_id}"
    sent = []

    def fake_advise(items):
        sent.extend(items)
        return ({"sig:soc": {"choice": "exclude", "reason": "근거 부족"},
                 "sig:pack_voltage": {"choice": "nonsense", "reason": "x"}}, "SOC는 빼는 것이 좋습니다.", "openai")

    monkeypatch.setattr(ai, "advise_logic", fake_advise)
    _post(admin_client, f"{page}/advise", page)

    html = admin_client.get(page).get_data(as_text=True)
    assert "SOC는 빼는 것이 좋습니다." in html and "근거 부족" in html
    assert all("layout" not in (i["after"] or {}) and "evidence" not in (i["after"] or {}) for i in sent)
    with app.app_context():
        logic = db.session.get(ScanLogic, logic_id)
        recommended = service.recommended(logic)
        assert recommended["sig:soc"]["choice"] == "exclude"
        assert recommended["sig:pack_voltage"] == {"choice": "after", "reason": "기본안"}


def test_new_logic_replaces_old_and_rollback_brings_back_rules(app, admin_client, trained):
    run_id = _run_id(_ingest(admin_client))
    second = _draft(admin_client, run_id)
    with app.app_context():
        items = {i["key"]: i for i in db.session.get(ScanLogic, second).diff["items"]}
        assert items["sig:soc"]["change"] == "same" and items["cmd:7E4:220101"]["change"] == "same"

    _confirm(app, admin_client, second, **{"sig:soc": "exclude"})
    with app.app_context():
        assert service.active_rule("soc", "기아", "EV6") is None
        assert db.session.get(ScanLogic, trained["logic"]).status == LogicStatus.RETIRED
        assert db.session.scalar(select(func.max(DecodeRule.revision)).where(DecodeRule.signal_key == "soc")) == 1
        change_id = db.session.scalar(select(func.max(RuleChange.id)))
    html = admin_client.get("/admin/canlab/rules").get_data(as_text=True)
    assert "변경 이력" in html and "적용 중 범위" in html and f"/admin/canlab/changes/{change_id}/rollback" in html

    rollback = f"/admin/canlab/changes/{change_id}/rollback"
    assert _post(admin_client, rollback, "/admin/canlab/rules").status_code == 302
    with app.app_context():
        assert service.active_logic(EV6).id == trained["logic"]
        assert service.active_rule("soc", "기아", "EV6") is not None
        assert db.session.get(ScanLogic, second).status == LogicStatus.RETIRED
        change = db.session.get(RuleChange, change_id)
        assert change.reverted_by_id and db.session.get(RuleChange, change.reverted_by_id).action == "rollback"
    again = _post(admin_client, rollback, "/admin/canlab/rules")
    assert again.status_code == 409 and "이미 되돌린 변경입니다" in again.get_data(as_text=True)


def test_report_from_wescan_trace_uses_applied_rules(app, admin_client, trained):
    with app.app_context():
        active = {r.signal_key for r in db.session.scalars(
            select(DecodeRule).where(DecodeRule.status == RuleStatus.ACTIVE))}
        assert {"soc", "pack_voltage", "pack_current", "max_cell_v", "min_cell_v"} <= active

    wecan_id = _dataset_id(_upload(admin_client, _wecan_trace().encode(), "wecan.trc", "wecan_trc", "그랜저 HEV"))
    response = _post(admin_client, "/admin/canlab/reports", "/admin/canlab/reports", dataset_id=str(wecan_id))
    assert response.status_code == 302
    html = admin_client.get(response.headers["Location"]).get_data(as_text=True)
    assert "37.5" in html and "256.5" in html and "3.56" in html
    assert 'id="report-data"' in html and "vendor/chart.umd.min.js" in html
    assert "1. 종합: 충전 상태(SOC) 37.5%" in html


def test_analysis_never_replaces_active_rules_and_flags_overlap(app, admin_client):
    with app.app_context():
        for key, start in (("soc", 5), ("max_temp", 12)):
            _rule(key, start)
        db.session.commit()

    run_id = _run_id(_ingest(admin_client))

    with app.app_context():
        assert service.active_rule("soc").start == 5
        assert service.active_rule("pack_voltage") is None
        result = db.session.get(AnalysisRun, run_id).result
        assert result["soc"]["matches_active"] is False and "적용 중 수식" in result["soc"]["reasons"][-1]
        assert result["pack_voltage"]["status"] == "가설"
        assert "배터리 최대 온도" in result["pack_voltage"]["reasons"][0]
    logic_id = _draft(admin_client, run_id)
    with app.app_context():
        items = {i["key"]: i for i in db.session.get(ScanLogic, logic_id).diff["items"]}
        assert items["sig:soc"]["change"] == "changed" and items["sig:soc"]["before"]["formula"] == "b5(무부호 8비트)"
        assert items["sig:pack_voltage"]["default"] == "exclude"
        assert items["sig:max_temp"]["change"] == "removed" and items["sig:max_temp"]["default"] == "before"


def test_reset_cli_counts_then_deletes_all_canlab_data(app, admin_client, trained):
    runner = app.test_cli_runner()

    dry = runner.invoke(args=["canlab", "reset"])
    assert dry.exit_code == 0 and "--yes" in dry.output
    with app.app_context():
        assert db.session.scalar(select(func.count(CanDataset.id))) == 2

    done = runner.invoke(args=["canlab", "reset", "--yes"])
    assert done.exit_code == 0 and "모두 삭제했습니다" in done.output
    with app.app_context():
        for model in (CanDataset, GroundTruthValue, AnalysisRun, DecodeRule, ScanLogic, DiagnosticReport,
                      RuleChange, RuleIncident, ScanWescanCompare):
            assert db.session.scalar(select(func.count()).select_from(model)) == 0
        assert db.session.scalar(select(Activity.relation_type).where(Activity.relation_type == "CAN 분석 초기화"))


def test_rule_rollback_and_conflict(app, admin_client, trained):
    with app.app_context():
        rule = db.session.scalar(select(DecodeRule).where(DecodeRule.signal_key == "soc"))
        rule_id, version = rule.id, rule.version

    stale = _post(admin_client, f"/admin/canlab/rules/{rule_id}/retire", "/admin/canlab/rules",
                  version=str(version + 5))
    assert stale.status_code == 409

    assert _post(admin_client, f"/admin/canlab/rules/{rule_id}/retire", "/admin/canlab/rules",
                 version=str(version)).status_code == 302
    with app.app_context():
        assert service.active_rule("soc", "기아", "EV6") is None
        version = db.session.get(DecodeRule, rule_id).version

    assert _post(admin_client, f"/admin/canlab/rules/{rule_id}/activate", "/admin/canlab/rules",
                 version=str(version)).status_code == 302
    with app.app_context():
        assert service.active_rule("soc", "기아", "EV6").id == rule_id
        actions = db.session.scalars(select(Activity.relation_type).where(Activity.relation == "DecodeRule")).all()
        assert actions == ["디코딩 규칙 해제", "디코딩 규칙 적용"]
        changes = db.session.scalars(select(RuleChange.action).order_by(RuleChange.id)).all()
        assert changes == ["apply", "retire", "activate"]


def test_ai_report_summary_is_saved(app, admin_client, trained, monkeypatch):
    wecan_id = _dataset_id(_upload(admin_client, _wecan_trace().encode(), "wecan.trc", "wecan_trc"))
    report_url = _post(admin_client, "/admin/canlab/reports", "/admin/canlab/reports",
                       dataset_id=str(wecan_id)).headers["Location"]
    captured = {}

    def fake_summary(facts):
        captured.update(facts)
        return "1. 종합 의견: 배터리 상태가 양호합니다.", "anthropic"

    monkeypatch.setattr(ai, "summarize_report", fake_summary)
    _post(admin_client, f"{report_url}/ai", report_url)

    html = admin_client.get(report_url).get_data(as_text=True)
    assert "배터리 상태가 양호합니다" in html and "AI 작성 · anthropic" in html
    assert captured["values"]["배터리 충전 상태(BMS)"]["value"] == 37.5


def test_live_capture_is_saved_as_dataset(app, admin_client):
    token = csrf_token(admin_client, "/admin/canlab/datasets")
    content = "\n".join([
        "# WECAR-ELM 1", "# vehicle: 아이오닉5", "# source: web",
        "10.0 TX 7E4 03 22 01 01",
        "55.2 RX 7EC 03 7F 22 31",
    ]) + "\n"
    response = admin_client.post("/admin/canlab/live", data={
        "csrf_token": token, "vehicle": "아이오닉5", "filename": "live.txt", "content": content})

    assert response.status_code == 201
    with app.app_context():
        dataset = db.session.get(CanDataset, response.get_json()["id"])
        assert (dataset.kind, dataset.source, dataset.summary["format"]) == ("live_capture", "web", "wecar_elm")

    empty = admin_client.post("/admin/canlab/live", data={"csrf_token": token, "vehicle": "x", "content": ""})
    assert empty.status_code == 400 and "빈 파일" in empty.get_json()["message"]


def _elm_reply(payload: bytes) -> str:
    return "\r".join("7EC " + " ".join(f"{b:02X}" for b in frame) for frame in isotp_frames(payload))


def _elm_capture() -> str:
    """웹 블루투스 수집이 만드는 '# WECAR-ELM 1' 기록."""
    return elm_from_exchanges([
        {"t_ms": 10, "header": "7E4", "command": "220101",
         "reply": _elm_reply(bms_0101(soc=37.5, voltage=256.5, current=5.5, cell_max=3.56, cell_min=3.54))},
        {"t_ms": 20, "header": "7E4", "command": "1902FF", "reply": "7EC 03 59 02 FF"},
        {"t_ms": 30, "header": "7E4", "command": "22F190", "reply": _elm_reply(b"\x62\xF1\x90TESTVIN0000123456")},
    ], {"vehicle": "아이오닉5", "source": "web"})


def test_live_preview_interprets_without_saving(app, client, admin_client, trained):
    token = csrf_token(admin_client, "/admin/canlab/live")
    with app.app_context():
        before = db.session.scalar(select(func.count(CanDataset.id)))

    response = admin_client.post("/admin/canlab/live/preview", data={"csrf_token": token, "content": _elm_capture()})

    assert response.status_code == 200
    body = response.get_json()
    values = {v["key"]: v for v in body["values"]}
    assert values["soc"]["value"] == 37.5 and values["soc"]["unit"] == "%"
    assert values["pack_voltage"]["value"] == 256.5
    assert body["vin"] == "TESTVIN0000******"
    assert [e["request_id"] for e in body["ecus"]] == ["7E4"]
    assert body["dtcCheckedEcus"] == ["7E4"] and body["dtcs"] == {"7E4": []}
    with app.app_context():
        assert db.session.scalar(select(func.count(CanDataset.id))) == before

    no_reply = admin_client.post("/admin/canlab/live/preview", data={
        "csrf_token": token, "content": "# WECAR-ELM 1\n10.0 TX 7E4 03 22 01 01\n"})
    assert no_reply.status_code == 400 and "진단 요청·응답을 찾지 못했습니다" in no_reply.get_json()["message"]
    assert admin_client.post("/admin/canlab/live/preview", data={"content": _elm_capture()}).status_code == 400
    assert client.post("/admin/canlab/live/preview", data={"content": _elm_capture()}).status_code in (302, 400)


def test_live_capture_can_create_report_directly(app, admin_client, trained):
    token = csrf_token(admin_client, "/admin/canlab/live")
    response = admin_client.post("/admin/canlab/live", data={
        "csrf_token": token, "vehicle": "아이오닉5", "filename": "quick.txt", "content": _elm_capture(), "report": "1"})

    assert response.status_code == 201
    report_url = response.get_json()["report_url"]
    assert re.fullmatch(r"/admin/canlab/reports/\d+", report_url)
    assert "37.5%" in admin_client.get(report_url).get_data(as_text=True)


def _obd_config(html: str) -> dict:
    match = re.search(r'<script type="application/json" id="obd-config">(.*?)</script>', html, re.S)
    return json.loads(match.group(1))


def test_live_page_connects_without_profiles(app, admin_client, trained):
    html = admin_client.get("/admin/canlab/live").get_data(as_text=True)
    assert "진단기 연결" in html and "자동 감지" in html
    assert "js/components/obd-link.js" in html and "js/components/obd-ble.js" in html
    config = _obd_config(html)
    assert config["profiles"] == [] and config["fromRules"] is True
    assert {"header": "7E4", "command": "220101"} in config["requests"]
    assert {"header": "7E4", "command": "1902FF"} in config["requests"]
    assert config["saveUrl"] == "/admin/canlab/live" and config["previewUrl"] == "/admin/canlab/live/preview"
    assert config["devices"] == [] and config["devicesUrl"] == "/admin/obd/my-devices"
    assert "js/components/obd-plan.js" in html and "js/components/obd-driver.js" in html
    assert html.index("obd-driver.js") < html.index("obd-link.js")

    with app.app_context():
        db.session.add(ObdProfile(name="vLinker", transport="ble", device_name_prefix="vLinker",
                                  service_uuid="fff0", write_uuid="fff2", notify_uuid="fff1",
                                  init_commands=["ATZ", "ATE0"], read_commands=["220101"]))
        db.session.commit()
    config = _obd_config(admin_client.get("/admin/canlab/live").get_data(as_text=True))
    assert config["profiles"] == [{"id": config["profiles"][0]["id"], "name": "vLinker", "namePrefix": "vLinker",
                                   "service": "fff0", "write": "fff2", "notify": "fff1",
                                   "init": ["ATZ", "ATE0"], "timeout": 2000, "dialect": "elm327",
                                   "canBitrate": None}]


def test_dashboard_has_bluetooth_card(app, admin_client, trained):
    html = admin_client.get("/admin/").get_data(as_text=True)

    assert "블루투스 진단기" in html and "빠른 점검" in html and "결과지로 저장" in html
    assert "js/components/obd-link.js" in html and "js/components/obd-dashboard.js" in html
    assert 'id="obd-quick"' in html and 'name="csrf_token"' in html
    config = _obd_config(html)
    assert {"header": "7E4", "command": "220101"} in config["requests"]
    assert config["previewUrl"] == "/admin/canlab/live/preview"


def test_live_page_without_rules_uses_profile_commands(app, admin_client):
    with app.app_context():
        db.session.add(ObdProfile(name="vLinker", transport="ble", device_name_prefix="vLinker",
                                  service_uuid="fff0", write_uuid="fff2", notify_uuid="fff1",
                                  request_header="7E4", response_header="7EC", read_commands=["220105"]))
        db.session.commit()
    config = _obd_config(admin_client.get("/admin/canlab/live").get_data(as_text=True))
    assert config["requests"] == [{"header": "7E4", "command": "220105"}] and config["fromRules"] is False


# ── 차종·제조사 범위, 확대, 되돌리기, 문제 로그 ───────────────────────────

def test_rules_are_picked_model_then_maker_then_common(app):
    with app.app_context():
        _rule("soc", 5)
        _rule("soc", 6, "기아")
        _rule("soc", 7, "기아", "EV6")
        _rule("max_temp", 8, "현대", "아이오닉5")
        db.session.commit()

        assert service.rules_for(EV6)["soc"].start == 7
        assert service.rules_for(NIRO)["soc"].start == 6
        assert service.rules_for(IONIQ5)["soc"].start == 5 and service.rules_for(IONIQ5)["max_temp"].start == 8
        assert "max_temp" not in service.rules_for(EV6)
        assert service.rules_for(None)["soc"].start == 5
        assert service.rules_for({"diag_company": " 기아 ", "diag_model": "ev6"})["soc"].start == 7
        assert service.capture_requests(IONIQ5) == [{"header": "7E4", "command": "220101"},
                                                    {"header": "7E4", "command": "1902FF"},
                                                    {"header": "7E4", "command": "22F190"}]


def test_scoped_rules_apply_only_to_matching_cars(app, admin_client, trained):
    with app.app_context():
        assert {r.signal_key for r in service.active_rule_refs(EV6)} >= {"soc", "pack_voltage"}
        assert service.active_rule_refs(IONIQ5) == [] and service.active_rule_refs(NIRO) == []
        assert service.capture_requests(IONIQ5) == []
        assert {"header": "7E4", "command": "220101"} in service.capture_requests(EV6)
        # 차량 정보가 없으면(실시간 수집·앱 기본) 가장 최근에 적용한 범위 규칙을 쓴다.
        assert {r.signal_key for r in service.active_rule_refs(None)} >= {"soc"}


def test_backtest_worse_candidate_keeps_current_rule():
    items = [{"key": "sig:soc", "kind": "signal", "signal_key": "soc", "before": {"rule_id": 1}, "after": {},
              "default": "after"},
             {"key": "sig:soh", "kind": "signal", "signal_key": "soh", "before": None, "after": {}, "default": "after"}]
    service._apply_backtest(items, {"signals": {"soc": {"verdict": "악화"}, "soh": {"verdict": "악화"}}})
    assert [i["default"] for i in items] == ["before", "exclude"] and "과거 데이터" in items[0]["note"]


def test_expand_to_maker_then_rollback_leaves_model_scope(app, admin_client, trained):
    page = f"/admin/canlab/logics/{trained['logic']}"
    assert "같은 제조사(기아)로 확대" in admin_client.get(page).get_data(as_text=True)

    response = _post(admin_client, f"{page}/expand", page)
    assert response.status_code == 302
    expansion = int(re.search(r"/logics/(\d+)", response.headers["Location"]).group(1))
    with app.app_context():
        logic = db.session.get(ScanLogic, expansion)
        assert (logic.maker, logic.model, logic.status) == ("기아", None, LogicStatus.DRAFT)
        assert logic.diff["action"] == "expand" and logic.diff["from_logic"] == trained["logic"]
        assert logic.diff["backtest"]["scope"] == "제조사 기아"
    assert "제조사 기아에 적용합니다" in admin_client.get(f"/admin/canlab/logics/{expansion}").get_data(as_text=True)

    assert _confirm(app, admin_client, expansion).status_code == 302
    with app.app_context():
        assert service.active_rule("soc", "기아", None) is not None
        assert service.rules_for(NIRO)["soc"].maker == "기아" and service.rules_for(NIRO)["soc"].model is None
        assert service.rules_for(EV6)["soc"].model == "EV6"
        assert service.active_logic(NIRO).id == expansion and service.active_logic(EV6).id == trained["logic"]
        change = db.session.scalar(select(RuleChange).where(RuleChange.action == "expand"))

    assert _post(admin_client, f"/admin/canlab/changes/{change.id}/rollback", "/admin/canlab/rules").status_code == 302
    with app.app_context():
        assert service.active_rule("soc", "기아", None) is None and service.active_logic(NIRO) is None
        assert service.active_logic(EV6).id == trained["logic"]
        assert service.rules_for(EV6)["soc"].model == "EV6"
        assert db.session.scalar(select(Activity.relation_type).where(
            Activity.relation_type == "디코딩 규칙 되돌리기")) is not None

    expand_draft = _post(admin_client, f"/admin/canlab/logics/{expansion}/expand", page)
    assert expand_draft.status_code == 302 and "적용 중인 차종 로직만" in admin_client.get(
        expand_draft.headers["Location"]).get_data(as_text=True)


def test_logic_problems_are_logged_and_listed(app, admin_client, trained):
    with app.app_context():
        logic = db.session.get(ScanLogic, trained["logic"])
        count = service.record_incidents(77, logic, [
            {"group": "logic", "label": "BMS 220101", "header": "7E4", "command": "220101", "message": "시간 초과"},
            {"group": "lookup", "label": "차량정보 조회", "message": "무시"}])
        db.session.commit()
        assert count == 1
        incident = db.session.scalar(select(RuleIncident))
        assert (incident.scan_id, incident.maker, incident.model, incident.command) == (77, "기아", "EV6", "7E4 220101")

    html = admin_client.get("/admin/canlab/rules").get_data(as_text=True)
    assert "문제 로그" in html and "시간 초과" in html and "/admin/scan/77" in html


# ── 참고자료 DB ──────────────────────────────────────────────────────────

def _register(client, address: str, **data):
    page = "/admin/canlab/references"
    return client.post(f"{page}/url", data={"csrf_token": csrf_token(client, page), "url": address, **data})


def test_reference_url_must_be_public_https(app, admin_client):
    for url in ("http://example.com/can", "https://127.0.0.1/x", "https://10.0.0.5/x", "https://[::1]/x",
                "https://user:pw@example.com/x", "https://example.com:8443/x", "ftp://example.com/x"):
        with pytest.raises(service.ServiceError):
            references.check_url(url)

    response = _register(admin_client, "https://169.254.169.254/latest/meta-data")
    assert response.status_code == 400 and "내부·사설 네트워크 주소" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.scalar(select(CanReference.id)) is None


def test_reference_url_is_extracted_by_ai_and_used_only_after_approval(app, admin_client, monkeypatch):
    monkeypatch.setattr(references, "check_url", lambda url: url)
    monkeypatch.setattr(references, "fetch_text", lambda url: ("7E4 22 0105 byte 9 SOH x0.1", "BMS PID 표"))
    sent = {}

    def fake_extract(text, maker, model):
        sent.update(text=text, maker=maker, model=model)
        return [{"signal_key": "soh", "request_id": "7E4", "did": "0105", "start": 9, "width": 2, "scale": 0.1,
                 "note": "SOH"},
                {"signal_key": "unknown", "request_id": "7E4", "did": "0105", "start": 1, "width": 1},
                {"signal_key": "soc", "request_id": "7E4", "did": "0101", "start": 400, "width": 1},
                {"signal_key": "soc", "request_id": "7E4", "did": "0101", "start": 4, "width": 3},
                {"signal_key": "soc", "request_id": "XYZ", "did": "0101", "start": 4, "width": 1}], "openai"

    monkeypatch.setattr(ai, "extract_references", fake_extract)
    page = "/admin/canlab/references"
    response = _register(admin_client, "https://example.com/bms", maker="기아", model="EV6")
    assert response.status_code == 302
    soh = ("soh", Layout(0x7E4, 0x0105, 9, 2, scale=0.1))
    with app.app_context():
        ref = db.session.scalar(select(CanReference))
        assert (ref.status, ref.title, ref.ai_provider) == (ReferenceStatus.PENDING, "BMS PID 표", "openai")
        assert [i["signal_key"] for i in ref.items] == ["soh"] and sent["maker"] == "기아"
        assert soh not in references.hypotheses(EV6)
        ref_id, version = ref.id, ref.version
    html = admin_client.get(page).get_data(as_text=True)
    assert "BMS PID 표" in html and "검토 대기" in html and "해석 항목 1개" in html

    stale = _post(admin_client, f"{page}/{ref_id}/approve", page, version=str(version + 1))
    assert stale.status_code == 409
    assert _post(admin_client, f"{page}/{ref_id}/approve", page, version=str(version)).status_code == 302
    with app.app_context():
        assert db.session.get(CanReference, ref_id).status == ReferenceStatus.APPROVED
        assert references.hypotheses(EV6)[soh] == [f"참고자료 #{ref_id}"]
        assert soh not in references.hypotheses(IONIQ5) and soh not in references.hypotheses(None)
    duplicate = _register(admin_client, "https://example.com/bms")
    assert duplicate.status_code == 409


def test_obdb_sync_saves_approved_references(app, admin_client, monkeypatch):
    data = {"commands": [{"hdr": "7E4", "cmd": {"22": "0101"}, "signals": [
        {"id": "EV6_HVBAT_SOC", "fmt": {"bix": 32, "len": 8, "div": 2, "max": 100}},
        {"id": "EV6_ODD_BITS", "fmt": {"bix": 3, "len": 5}}]}]}

    def fake_fetch(client, repo):
        if repo != "Kia-EV6":
            raise references.httpx.ConnectError("offline")
        return data

    monkeypatch.setattr(references, "fetch_obdb", fake_fetch)
    page = "/admin/canlab/references"
    bad = _post(admin_client, f"{page}/sync", page, repo="../etc", keywords="x")
    assert bad.status_code == 400 and "저장소 이름" in bad.get_data(as_text=True)

    response = _post(admin_client, f"{page}/sync", page)
    assert response.status_code == 302
    with app.app_context():
        ref = db.session.scalar(select(CanReference))
        assert (ref.source_type, ref.status, ref.maker, ref.model, ref.license) == (
            "obdb", ReferenceStatus.APPROVED, "기아", "EV6", "CC-BY-SA-4.0")
        assert [(i["signal_key"], i["start"], i["scale"]) for i in ref.items] == [("soc", 4, 0.5)]
        assert references.hypotheses(EV6)[("soc", Layout(0x7E4, 0x0101, 4, 1, scale=0.5))][-1] == f"참고자료 #{ref.id}"
    assert "받지 못한 저장소" in admin_client.get(page).get_data(as_text=True)

    assert _post(admin_client, f"{page}/sync", page).status_code == 302
    with app.app_context():
        assert db.session.scalar(select(func.count(CanReference.id))) == 1


def test_compare_tab_and_scan_wescan_compare(app, admin_client, trained):
    html = admin_client.get("/admin/canlab/compare").get_data(as_text=True)
    assert "스캔·위스캔 비교" in html and "비교하고 후보 만들기" in html
    assert str(trained["wescan"]) in html

    token = csrf_token(admin_client, "/admin/canlab/compare")
    response = admin_client.post("/admin/canlab/compare", content_type="multipart/form-data", data={
        "csrf_token": token, "dataset_id": str(trained["wescan"]), "values_text": TRUTHS,
        "scan_file": (io.BytesIO(b""), ""),
    })
    assert response.status_code == 302, response.get_data(as_text=True)
    compare_id = int(re.search(r"/compare/(\d+)", response.headers["Location"]).group(1))
    show = admin_client.get(f"/admin/canlab/compare/{compare_id}").get_data(as_text=True)
    assert "신호별 차이" in show and "디코딩 규칙 후보" in show
    with app.app_context():
        row = db.session.get(ScanWescanCompare, compare_id)
        assert row.scan_dataset_id == trained["wescan"] and row.logic_id and row.diff
        assert db.session.get(ScanLogic, row.logic_id).status == LogicStatus.DRAFT


def test_compare_upload_file_without_dataset(app, admin_client, trained):
    token = csrf_token(admin_client, "/admin/canlab/compare")
    # 이미 올린 위스캔 TRC와 SHA가 겹치지 않게 다른 응답을 쓴다.
    content = trc(exchange(0x7E4, b"\x22\x01\x01", bms_0101(soc=40.0, voltage=260.0))).encode()
    response = admin_client.post("/admin/canlab/compare", content_type="multipart/form-data", data={
        "csrf_token": token, "dataset_id": "0",
        "scan_file": (io.BytesIO(content), "scan-compare.txt"),
        "values_text": "배터리 충전 상태(BMS) | 40 | %\n배터리 팩 전압 | 260 | V\n",
    })
    assert response.status_code == 302, response.get_data(as_text=True)
    with app.app_context():
        row = db.session.scalar(select(ScanWescanCompare).order_by(ScanWescanCompare.id.desc()))
        assert row is not None and row.scan_dataset.kind == "live_capture"
        assert row.scan_dataset.filename == "scan-compare.txt"


def test_compare_requires_scan_and_truths(admin_client):
    token = csrf_token(admin_client, "/admin/canlab/compare")
    empty = admin_client.post("/admin/canlab/compare", content_type="multipart/form-data", data={
        "csrf_token": token, "dataset_id": "0", "values_text": "",
    })
    assert empty.status_code == 400
    assert "스캔 통신기록" in empty.get_data(as_text=True) or "고르거나" in empty.get_data(as_text=True)
