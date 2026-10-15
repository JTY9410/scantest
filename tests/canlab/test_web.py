import io
import json
import re

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.core.audit import Activity
from app.extensions import db
from app.modules.canlab import ai, service
from app.modules.canlab.engine.frames import elm_from_exchanges
from app.modules.canlab.engine.search import Layout
from app.modules.canlab.models import (
    AnalysisRun,
    CanDataset,
    DecodeRule,
    DiagnosticReport,
    GroundTruthValue,
    LogicStatus,
    RuleStatus,
    ScanLogic,
)
from app.modules.obd.models import ObdProfile
from app.modules.scanner.plan import build_plan
from tests.canlab.synthetic import bms_0101, bms_session, exchange, isotp_frames, trc
from tests.conftest import csrf_token

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


def _upload_wescan(client, content: bytes = None, values: str = TRUTHS, filename: str = "wescan.trc", **extra):
    token = csrf_token(client, "/admin/canlab/wescan")
    content = bms_session(count=1).encode() if content is None else content
    return client.post("/admin/canlab/wescan", content_type="multipart/form-data", data={
        "csrf_token": token, "file": (io.BytesIO(content), filename), "vehicle": "EV6 시험차",
        "values_text": values, **extra,
    })


def _upload_reverse(client, content: bytes = None, filename: str = "reverse.trc"):
    token = csrf_token(client, "/admin/canlab/reverse")
    content = _reverse_trace().encode() if content is None else content
    return client.post("/admin/canlab/reverse", content_type="multipart/form-data", data={
        "csrf_token": token, "file": (io.BytesIO(content), filename), "vehicle": "EV6 시험차",
    })


def _analyse(client, wescan_id: int, reverse_id: int):
    return _post(client, "/admin/canlab/analysis", "/admin/canlab/analysis",
                 wescan_id=str(wescan_id), reverse_ids=str(reverse_id))


def _run_id(response) -> int:
    return int(response.headers["Location"].rsplit("/", 1)[1])


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
    """위스캔 데이터(최종값 포함)와 리버스 데이터를 올리고 역산 분석까지 마친 상태(적용 전)."""
    wescan_id = _dataset_id(_upload_wescan(admin_client))
    reverse_id = _dataset_id(_upload_reverse(admin_client))
    response = _analyse(admin_client, wescan_id, reverse_id)
    assert response.status_code == 302
    return {"wescan": wescan_id, "reverse": reverse_id, "run": _run_id(response)}


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


def test_wescan_upload_extracts_commands_and_final_values(app, admin_client):
    response = _upload_wescan(admin_client)

    assert response.status_code == 302
    html = admin_client.get(response.headers["Location"]).get_data(as_text=True)
    assert "추출한 명령과 산출 결과" in html and "위스캔 최종값(정답값)" in html
    assert "220101" in html and "31 " in html
    with app.app_context():
        dataset = db.session.scalar(select(CanDataset))
        assert dataset.kind == "wecan_trc"
        commands = {(c["header"], c["command"]): c for c in dataset.summary["commands"]}
        assert commands[("7E4", "220101")]["positive"] == 1 and commands[("7E4", "220101")]["sendable"] is True
        assert commands[("7E4", "22010A")]["negative"].startswith("31 ")
        assert [t.signal_key for t in sorted(dataset.truths, key=lambda t: t.id)][:5] == [
            "soc", "pack_voltage", "pack_current", "max_cell_v", "min_cell_v"]
    page = admin_client.get("/admin/canlab/wescan").get_data(as_text=True)
    assert "wescan.trc" in page and "위스캔값 입력" in page


def test_wescan_values_from_csv_file_and_missing_values(app, admin_client):
    csv = "배터리 충전 상태(BMS),94.5,%\n배터리 팩 전압,785.5,V\n".encode()
    response = _upload_wescan(admin_client, values="", values_file=(io.BytesIO(csv), "values.csv"))
    assert response.status_code == 302
    with app.app_context():
        assert {t.signal_key for t in db.session.scalars(select(GroundTruthValue))} == {"soc", "pack_voltage"}

    missing = _upload_wescan(admin_client, content=bms_session(count=2).encode(), values="메모만 있음")
    assert missing.status_code == 400 and "위스캔 최종값을" in missing.get_data(as_text=True)


