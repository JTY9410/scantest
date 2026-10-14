import io
import re

import pytest
from PIL import Image
from sqlalchemy import select

from app.core.audit import Activity
from app.extensions import db
from app.modules.canlab import ai, service
from app.modules.canlab.engine.search import Layout
from app.modules.canlab.models import AnalysisRun, CanDataset, DecodeRule, GroundTruthValue, RuleStatus
from app.modules.obd.models import ObdProfile
from tests.canlab.synthetic import bms_0101, bms_session, exchange, trc
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


def _analyse(client, trace_id: int, truth_id: int, apply: bool = True):
    extra = {"apply": "y"} if apply else {}
    return _post(client, "/admin/canlab/analysis", "/admin/canlab/analysis",
                 trace_ids=str(trace_id), truth_dataset_id=str(truth_id), **extra)


@pytest.fixture
def trained(app, admin_client):
    """G스캔 기록 + 정답값 PDF를 올리고 역산까지 마친 상태."""
    trace_id = _dataset_id(_upload(admin_client, bms_session(count=1).encode(), "gscan.trc", "gscan_trc"))
    pdf_id = _dataset_id(_upload(admin_client, _pdf(), "result.pdf", "gscan_pdf"))
    page = f"/admin/canlab/datasets/{pdf_id}"
    _post(admin_client, f"{page}/truths/add", page, text=TRUTHS)
    response = _analyse(admin_client, trace_id, pdf_id)
    assert response.status_code == 302
    return {"trace": trace_id, "pdf": pdf_id, "run": int(response.headers["Location"].rsplit("/", 1)[1])}


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


def test_analysis_activates_validated_rules_and_report_applies_them(app, admin_client, trained):
    run_html = admin_client.get(f"/admin/canlab/analysis/{trained['run']}").get_data(as_text=True)
    assert "확정" in run_html and "b12~b13" in run_html

    with app.app_context():
        active = {r.signal_key: r for r in db.session.scalars(
            select(DecodeRule).where(DecodeRule.status == RuleStatus.ACTIVE))}
        assert {"soc", "pack_voltage", "pack_current", "max_cell_v", "min_cell_v"} <= set(active)
        assert active["soc"].formula == "b4(무부호 8비트) × 0.5"
        assert active["pack_current"].signed is True

    wecan_id = _dataset_id(_upload(admin_client, _wecan_trace().encode(), "wecan.trc", "wecan_trc", "그랜저 HEV"))
    response = _post(admin_client, "/admin/canlab/reports", "/admin/canlab/reports", dataset_id=str(wecan_id))
    assert response.status_code == 302
    html = admin_client.get(response.headers["Location"]).get_data(as_text=True)
    assert "37.5" in html and "256.5" in html and "3.56" in html
    assert 'id="report-data"' in html and "vendor/chart.umd.min.js" in html
    assert "1. 종합: 충전 상태(SOC) 37.5%" in html


def test_second_analysis_keeps_same_rules_without_new_versions(app, admin_client, trained):
    _analyse(admin_client, trained["trace"], trained["pdf"])

    with app.app_context():
        assert db.session.scalar(select(DecodeRule.revision).where(DecodeRule.signal_key == "soc")
                                 .order_by(DecodeRule.revision.desc())) == 1


def test_validate_only_run_leaves_rules_untouched(app, admin_client):
    trace_id = _dataset_id(_upload(admin_client, bms_session(count=1).encode(), "gscan.trc", "gscan_trc"))
    pdf_id = _dataset_id(_upload(admin_client, _pdf(), "result.pdf", "gscan_pdf"))
    page = f"/admin/canlab/datasets/{pdf_id}"
    _post(admin_client, f"{page}/truths/add", page, text=TRUTHS)

    response = _analyse(admin_client, trace_id, pdf_id, apply=False)

    assert response.status_code == 302
    with app.app_context():
        assert db.session.scalar(select(DecodeRule.id)) is None
    html = admin_client.get(response.headers["Location"]).get_data(as_text=True)
    assert "검증만(적용 안 함)" in html and "확정" in html


def test_analysis_never_replaces_or_overlaps_active_rules_automatically(app, admin_client):
    with app.app_context():
        for key, start in (("soc", 5), ("max_temp", 12)):
            layout = Layout(0x7E4, 0x0101, start, 1)
            db.session.add(DecodeRule(signal_key=key, revision=1, status=RuleStatus.ACTIVE, confidence=0.9,
                                      evidence={}, formula=layout.formula(), **layout.to_dict()))
        db.session.commit()
    trace_id = _dataset_id(_upload(admin_client, bms_session(count=1).encode(), "gscan.trc", "gscan_trc"))
    pdf_id = _dataset_id(_upload(admin_client, _pdf(), "result.pdf", "gscan_pdf"))
    page = f"/admin/canlab/datasets/{pdf_id}"
    _post(admin_client, f"{page}/truths/add", page, text=TRUTHS)

    _analyse(admin_client, trace_id, pdf_id)

    with app.app_context():
        assert service.active_rule("soc").start == 5
        assert service.active_rule("pack_voltage") is None
        result = db.session.scalar(select(AnalysisRun.result))
        assert result["soc"]["status"] == "가설" and "자동으로 바꾸지 않았습니다" in result["soc"]["reasons"][0]
        assert "배터리 최대 온도" in result["pack_voltage"]["reasons"][0]
        assert service.active_rule("max_cell_v") is not None


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


def test_live_page_lists_requests_from_active_rules(app, admin_client, trained):
    assert "사용할 BLE 프로필이 없습니다" in admin_client.get("/admin/canlab/live").get_data(as_text=True)
    with app.app_context():
        db.session.add(ObdProfile(name="vLinker", transport="ble", device_name_prefix="vLinker",
                                  service_uuid="fff0", write_uuid="fff2", notify_uuid="fff1",
                                  init_commands=["ATZ", "ATE0"], read_commands=["220101"]))
        db.session.commit()

    html = admin_client.get("/admin/canlab/live").get_data(as_text=True)
    assert 'data-header="7E4" data-command="220101"' in html
    assert 'data-command="1902FF"' in html and "적용 중 규칙 기준" in html
    assert "js/components/obd-ble.js" in html
