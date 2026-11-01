"""신규적용 v3: 플래그 기본 OFF 동일성, C2a 억제 방향, C3/C4/C5/C11a–d."""

from __future__ import annotations

import os

import pytest

from app.modules.canlab.engine import e2e, search, validate
from app.modules.canlab.engine.features import flag
from app.modules.canlab.engine.search import GroundTruth, Layout
from app.modules.canlab.engine.uds import Transaction, format_dtc, parse_dtcs
from app.modules.scanner.dtc_ftb import fault_type_label
from app.modules.scanner import obd
from app.modules.scanner.security import EmptyProvider, StaticTestProvider, analyze_security_trace, unlock_allowed


@pytest.fixture
def clear_flags(monkeypatch):
    for name in (
        "SCAN_DTC_FTB_LABELS", "CANLAB_ENDIAN_EVIDENCE", "CANLAB_COUNTER_WARN",
        "CANLAB_DBC_EXPORT", "SCAN_SECURITY_STATUS", "SCAN_SECURITY_UNLOCK",
    ):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(name, "0")


def test_flag_defaults_off(clear_flags):
    assert flag("SCAN_DTC_FTB_LABELS") is False
    assert flag("CANLAB_COUNTER_WARN") is False
    assert unlock_allowed() is False


def test_ftb_label_table():
    assert fault_type_label(0x13) == "회로 오픈"
    assert format_dtc(0x0A, 0x7F, 0x13) == "P0A7F13"


def test_uds_dtcs_flag_off_no_fault_type(clear_flags):
    # 59 02 FF | P0A7F + FTB 13 + status 88
    payload = bytes.fromhex("59 02 FF 0A 7F 13 88")
    rows = obd.uds_dtcs(payload)
    assert rows[0]["code"] == "P0A7F13"
    assert "fault_type" not in rows[0]


def test_uds_dtcs_flag_on_adds_fault_type(monkeypatch):
    monkeypatch.setenv("SCAN_DTC_FTB_LABELS", "1")
    payload = bytes.fromhex("59 02 FF 0A 7F 13 88")
    rows = obd.uds_dtcs(payload)
    assert rows[0]["code"] == "P0A7F13"
    assert rows[0]["fault_type"] == "회로 오픈"
    assert rows[0]["fault_type_source"] == "표준 기준"


def test_expects_response_suppress():
    tx = Transaction(0.0, 0x7E0, 0x7E8, 0x3E, bytes([0x3E, 0x80]))
    assert tx.expects_response is False
    tx2 = Transaction(0.0, 0x7E0, 0x7E8, 0x3E, bytes([0x3E, 0x00]))
    assert tx2.expects_response is True
    tx3 = Transaction(0.0, 0x7E0, 0x7E8, 0x10, bytes([0x10, 0x81]))
    assert tx3.expects_response is False


def test_counter_detect():
    payloads = [bytes([(i % 256), 0x10, 0x20]) for i in range(20)]
    assert 0 in e2e.counter_bytes(payloads)
    assert 1 not in e2e.counter_bytes(payloads)


def test_c2a_does_not_increase_activations(monkeypatch, clear_flags):
    """카운터 경고는 확정을 늘리지 않는다(억제 방향만)."""
    rows = []
    for i in range(40):
        p = bytearray(8)
        p[0] = i % 256  # counter
        p[1] = 150  # soc raw *0.5 = 75
        rows.append((float(i), bytes(p)))
    samples = {(0x7E4, 0x0101): rows}
    truths = [GroundTruth("soc", 75.0, 1)]
    ranked = search.search(samples, truths, {})
    off = validate.judge(truths, ranked, samples)
    monkeypatch.setenv("CANLAB_COUNTER_WARN", "1")
    on = validate.judge(truths, ranked, samples)
    off_n = sum(1 for d in off.values() if d.activate)
    on_n = sum(1 for d in on.values() if d.activate)
    assert on_n <= off_n
    # soc uses b1, not counter — activations equal
    assert on["soc"].activate == off["soc"].activate