def test_wescan_values_from_text_pdf_are_unconfirmed(app, admin_client):
    pdf = _text_pdf("위스캔 진단 결과", "배터리 충전 상태(BMS) 94.5 %", "배터리 팩 전압 785.5 V")
    response = _upload_wescan(admin_client, values="최소 셀 전압 | 4.06 | V",
                              values_file=(io.BytesIO(pdf), "result.pdf"))

    assert response.status_code == 302
    assert "PDF에서 읽은 2개는 아래 표에서 확인하고 확정하세요" in admin_client.get(
        response.headers["Location"]).get_data(as_text=True)
    with app.app_context():
        rows = db.session.scalars(select(GroundTruthValue).order_by(GroundTruthValue.id)).all()
        assert [(r.signal_key, r.confirmed, r.source, r.page) for r in rows] == [
            ("min_cell_v", True, "manual", None),
            ("soc", False, "pdf_text", 1), ("pack_voltage", False, "pdf_text", 1)]


def test_wescan_values_from_image_pdf_use_ai(app, admin_client, monkeypatch):
    no_ai = _upload_wescan(admin_client, values="", values_file=(io.BytesIO(_pdf()), "scan.pdf"))
    assert no_ai.status_code == 400 and "PDF에 글자가 없어 AI 판독이 필요합니다" in no_ai.get_data(as_text=True)
    with app.app_context():
        assert db.session.scalar(select(func.count(CanDataset.id))) == 0

    monkeypatch.setattr(ai, "read_table", lambda image=None, page_text=None: (
        [{"label": "배터리 팩 전압", "value": "785.5", "unit": "V"},
         {"label": "고객 메모", "value": "확인 필요", "unit": ""}], "openai"))
    response = _upload_wescan(admin_client, values="", values_file=(io.BytesIO(_pdf()), "scan.pdf"))

    assert response.status_code == 302
    with app.app_context():
        rows = db.session.scalars(select(GroundTruthValue)).all()
        assert [(r.signal_key, r.confirmed, r.source, r.page) for r in rows] == [("pack_voltage", False, "ai_ocr", 1)]


def test_reverse_upload_extracts_commands(app, admin_client):
    response = _upload_reverse(admin_client)

    assert response.status_code == 302
    with app.app_context():
        dataset = db.session.scalar(select(CanDataset))
        assert dataset.kind == "gscan_trc"
        assert [c["command"] for c in dataset.summary["commands"]] == ["220101", "220105"]
    assert "reverse.trc" in admin_client.get("/admin/canlab/reverse").get_data(as_text=True)


def test_analysis_compares_commands_and_finds_formulas_without_applying(app, admin_client, analysed):
    html = admin_client.get(f"/admin/canlab/analysis/{analysed['run']}").get_data(as_text=True)

    assert "명령 비교" in html and "b12~b13" in html and "def decode_soc" in html
    assert 'action="/admin/canlab/analysis/%d/apply"' % analysed["run"] in html
    with app.app_context():
        assert db.session.scalar(select(DecodeRule.id)) is None
        run = db.session.get(AnalysisRun, analysed["run"])
        assert run.reverse_dataset_ids == [analysed["reverse"]] and run.truth_dataset_id == analysed["wescan"]
        assert [c["command"] for c in run.commands["common"]] == ["220101"]
        assert [c["command"] for c in run.commands["reverse_only"]] == ["220105"]
        assert "22010A" in [c["command"] for c in run.commands["wescan_only"]]
        assert run.result["soc"]["status"] == "확정" and run.result["soc"]["formula"] == "b4(무부호 8비트) × 0.5"


def test_analysis_requires_wescan_and_reverse(app, admin_client):
    wescan_id = _dataset_id(_upload_wescan(admin_client))
    response = _post(admin_client, "/admin/canlab/analysis", "/admin/canlab/analysis", wescan_id=str(wescan_id))
    assert response.status_code == 400
    with app.app_context():
        assert db.session.scalar(select(AnalysisRun.id)) is None


