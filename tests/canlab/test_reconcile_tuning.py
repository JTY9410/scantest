"""완료 데이터 대조 허용오차·필수 명령(설정 가능)과 BMS 밖 제어기 PID(LDC·충전 인렛) 해석. 값은 모두 가짜 바이트."""
from app.modules.canlab.engine import bms
from app.modules.canlab.engine.reconcile import (
    DEFAULT_REQUIRED,
    DEFAULT_TOLERANCES,
    _compare,
    bms_definitions,
    coverage,
    tolerance,
    tolerance_table,
)


def test_cell_position_numbers_are_info_only():
    assert _compare("max_cell_no", 4, [1.0, 2.0, 3.0]) == ("일치", "위치 번호는 동률 셀 사이에서 바뀌어 비교하지 않음")


def test_counter_never_decreases_and_increase_is_capped_by_lag():
    assert _compare("cum_discharge_ah", 100.0, [100.1])[0] == "일치"          # 분해능 0.1 안
    assert _compare("cum_discharge_ah", 99.8, [100.1])[0] == "불일치"         # 감소
    assert _compare("cum_discharge_ah", 100.3, [100.1], lag_s=200)[0] == "일치"
    status, note = _compare("cum_discharge_ah", 200.0, [100.0], lag_s=200)   # 200초에 100Ah 증가는 상한(30.1) 초과
    assert status == "불일치" and "상한" in note
    assert _compare("cum_discharge_ah", 200.0, [100.0])[0] == "일치"          # 시차를 모르면 증가만 본다


def test_data_based_tolerances_and_override():
    assert tolerance("soh", 97.0) == 0.1
    assert tolerance("pack_voltage", 700.0) == 3.5
    assert tolerance("module_temp_3", 20) == 1
    assert _compare("ldc_voltage", 14.74, [14.70, 14.72])[0] == "일치"
    assert _compare("ldc_voltage", 14.90, [14.70, 14.72])[0] == "불일치"
    table = tolerance_table({"soh": {"abs": 0.5}, "new_key": {"mode": "point", "abs": 2}})
    assert tolerance("soh", 97.0, table) == 0.5 and DEFAULT_TOLERANCES["soh"]["abs"] == 0.1
    assert _compare("soh", 97.0, [97.4], table)[0] == "일치"
    assert _compare("new_key", 10, [11.5], table)[0] == "일치"


def test_required_commands_per_type_and_override():
    ours = [("7E4", "220101"), ("7E4", "220102"), ("7E4", "220103"), ("7E4", "220104"), ("7E4", "220105"),
            ("7E4", "19020F")]
    assert coverage("ev", ours, ours)["required_ratio"] == 1.0
    assert coverage("ice", ours, ours)["required_ratio"] == 0.0
    assert coverage("ice", ours, ours, {"ice": (("7E4", "1902"),)})["required_ratio"] == 1.0
    assert ("7E0", "1902") in DEFAULT_REQUIRED["hev"] and ("7E1", "1902") in DEFAULT_REQUIRED["ice"]


def _e011(ldc_out_mv: int, ldc_in_dv: int) -> bytes:
    data = bytearray(46)
    data[0:3] = b"\x62\xe0\x11"
    data[10:12] = ldc_out_mv.to_bytes(2, "big")
    data[14:16] = ldc_in_dv.to_bytes(2, "big")
    return bytes(data)


def _e004(dc1: int, dc2: int, ac: int) -> bytes:
    data = bytearray(22)
    data[0:3] = b"\x62\xe0\x04"
    data[8], data[9], data[10] = dc1 + 50, dc2 + 50, ac + 50
    return bytes(data)


def test_ecu_fields_decode_ldc_and_inlets_for_egmp_only():
    samples = {(0x7E5, 0xE011): [(0.0, _e011(14800, 6950))], (0x744, 0xE004): [(0.0, _e004(21, 22, 25))]}
    by_key = {f.key: f for f in bms.ecu_fields("egmp")}
    assert by_key["ldc_voltage"].value(samples[(0x7E5, 0xE011)][0][1]) == 14.8
    assert by_key["ldc_input_voltage"].value(samples[(0x7E5, 0xE011)][0][1]) == 695.0
    assert [by_key[k].value(samples[(0x744, 0xE004)][0][1]) for k in
            ("dc_inlet_temp_1", "dc_inlet_temp_2", "ac_inlet_temp_1")] == [21, 22, 25]
    assert {f.grade for f in by_key.values()} == {"유력"}
    assert bms.ecu_fields("hev") == [] and bms.ecu_fields("unknown") == []
    assert {f.key for f in bms.ecu_fields("niro")} == {"dc_inlet_temp_1", "dc_inlet_temp_2", "ac_inlet_temp_1"}
    defs = {d.key: d for d in bms_definitions("egmp")}
    assert defs["ldc_voltage"].request_id == 0x7E5 and defs["dc_inlet_temp_1"].request_id == 0x744
    assert "motor_temp_front" not in defs and "motor_offset_u_front" not in defs  # 근거 부족 → 넣지 않음


def test_report_ev_items_measured_with_ldc_and_inlets():
    from app.modules.scanner import report

    battery = {k: {"value": v, "grade": "유력"} for k, v in {
        "soh": 97.0, "isolation_kohm": 3000, "max_cell_v": 3.84, "min_cell_v": 3.82, "max_temp": 15, "min_temp": 13,
        "ldc_voltage": 14.8, "aux_voltage": 14.3, "dc_inlet_temp_1": 21, "dc_inlet_temp_2": 22,
        "ac_inlet_temp_1": 25}.items()}
    rows = report.type_judgments({"battery": battery}, "ev")
    assert all(r["result"] != report.UNREAD for r in rows) and report.overall(rows, 0) == "양호"


def test_reconcile_settings_come_from_config(app, monkeypatch):
    from app.config import _json

    monkeypatch.setenv("RECONCILE_TOLERANCES", '{"soh": {"abs": 0.3}}')
    assert _json("RECONCILE_TOLERANCES") == {"soh": {"abs": 0.3}}
    monkeypatch.delenv("RECONCILE_TOLERANCES")
    assert _json("RECONCILE_TOLERANCES") == {}
    assert app.config["RECONCILE_TOLERANCES"] == {} and app.config["RECONCILE_REQUIRED"] == {}
