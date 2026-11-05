"""PCAN 계열 CSV 파서, BMS 0101~010C 해석, SOH 연결, CSV 업로드·위스캔/지스캔 비교.

픽스처는 실차 로그에서 BMS(7E4/7EC) 프레임만 남기고 시각을 상대값으로 바꾼 것이다(VIN·번호판 없음).
"""

import io
import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app.extensions import db
from app.modules.canlab.engine import bms, sequence
from app.modules.canlab.engine.decode import load_trace
from app.modules.canlab.engine.frames import decode_text, detect_format, parse_trace
from app.modules.canlab.models import CanDataset
from app.modules.scanner import soh_estimation
from tests.canlab.synthetic import bms_session
from tests.conftest import csrf_token

FIXTURES = Path(__file__).parent.parent / "fixtures" / "csv"
HEADER = ("Timestamp,Channel,CAN_ID,DLC,Data,IDType,DataLength,FrameType,Remote,BRS,ESI,Status1,Status2,Status3,"
          "Status4,Protocol,NumberBytesData,DLCSource,PCTimeUTC,TimeHardware,TimeHardware2,TimeStampHardwareID,"
          "TimeSystem,TimeSystem2,TimeStampSystemID,Sequence,Connection,TimestampError")


def _row(t: float, can_id: int, data: str, status: str = "0x04000000", id_type: str = "Standard") -> str:
    dlc = len(data.split())
    return (f"{t},1,{can_id:08X},{dlc},{data},{id_type},{dlc},CAN,0,0,0,{status},0x00000000,0x00000000,0x00000000,"
            f"1,{dlc},derived_from_API_byte_count,2026-01-01T00:00:00+00:00,0,0,0,0,0,0,0,1,")


def _text(name: str) -> str:
    return decode_text((FIXTURES / name).read_bytes())


def test_csv_detected_and_status_rows_dropped():
    text = "\n".join([HEADER, _row(0.1, 0x7E4, "03 22 01 01 00 00 00 00"),
                      _row(0.2, 0, "00 00 00", status="0x84000205", id_type="Extended"),
                      _row(0.3, 0x316, "05 20 00 00 00 00 00 00")])
    parsed = parse_trace(text)
    assert detect_format(text) == "pcan_csv" and parsed.format == "pcan_csv"
    assert [f.can_id for f in parsed.frames] == [0x7E4, 0x316]
    assert parsed.frames[0].t_ms == 100.0 and parsed.meta["STATUS_ROWS"] == "1"


@pytest.mark.parametrize("transform", [
    lambda t: "\ufeff" + t,                       # BOM
    lambda t: t.replace("\n", "\r\n"),           # CRLF
    lambda t: t.replace(",", ";"),               # 세미콜론 구분자
])
def test_csv_variants(transform):
    text = "\n".join([HEADER, _row(0.1, 0x7E4, "03 22 01 01 00 00 00 00")])
    parsed = parse_trace(transform(text))
    assert parsed.format == "pcan_csv" and len(parsed.frames) == 1


def test_minimal_header_variant_and_cp949():
    text = "time,id,dlc,data\n0.5,7E4,8,03 22 01 05 00 00 00 00\n"
    parsed = parse_trace(decode_text(text.encode("cp949")))
    assert parsed.format == "pcan_csv" and parsed.frames[0].can_id == 0x7E4


def test_trc_still_parsed():
    assert parse_trace(bms_session(count=1)).format == "pcan_trc"


def test_direction_inferred_from_id_rule():
    trace = parse_trace(_text("ev_a_wescan.csv"))
    dirs = {f.can_id: f.direction for f in trace.frames}
    assert dirs[0x7E4] == "tx" and dirs[0x7EC] == "rx"


@pytest.mark.parametrize("name", ["ev_a_wescan.csv", "ev_a_gscan.csv"])
def test_bms_decoding_confirmed_fields(name):
    trace = load_trace(_text(name))
    result = bms.decode_bms(trace.samples, "아이오닉5")
    values = result["values"]
    assert result["platform"] == "egmp"
    assert result["cells"]["count"] == 192          # 2V 미만 패딩 제외
    assert result["soh"] == {"value": 99.4, "grade": "확인됨", "pid": "0105", "bytes": "25–26", "note": ""}
    assert 0 <= values["soc"] <= 100 and 600 < values["pack_voltage"] < 800
    # 자기검증: 셀 합계 ≈ 팩 전압(0.5% 이내), kWh/Ah ≈ 팩 공칭전압
    assert abs(result["checks"]["cell_sum_vs_pack_pct"]) < 0.5
    assert 650 < result["checks"]["charge_kwh_per_ah_v"] < 800
    grades = {f["key"]: f["grade"] for f in result["fields"]}
    assert grades["pack_current"] == "확인됨" and grades["aux_voltage"] == "유력"
    assert grades["inlet_temp"] == "유력"
    assert all(u["pid"] not in ("0101", "0105") for u in result["unverified"])


