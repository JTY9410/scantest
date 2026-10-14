from app.modules.canlab.engine import uds
from app.modules.canlab.engine.decode import RuleRef, decode_signals, diagnose, load_trace
from app.modules.canlab.engine.frames import ELM_HEADER, parse_trace
from app.modules.canlab.engine.isotp import reassemble
from app.modules.canlab.engine.search import GroundTruth, Layout, search
from app.modules.canlab.engine.validate import judge
from tests.canlab.synthetic import bms_0101, bms_session, exchange, trc


def test_parse_pcan_trc_reads_frames_and_meta():
    parsed = parse_trace(bms_session(count=1))

    assert parsed.format == "pcan_trc"
    assert parsed.meta["FILEVERSION"] == "1.1"
    assert parsed.frames[0].can_id == 0x7E4
    assert parsed.frames[0].data[:4] == b"\x03\x22\x01\x01"
    assert parsed.skipped_lines == 0


def test_parse_elm_capture_with_tx_and_rx_lines():
    text = f"{ELM_HEADER}\n# device: OBDII\n0.0 TX 7E4 03 22 01 01\n12.5 RX 7EC 03 7F 22 31\n"
    parsed = parse_trace(text)

    assert parsed.format == "wecar_elm"
    assert parsed.meta["device"] == "OBDII"
    assert [(f.direction, f.can_id) for f in parsed.frames] == [("tx", 0x7E4), ("rx", 0x7EC)]


def test_isotp_reassembles_multi_frame_and_marks_broken_sequence():
    response = bms_0101()
    frames = parse_trace(trc(exchange(0x7E4, b"\x22\x01\x01", response))).frames
    messages = reassemble(frames)

    assert [m.payload for m in messages if m.can_id == 0x7EC] == [response]

    broken = [f for f in frames if not (f.can_id == 0x7EC and f.data[0] == 0x23)]
    incomplete = [m for m in reassemble(broken) if m.can_id == 0x7EC]
    assert incomplete and not incomplete[0].complete


def test_pairs_requests_with_positive_and_negative_responses():
    trace = load_trace(bms_session(count=1))
    by_did = {tx.did: tx for tx in trace.transactions if tx.service == 0x22}

    assert by_did[0x0101].positive and by_did[0x0101].response_id == 0x7EC
    assert by_did[0x010A].negative_code == 0x31
    assert by_did[0x0101].data == bms_0101()[3:]


def test_dtc_vin_and_ecu_summary():
    summary = diagnose(load_trace(bms_session(count=1)))

    assert summary["vin"] == "TESTVIN0000******"
    assert summary["dtcs"]["7E4"] == [{"code": "P0A7F00", "status": 9, "confirmed": True, "active": True}]
    bms = next(e for e in summary["ecus"] if e["request_id"] == "7E4")
    assert bms["label"] == "BMS(배터리 관리)"
    assert bms["dids"] == ["0101"]
    assert bms["negative"][0]["did"] == "010A"


def test_format_dtc_prefixes():
    assert uds.format_dtc(0x0A, 0x7F, 0x00) == "P0A7F00"
    assert uds.format_dtc(0xC1, 0x00, 0x87) == "U010087"


def test_search_recovers_known_formulas_and_activates_them():
    trace = load_trace(bms_session(count=3))
    truths = [GroundTruth("soc", 95.5, 1), GroundTruth("pack_voltage", 785.5, 1),
              GroundTruth("pack_current", -12.3, 1), GroundTruth("cum_charge_ah", 1756.5, 1)]

    decisions = judge(truths, search(trace.samples, truths), trace.samples)

    assert decisions["soc"].activate
    assert decisions["soc"].candidate.layout == Layout(0x7E4, 0x0101, 4, 1, scale=0.5)
    assert decisions["pack_voltage"].candidate.layout.start == 12
    assert decisions["pack_current"].candidate.layout == Layout(0x7E4, 0x0101, 10, 2, signed=True, scale=0.1)
    assert decisions["cum_charge_ah"].candidate.layout.width == 4
    assert all(d.activate for d in decisions.values())


def test_zero_or_missing_truth_is_unknown():
    trace = load_trace(bms_session(count=1))
    truths = [GroundTruth("soc", 0, 0), GroundTruth("isolation_kohm", 4321, 0)]

    decisions = judge(truths, search(trace.samples, truths), trace.samples)

    assert not decisions["soc"].activate and "UNKNOWN" in decisions["soc"].reasons[0]
    assert not decisions["isolation_kohm"].activate


def test_ambiguous_value_without_reference_stays_hypothesis():
    # 24가 b14·b15 두 곳에 있고, inlet_temp의 참고자료 위치(b22)에는 없다.
    trace = load_trace(bms_session(count=1, max_temp=24, min_temp=24))
    truths = [GroundTruth("inlet_temp", 24, 0)]

    decision = judge(truths, search(trace.samples, truths), trace.samples)["inlet_temp"]

    assert not decision.activate
    assert "다른 해석" in decision.reasons[0]


def test_unique_match_without_reference_is_activated():
    trace = load_trace(bms_session(count=1))
    truths = [GroundTruth("inlet_temp", 41, 0)]

    decision = judge(truths, search(trace.samples, truths), trace.samples)["inlet_temp"]

    assert decision.activate and decision.candidate.layout.start == 26


def test_cross_check_blocks_min_greater_than_max():
    trace = load_trace(bms_session(count=1, max_temp=20, min_temp=30))
    truths = [GroundTruth("max_temp", 20, 0), GroundTruth("min_temp", 30, 0)]

    decisions = judge(truths, search(trace.samples, truths), trace.samples)

    assert not decisions["max_temp"].activate
    assert "최솟값" in decisions["max_temp"].reasons[-1]


def test_decode_signals_uses_rules_and_drops_out_of_range_values():
    trace = load_trace(bms_session(count=2))
    rules = [
        RuleRef(1, 3, "soc", Layout(0x7E4, 0x0101, 4, 1, scale=0.5), 0.98),
        RuleRef(2, 1, "max_cell_v", Layout(0x7E4, 0x0101, 12, 2, scale=1), 0.5),
    ]

    values = decode_signals(trace.samples, rules)

    assert values["soc"]["value"] == 95.0
    assert [v for _, v in values["soc"]["series"]] == [94.5, 95.0]
    assert values["soc"]["rule_version"] == 3
    assert "max_cell_v" not in values
