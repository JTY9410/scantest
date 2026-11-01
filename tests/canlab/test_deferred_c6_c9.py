"""C6 F4 fallback · C7 ECU 교차 · C8–C9 방송 분석 · 플래그 기본 OFF."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.canlab.engine import broadcast
from app.modules.canlab.engine.decode import diagnose, load_trace
from app.modules.canlab.engine.features import flag
from app.modules.scanner import analysis, interpret
from app.modules.scanner.plan import F4_FALLBACK_PIDS, build_plan

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "trc"
AVANTE = {"diag_car_id": "", "diag_company": "현대", "diag_model": "아반떼", "diag_year": "2019",
          "diag_fuel": "휘발유", "diag_displacement": "1598"}


@pytest.fixture
def clear_new_flags(monkeypatch):
    for name in ("SCAN_F4_FALLBACK", "SCAN_ECU_CROSS_CHECK", "CANLAB_BROADCAST_ANALYSIS"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(name, "0")


def test_new_flags_default_off(clear_new_flags):
    assert flag("SCAN_F4_FALLBACK") is False
    assert flag("SCAN_ECU_CROSS_CHECK") is False
    assert flag("CANLAB_BROADCAST_ANALYSIS") is False


def test_plan_omits_f4_when_flag_off(app, clear_new_flags):
    with app.app_context():
        app.config["SCAN_F4_FALLBACK"] = False
        commands = {s["command"] for s in build_plan(AVANTE)["steps"]}
    assert not any(c.startswith("22F4") for c in commands)


def test_plan_adds_f4_when_flag_on(app, monkeypatch, clear_new_flags):
    monkeypatch.setenv("SCAN_F4_FALLBACK", "1")
    with app.app_context():
        app.config["SCAN_F4_FALLBACK"] = True
        steps = [s for s in build_plan(AVANTE)["steps"] if s["command"].startswith("22F4")]
    assert {s["command"] for s in steps} == {f"22F4{pid:02X}" for pid in F4_FALLBACK_PIDS}
    assert all(s.get("when", {}).get("f4_fallback") for s in steps)
    assert all(s.get("header") == "7E0" for s in steps)


def test_interpret_f4_uses_mode01_formula(clear_new_flags):
    steps = [{
        "command": "22F40C", "reply": "7E8 05 62 F4 0C 1F 40\r\r>", "bus": "can",
        "label": "UDS 대체 엔진 회전수", "header": "7E0", "t_ms": 1, "group": "uds",
    }]
    result, _ = interpret.interpret(steps, [], "", AVANTE)
    keys = {v["key"]: v for v in result["values"]}
    assert "rpm" in keys
    assert keys["rpm"]["value"] == 2000.0
    assert keys["rpm"].get("source", "").startswith("UDS 22 F4")


def test_f4_does_not_override_mode01(clear_new_flags):
    steps = [
        {"command": "010C", "reply": "7E8 04 41 0C 0F A0\r\r>", "bus": "can",
         "label": "RPM", "t_ms": 1, "group": "pid"},
        {"command": "22F40C", "reply": "7E8 05 62 F4 0C 1F 40\r\r>", "bus": "can",
         "label": "UDS 대체", "header": "7E0", "t_ms": 2, "group": "uds"},
    ]
    result, _ = interpret.interpret(steps, [], "", AVANTE)
    rpm = next(v for v in result["values"] if v["key"] == "rpm")
    assert rpm["value"] == 1000.0


def test_cross_check_off_no_extra_warning(clear_new_flags):
    result = {
        "values": [{"key": "soc", "value": 50.0, "label": "SOC"}],
        "ecu_values": [{"ecu": "7E4", "label": "BMS", "values": [{"key": "soc", "value": 80.0}]}],
    }
    summary = analysis.summarize(result)
    assert not any("어긋납니다" in w for w in summary["warnings"])


def test_cross_check_on_detects_mismatch(monkeypatch, clear_new_flags):
    monkeypatch.setenv("SCAN_ECU_CROSS_CHECK", "1")
    result = {
        "values": [{"key": "soc", "value": 50.0, "label": "SOC"}],
        "ecu_values": [{"ecu": "7E4", "label": "BMS", "values": [{"key": "soc", "value": 80.0}]}],
    }
    summary = analysis.summarize(result)
    assert any("SOC" in w and "어긋납니다" in w for w in summary["warnings"])


def test_cross_check_soc_vs_display(monkeypatch, clear_new_flags):
    monkeypatch.setenv("SCAN_ECU_CROSS_CHECK", "1")
    result = {
        "values": [
            {"key": "soc", "value": 40.0, "label": "SOC"},
            {"key": "soc_display", "value": 70.0, "label": "표시 SOC"},
        ],
        "ecu_values": [],
    }
    summary = analysis.summarize(result)
    assert any("디스플레이 SOC" in w for w in summary["warnings"])


def test_broadcast_flag_off_diagnose_unchanged(clear_new_flags):
    text = (FIXTURES / "synthetic_broadcast.trc").read_text()
    off = diagnose(load_trace(text))
    assert "broadcast" not in off


def test_broadcast_flag_on_adds_analysis(monkeypatch, clear_new_flags):
    monkeypatch.setenv("CANLAB_BROADCAST_ANALYSIS", "1")
    text = (FIXTURES / "synthetic_broadcast.trc").read_text()
    on = diagnose(load_trace(text))
    assert "broadcast" in on
    bc = on["broadcast"]
    assert "100" in bc["periodic_ids"]
    assert "100" in bc["broadcast_candidate_ids"]
    row = next(r for r in bc["ids"] if r["id"] == "100")
    assert row["period_ms"] == 10.0
    assert 0 in row["counter_bytes"]
    assert 1 in row["changing_bytes"]


def test_broadcast_vehicle_fixtures_note_limitation(clear_new_flags):
    for name in ("vehicle_a_diag.trc", "vehicle_b_diag.trc"):
        report = broadcast.analyze_trace_text((FIXTURES / name).read_text())
        assert report["frame_count"] > 0
        if not report["broadcast_candidate_ids"]:
            assert report["limitations"]


def test_fixtures_have_no_raw_vin_or_cert_material():
    banned = ("KMHN2411BTA131575", "KNAC381AFPA607257")
    for path in FIXTURES.iterdir():
        text = path.read_text(errors="replace")
        for item in banned:
            assert item not in text, path.name