def test_inlet_temp_offset_by_platform():
    data = bytes(22) + bytes([0x37]) + bytes(40)
    samples = {(0x7E4, 0x0101): [(0.0, data)]}
    by = lambda hint: next(f for f in bms.decode_bms(samples, hint)["fields"] if f["key"] == "inlet_temp")  # noqa: E731
    assert by("아이오닉5")["value"] == 15
    assert by("포터EV")["value"] == 0x37
    assert by(None)["value"] is None and by(None)["grade"] == "미확인"


def test_hev_soh_is_only_likely():
    data = bytes(25) + (1000).to_bytes(2, "big") + bytes(20)
    result = bms.decode_bms({(0x7E4, 0x0105): [(0.0, data)]}, "그랜저 HEV")
    assert result["soh"]["value"] == 100.0 and result["soh"]["grade"] == "유력"


def test_command_sequence_and_tool_compare():
    a, b = (load_trace(_text(n)) for n in ("ev_a_wescan.csv", "ev_a_gscan.csv"))
    seq = sequence.command_sequence(b.transactions)
    assert seq["steps"][0]["request_id"] == "7E4" and seq["steps"][0]["service"] == "22"
    assert seq["latency_ms"]["median"] > 0
    result = sequence.compare_tools(a.transactions, b.transactions)
    assert result["dids"]["a"] < result["dids"]["b"] and result["dids"]["common"] >= 5
    assert set(result["verdicts"]) <= {"일치", "부분 일치", "불일치"}
    assert "7E4 0106" in result["dids"]["only_b"]


def test_soh_direct_value_first_and_canonical_keys():
    direct = soh_estimation.estimate_soh({"soh": 97.1, "cum_charge_ah": 13284, "cum_discharge_ah": 13000})
    assert direct.method == "bms_direct" and direct.soh == 97.1
    # 디코더 표준 키(cum_charge_ah)로도 누적 Ah 추정이 돈다(예전에는 battery_* 키만 찾아 건너뛰었다).
    by_ah = soh_estimation.estimate_soh({"cum_charge_ah": 5000, "cum_discharge_ah": 4750})
    assert by_ah.method == "coulomb_counting"
    legacy = soh_estimation.estimate_soh({"battery_cum_charge_ah": 5000, "battery_cum_discharge_ah": 4750})
    assert legacy.method == "coulomb_counting"
    ind = soh_estimation.battery_indicators({"cum_charge_kwh": 100, "cum_discharge_kwh": 97,
                                             "cum_charge_ah": 140, "max_cell_v": 3.72, "min_cell_v": 3.70})
    assert ind == {"efficiency_pct": 97.0, "kwh_per_ah_v": 714.3, "cell_spread_mv": 20}


def test_scanner_analysis_uses_estimate_without_crash():
    from app.modules.scanner.analysis import _ev

    battery = {k: {"value": v} for k, v in {"cum_charge_ah": 5000.0, "cum_discharge_ah": 4750.0}.items()}
    items = _ev({"battery": battery})
    soh = next(i for i in items if i["label"].startswith("배터리 건강"))
    assert soh["method"] == "estimated" and "(추정)" in soh["value"]


def _upload(client, content: bytes, filename: str, kind: str, **extra):
    token = csrf_token(client, "/admin/canlab/datasets")
    return client.post("/admin/canlab/datasets", content_type="multipart/form-data", data={
        "csrf_token": token, "file": (io.BytesIO(content), filename), "kind": kind, "vehicle": "아이오닉5 시험차",
        **extra})


def test_csv_upload_shows_bms_sequence_and_compare(app, admin_client):
    wescan = _upload(admin_client, (FIXTURES / "ev_a_wescan.csv").read_bytes(), "a_wescan.csv", "wecan_trc")
    assert wescan.status_code == 302, wescan.get_data(as_text=True)[:500]
    html = admin_client.get(wescan.headers["Location"]).get_data(as_text=True)
    assert "CSV(PCAN 계열)" in html and "배터리(BMS) 해석" in html and "명령 순서 리포트" in html
    assert "99.4 %" in html and "장비 상태 행 1개 제외" in html
    gscan = _upload(admin_client, (FIXTURES / "ev_a_gscan.csv").read_bytes(), "a_gscan.csv", "gscan_trc",
                    diagnostic_only="y")
    assert gscan.status_code == 302
    with app.app_context():
        rows = list(db.session.scalars(select(CanDataset).order_by(CanDataset.id)))
        assert [r.file_format for r in rows] == ["pcan_csv", "pcan_csv"]
        assert rows[1].summary["stored"]["diagnostic_only"] is True
        a, b = rows[0].id, rows[1].id
    page = admin_client.get(f"/admin/canlab/datasets/compare-tools?a={a}&b={b}")
    text = page.get_data(as_text=True)
    assert page.status_code == 200 and "공통 DID 응답 비교" in text and "7E4 22 0101" in text
    assert re.search(r"BMS 확인됨 항목 값 비교", text)


def test_csv_upload_respects_limit(app, admin_client, monkeypatch):
    monkeypatch.setitem(app.config, "CANLAB_MAX_UPLOAD_BYTES", 1000)
    response = _upload(admin_client, (FIXTURES / "ev_a_gscan.csv").read_bytes(), "big.csv", "gscan_trc")
    assert response.status_code == 413