def test_apply_shows_before_after_and_confirm_changes_scan_logic(app, admin_client, analysed):
    logic_id = _draft(admin_client, analysed["run"])
    html = admin_client.get(f"/admin/canlab/logics/{logic_id}").get_data(as_text=True)
    assert "변경 전" in html and "변경 후" in html and "AI 최적안 받기" in html
    assert 'name="choice-sig:soc"' in html and "고른 항목으로 적용 확정" in html
    with app.app_context():
        logic = db.session.get(ScanLogic, logic_id)
        items = {i["key"]: i for i in logic.diff["items"]}
        assert logic.status == LogicStatus.DRAFT and service.active_logic() is None
        assert items["sig:soc"]["change"] == "added" and items["sig:soc"]["default"] == "after"
        assert items["cmd:7E4:220101"]["change"] == "added"
        assert "cmd:7E4:220105" not in items
        assert db.session.scalar(select(DecodeRule.id)) is None

    response = _confirm(app, admin_client, logic_id, **{"cmd:7E4:22010A": "exclude"})

    assert response.status_code == 302
    with app.app_context():
        logic = db.session.get(ScanLogic, logic_id)
        assert logic.status == LogicStatus.ACTIVE and service.active_logic().id == logic_id
        commands = [(c["header"], c["command"]) for c in logic.commands]
        assert ("7E4", "220101") in commands and ("7E4", "22010A") not in commands
        assert {r["signal_key"] for r in logic.rules} >= {"soc", "pack_voltage", "pack_current"}
        active = {r.signal_key: r for r in db.session.scalars(
            select(DecodeRule).where(DecodeRule.status == RuleStatus.ACTIVE))}
        assert active["soc"].formula == "b4(무부호 8비트) × 0.5" and active["pack_current"].signed is True
        assert db.session.get(AnalysisRun, analysed["run"]).activated_count == len(active)
        steps = [s for s in build_plan({})["steps"] if s["group"] == "rule"]
        logic_step = next(s for s in steps if s["command"] == "220101")
        assert logic_step["header"] == "7E4" and logic_step["label"].startswith("스캔 로직:")
        assert sum(1 for s in steps if (s["header"], s["command"]) == ("7E4", "220101")) == 1
        actions = db.session.scalars(select(Activity.relation_type).where(Activity.relation == "ScanLogic")).all()
        assert actions == ["스캔 로직 초안", "스캔 로직 적용"]

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


def test_new_logic_replaces_old_and_restore_brings_back_rules(app, admin_client, trained):
    run_id = _run_id(_analyse(admin_client, trained["wescan"], trained["reverse"]))
    second = _draft(admin_client, run_id)
    with app.app_context():
        items = {i["key"]: i for i in db.session.get(ScanLogic, second).diff["items"]}
        assert items["sig:soc"]["change"] == "same" and items["cmd:7E4:220101"]["change"] == "same"

    _confirm(app, admin_client, second, **{"sig:soc": "exclude"})
    with app.app_context():
        assert service.active_rule("soc") is None
        assert db.session.get(ScanLogic, trained["logic"]).status == LogicStatus.RETIRED
        assert db.session.scalar(select(func.max(DecodeRule.revision)).where(DecodeRule.signal_key == "soc")) == 1
        version = db.session.get(ScanLogic, trained["logic"]).version
    assert "스캔 로직 버전" in admin_client.get("/admin/canlab/rules").get_data(as_text=True)

    page = f"/admin/canlab/logics/{trained['logic']}"
    stale = _post(admin_client, f"{page}/restore", "/admin/canlab/rules", version=str(version + 3))
    assert stale.status_code == 409
    assert _post(admin_client, f"{page}/restore", "/admin/canlab/rules", version=str(version)).status_code == 302
    with app.app_context():
        assert service.active_logic().id == trained["logic"]
        assert service.active_rule("soc") is not None
        assert db.session.get(ScanLogic, second).status == LogicStatus.RETIRED


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
            layout = Layout(0x7E4, 0x0101, start, 1)
            db.session.add(DecodeRule(signal_key=key, revision=1, status=RuleStatus.ACTIVE, confidence=0.9,
                                      evidence={}, formula=layout.formula(), **layout.to_dict()))
        db.session.commit()
    wescan_id = _dataset_id(_upload_wescan(admin_client))
    reverse_id = _dataset_id(_upload_reverse(admin_client))

    run_id = _run_id(_analyse(admin_client, wescan_id, reverse_id))

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
        for model in (CanDataset, GroundTruthValue, AnalysisRun, DecodeRule, ScanLogic, DiagnosticReport):
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
        assert service.active_rule("soc") is None
        version = db.session.get(DecodeRule, rule_id).version

    assert _post(admin_client, f"/admin/canlab/rules/{rule_id}/activate", "/admin/canlab/rules",
                 version=str(version)).status_code == 302
    with app.app_context():
        assert service.active_rule("soc").id == rule_id
        actions = db.session.scalars(select(Activity.relation_type).where(Activity.relation == "DecodeRule")).all()
        assert actions == ["디코딩 규칙 해제", "디코딩 규칙 적용"]


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