def test_c2a_blocks_when_candidate_on_counter(monkeypatch, clear_flags):
    rows = []
    for i in range(40):
        p = bytearray(4)
        p[0] = 50  # constant that *1.0 with offset 0 could match weakly; use as counter overlapping
        p[0] = i % 256
        rows.append((float(i), bytes(p)))
    # craft truth matching counter byte occasionally with scale — drifting pack uses support=1
    samples = {(0x7E4, 0x0101): rows}
    # Use aux_voltage-like: won't match. Instead force candidate on b0 by picking value that matches one sample.
    # Simpler: call _counter_warning path via decide with a candidate layout on b0.
    from app.modules.canlab.engine.search import Candidate
    layout = Layout(0x7E4, 0x0101, 0, 1, scale=1.0, offset=0.0)
    cand = Candidate("soc", layout, 0.0, 1, 40, float(rows[-1][1][0]), score=0.9)
    truth = GroundTruth("soc", float(rows[-1][1][0]), 0)
    monkeypatch.setenv("CANLAB_COUNTER_WARN", "1")
    decision = validate.decide(truth, [cand], samples)
    assert decision.activate is False
    assert any("카운터" in r for r in decision.reasons)


def test_empty_provider_blocks_material():
    p = EmptyProvider()
    assert p.has_material(1) is False
    with pytest.raises(LookupError):
        p.request_seed_key(1, b"\x00\x01")


def test_static_test_provider():
    p = StaticTestProvider(keys={1: b"\xAA\xBB"}, signatures={0x41: b"\x01\x02"})
    key, ref = p.request_seed_key(1, b"\x00")
    assert key == b"\xAA\xBB"
    assert ref.kind == "test"
    assert ref.size == 2


def test_security_trace_flag_off(clear_flags):
    txs = [Transaction(0.0, 0x5D0, 0x5D8, 0x27, bytes([0x27, 0x41]), response=bytes([0x7F, 0x27, 0x33]), negative_code=0x33)]
    out = analyze_security_trace(txs)
    assert out["enabled"] is False
    assert out["events"] == []


def test_security_trace_flag_on(monkeypatch, clear_flags):
    monkeypatch.setenv("SCAN_SECURITY_STATUS", "1")
    txs = [
        Transaction(0.0, 0x5D0, 0x5D8, 0x10, bytes([0x10, 0x03]), response=bytes([0x50, 0x03])),
        Transaction(1.0, 0x5D0, 0x5D8, 0x27, bytes([0x27, 0x41]) + b"\x00" * 10,
                    response=bytes([0x7F, 0x27, 0x33]), negative_code=0x33),
        Transaction(2.0, 0x5D0, 0x5D8, 0x27, bytes([0x27, 0x41]) + b"\x00" * 10,
                    response=bytes([0x67, 0x41])),
        Transaction(3.0, 0x5D0, 0x5D8, 0x27, bytes([0x27, 0x42]) + b"\x00" * 8,
                    response=bytes([0x67, 0x42])),
        Transaction(4.0, 0x5D0, 0x5D8, 0x3E, bytes([0x3E, 0x80])),
    ]
    out = analyze_security_trace(txs)
    assert out["enabled"] is True
    assert out["unlock_send_enabled"] is False
    assert any(e.get("nrc") == 0x33 for e in out["events"])
    assert "5D0" in out["unlocked_ecus"]
    assert out["tester_present"] >= 1
    # no raw payload in events
    assert all("request" not in e and "payload" not in e for e in out["events"])


def test_unlock_requires_both_flags(monkeypatch, clear_flags):
    monkeypatch.setenv("SCAN_SECURITY_STATUS", "1")
    assert unlock_allowed() is False
    monkeypatch.setenv("SCAN_SECURITY_UNLOCK", "1")
    assert unlock_allowed() is True
