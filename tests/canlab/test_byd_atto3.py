"""BYD Atto 3 로그(2026-11-06)에서 확인한 방송·BMS 배치."""

from types import SimpleNamespace

from app.modules.canlab.engine.byd_atto3 import decode
from app.modules.canlab.engine.decode import diagnose, load_trace
from app.modules.canlab.engine.frames import Frame
from app.modules.scanner.plan import build_plan

VIN = "LGXCE4CB8S2129200"


def _cell(start: int, mv: tuple[int, int, int]) -> Frame:
    data = bytes([0x12, start]) + b"".join(v.to_bytes(2, "little") for v in mv)
    return Frame(0.0, 0x644, data)


def test_atto3_log_layout_reads_odometer_and_cells():
    frames = [
        _cell(1, (3318, 3318, 3319)),
        _cell(124, (3318, 3317, 3319)),
        Frame(0.0, 0x644, bytes.fromhex("e963011904121d1e")),
    ]
    found = decode(frames)

    assert found["odometer_km"] == 7709
    assert found["cells"]["count"] == 6
    assert found["cells"]["values"][0] == {"no": 1, "mv": 3318}
    assert found["cells"]["values"][-1] == {"no": 126, "mv": 3319}
    assert found["cells"]["min_mv"] == 3317 and found["cells"]["max_mv"] == 3319


def test_bms_did_1586_is_vin_and_masked():
    tx = SimpleNamespace(positive=True, service=0x22, did=0x1586, data=VIN.encode())
    found = decode([], [tx])

    assert found["vin"] == "LGXCE4CB8S2******"
    assert found["odometer_km"] is None and found["cells"] is None


def test_unrelated_broadcast_is_not_atto3():
    assert decode([Frame(0.0, 0x123, b"\x12\x01" + b"\x00" * 6)]) is None


def test_csv_diagnosis_keeps_atto3_summary():
    rows = [
        "Timestamp,Channel,CAN_ID,DLC,Data,IDType,Status1",
        "1.000,1,00000644,8,12 01 F6 0C F6 0C F7 0C,Standard,0x00000000",
        "1.010,1,00000644,8,12 7C F6 0C F5 0C F7 0C,Standard,0x00000000",
        "1.020,1,00000644,8,E9 63 01 19 04 12 1D 1E,Standard,0x00000000",
    ]
    summary = diagnose(load_trace("\n".join(rows)))

    assert summary["atto3"]["odometer_km"] == 7709
    assert summary["atto3"]["cells"]["count"] == 6
    assert [cell["no"] for cell in summary["atto3"]["cells"]["values"]] == [1, 2, 3, 124, 125, 126]


def test_byd_plan_reads_bms_vin_and_stays_read_only(app):
    with app.app_context():
        steps = build_plan({"diag_company": "BYD", "diag_model": "Atto 3", "diag_fuel": "전기"})
    plain = {(s["header"], s["command"]) for s in steps["steps"]}

    assert ("7E7", "221586") in plain
    assert any("644" in note or "1586" in note for note in steps["notes"])
    assert not any(cmd[:2] in {"04", "14", "10", "27", "2E", "31"} for _, cmd in plain if not cmd.startswith("AT"))
