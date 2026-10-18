"""2026-10-18 대표 결정: 제어기 순회 기본 포함, 22 1050·22 B00x = 실주행거리, 웹 고장코드 지우기(별도 흐름).

DB 없이 돈다(계획의 학습·스캔 로직 조회는 바꿔 끼움): pytest --noconftest tests/scanner/test_sweep_odometer_clear.py
"""

import pytest

from app.modules.scanner import clear, interpret, obd, plan

EV6 = {"diag_company": "기아", "diag_model": "EV6", "diag_fuel": "전기"}
AVANTE = {"diag_company": "현대", "diag_model": "아반떼", "diag_fuel": "휘발유"}
BMW = {"diag_company": "BMW", "diag_model": "320d", "diag_fuel": "경유"}


@pytest.fixture(autouse=True)
def no_db(monkeypatch):
    import app.modules.scanner.learn as learn

    monkeypatch.setattr(plan, "capture_requests", lambda car=None: [])
    monkeypatch.setattr(plan, "logic_commands", lambda car=None: [])
    monkeypatch.setattr(learn, "learned_requests", lambda car: [])


def _steps(car, **kw):
    return plan.build_plan(car, expand=True, **kw)["steps"]


# ---- 제어기 순회 ---------------------------------------------------------------

def test_sweep_is_default_and_covers_all_dev_pairs():
    ev = _steps(EV6)
    headers = {s["header"] for s in ev if s["header"]}
    assert set(plan.SWEEP_COMMON) | set(plan.SWEEP_EV) <= headers
    assert len(plan.SWEEP_COMMON) == 35 and len(plan.SWEEP_EV) == 32
    sweep = [s for s in ev if s.get("sweep")]
    assert all(s["optional"] and s["bus"] == "can" and s["timeout"] == plan.SWEEP_TIMEOUT_MS and s["st"] == "19"
               for s in sweep)
    probes = [s for s in sweep if s["probe"]]
    assert all(s["command"] == "1902FF" for s in probes)
    assert len({s["header"] for s in probes}) == len(probes), "주소마다 한 번"


def test_sweep_skips_addresses_already_planned_and_ev_list_only_when_electrified():
    ice = _steps(AVANTE)
    probes = [s["header"] for s in ice if s.get("sweep") and s["probe"]]
    assert "7E0" not in probes and "7C6" not in probes and "7D1" not in probes  # 기존 UDS 단계가 이미 읽음
    assert "5E0" not in probes and "7A0" in probes
    assert len(probes) == 28
    assert len([s for s in _steps(BMW) if s.get("sweep") and s["probe"]]) == 31
    assert len([s for s in _steps(None) if s.get("sweep") and s["probe"]]) == 59, "연료 미상은 전동차 목록까지"


def test_sweep_orders_learned_responders_first():
    order = plan.sweep_headers(AVANTE, set(), [{"header": "7D6", "hits": 3}, {"header": "7B2", "hits": 9}])
    assert order[:2] == ["7B2", "7D6"]


def test_sweep_steps_come_before_learned_and_rule_steps():
    groups = [s["group"] for s in _steps(EV6)]
    last_sweep = max(i for i, s in enumerate(_steps(EV6)) if s.get("sweep"))
    assert all(g not in ("learned", "rule") for g in groups[:last_sweep])


def test_29bit_cars_skip_sweep_because_no_header29():
    assert all("header29" not in s for s in _steps(EV6) if s.get("sweep"))


def test_wecar_console_presets_are_gone():
    commands = {s["command"] for s in _steps(EV6)}
    assert "1902FFFFFF" not in commands and not any(c.startswith("ATSH") for c in commands)


# ---- 실주행거리 -----------------------------------------------------------------

def test_odometer_steps_precede_cluster_probe():
    ev = _steps(EV6)
    index = {(s["header"], s["command"]): i for i, s in enumerate(ev)}
    for did in plan.CLUSTER_ODO_DIDS:
        assert index[("7C6", f"22{did}")] < index[("7C6", "22F190")]
    assert ("7E5", "221050") in index
    assert ("7E5", "221050") not in {(s["header"], s["command"]) for s in _steps(AVANTE)}
    assert not any(s["command"][2:] in obd.ODOMETER_DIDS for s in _steps(BMW) if s["command"].startswith("22"))


@pytest.mark.parametrize(("did", "data", "km"), [
    ("B002", "000000000000011EA1", 73377),      # [6..8] 3바이트 BE (앱 주석: EV6 상용 로그)
    ("1050", "011EA1", 73377),                  # 3바이트 BE
    ("1050", "00F230", 62000),
    ("B003", "0000011EA1", 73377),              # 끝 3바이트
    ("B004", "A11E0100", 7841),                 # 앱 dev 후보 순서(2바이트 LE 먼저) 그대로 — 열린 문제
    ("B002", "00", None),
])
def test_maker_odometer_matches_app_dev_parser(did, data, km):
    assert obd.maker_odometer(did, bytes.fromhex(data)) == km


def _step(command, reply, header=None, group="maker"):
    return {"command": command, "reply": reply, "header": header, "group": group, "label": command,
            "optional": True, "bus": "can"}


def test_interpret_uses_01a6_first_then_maker_dids():
    steps = [_step("ATDPN", "A6", group="device"),
             _step("22B002", "7CE 10 0C 62 B0 02 00 00 00\r7CE 21 00 00 00 01 1E A1 00", "7C6")]
    result, _ = interpret.interpret(steps, [], "", EV6)
    odo = next(v for v in result["values"] if v["key"] == "odometer")
    assert odo["value"] == 73377 and odo["source"] == "7C6 22 B002" and odo["reference"]

    with_std = [_step("ATDPN", "A6", group="device"), _step("01A6", "7E8 06 41 A6 00 0B 32 A2", group="pid"),
                *steps[1:]]
    result, _ = interpret.interpret(with_std, [], "", EV6)
    assert [v["value"] for v in result["values"] if v["key"] == "odometer"] == [73385.8]  # 0x000B32A2 / 10


def test_interpret_prefers_cluster_when_1050_looks_like_range():
    steps = [_step("ATDPN", "A6", group="device"),
             _step("221050", "7ED 06 62 10 50 00 01 5E", "7E5"),
             _step("22B002", "7CE 10 0C 62 B0 02 00 00 00\r7CE 21 00 00 00 01 1E A1 00", "7C6")]
    result, _ = interpret.interpret(steps, [], "", EV6)
    odo = next(v for v in result["values"] if v["key"] == "odometer")
    assert odo["value"] == 73377 and any("실차 확인" in n for n in result["notes"])


# ---- 고장코드 지우기 -------------------------------------------------------------

BEFORE = {"protocol": {"bus": "can11"},
          "dtcs": [{"code": "P0133", "ecu": "7E8", "source": "OBD 03"},
                   {"code": "C161600", "ecu": "7D9", "source": "UDS 19 02"}]}


def test_clear_plan_targets_and_order():
    built = clear.build_clear_plan(BEFORE)
    assert built["targets"] == ["7E0", "7D1", "7D2", "7D0", "7D6", "7B2", "770"]
    groups = [s["group"] for s in built["steps"]]
    assert groups.index("clear_check") < groups.index("clear") < groups.index("clear_verify")
    uds = [s for s in built["steps"] if s["command"] == "14FFFFFF"]
    assert len(uds) == 7 and all(s["pending_retries"] == 6 and s["session_fallback"] for s in uds)
    assert not any(s["command"] == "14FFFFFFFF" for s in built["steps"]), "main의 5바이트 오류 아님"
    obd04 = next(s for s in built["steps"] if s["command"] == "04")
    assert obd04["when"] == {"clear_fallback": True, "obd_dtcs": True}
    first_verify = next(s for s in built["steps"] if s["group"] == "clear_verify")
    assert first_verify["delay_ms"] == 2000
    assert not any(s["command"].startswith("10") for s in built["steps"]), "10 03은 드라이버가 NRC 7F일 때만"


def test_clear_targets_are_all_responders_plus_fixed_six():
    snapshot = {
        "protocol": {"bus": "can11"},
        "dtcs": [{"code": "B160000", "ecu": "7BA", "source": "UDS 19 02"}],
        "ecus": [{"address": "7E8"}, {"address": "7EC"}, {"address": "7A8"}, {"address": "10"}],
        "steps": [
            {"header": "7C4", "status": "unsupported", "message": "이 차량·ECU가 지원하지 않습니다(7CC NRC 31 범위 밖)"},
            {"header": "5E2", "status": "negative", "message": "5EA NRC 22 조건 불충족"},
            {"header": "741", "status": "pending", "message": "응답 대기"},
            {"header": "7A5", "status": "unsupported", "message": "이 차량·ECU가 지원하지 않습니다(응답 없음)"},
            {"header": "7A6", "status": "timeout", "message": "시간 초과"},
            {"header": None, "status": "ok", "message": "1개 ECU 응답"},
        ],
    }
    targets = clear.clear_targets(snapshot)
    assert targets == ["7B2", "7E0", "7E4", "7A0", "7C4", "5E2", "741", "7D2", "7D0", "7D6", "770"]
    assert "7A5" not in targets and "7A6" not in targets
    built = clear.build_clear_plan(snapshot)
    assert len([s for s in built["steps"] if s["command"] == "14FFFFFF"]) == len(targets)
    assert len([s for s in built["steps"] if s["group"] == "clear_verify" and s["command"] == "1902FF"]) == len(targets)
    assert clear.validate_results([{"command": "14FFFFFF", "header": "7A5"}], built["targets"])


def test_clear_plan_29bit_uses_only_reported_ecus():
    built = clear.build_clear_plan({"protocol": {"bus": "can29"},
                                    "dtcs": [{"code": "P0133", "ecu": "18DAF110", "source": "UDS 19 02"}]})
    assert built["targets"] == ["18DA10F1"]


def test_validate_results_rejects_foreign_commands_and_headers():
    assert clear.validate_results([{"command": "14FFFFFF", "header": "7E0"}], ["7E0"]) is None
    assert clear.validate_results([{"command": "1003", "header": "7E0"}], ["7E0"]) is None
    assert "허용하지 않는" in clear.validate_results([{"command": "2EF190", "header": "7E0"}], ["7E0"])
    assert "발급하지 않은" in clear.validate_results([{"command": "14FFFFFF", "header": "7A0"}], ["7E0"])


def _clear_steps(**replies):
    base = [
        {"group": "clear_check", "command": "010D", "reply": replies.get("speed", "7E8 03 41 0D 00")},
        {"group": "clear", "command": "14FFFFFF", "header": "7E0",
         "reply": replies.get("7E0", "7E8 03 7F 14 78\r7E8 01 54")},
        {"group": "clear", "command": "14FFFFFF", "header": "7D2",
         "reply": replies.get("7D2", "7DA 03 7F 14 7F\r7DA 02 50 03\r7DA 01 54\r7DA 02 50 01")},
        {"group": "clear", "command": "14FFFFFF", "header": "7B2", "reply": replies.get("7B2", "7BA 03 7F 14 22")},
        {"group": "clear", "command": "04", "header": None, "reply": replies.get("04", "7E8 01 44")},
        {"group": "clear_verify", "command": "03", "reply": replies.get("03", "7E8 02 43 00")},
        {"group": "clear_verify", "command": "1902FF", "header": "7D2",
         "reply": replies.get("v7D2", "7DA 03 59 02 FF")},
    ]
    return base


def test_evaluate_clear_partial_with_session_and_rejection():
    result = clear.evaluate_clear(_clear_steps(), "can11", ["P0133", "C161600"])
    by = {e["header"]: e for e in result["ecus"]}
    assert by["7E0"]["status"] == "cleared"                       # NRC 78 뒤 54
    assert by["7D2"]["status"] == "cleared" and by["7D2"]["session_used"]
    assert by["7B2"]["status"] == "rejected" and by["7B2"]["nrc"] == 0x22
    assert result["obd04"]["status"] == "cleared"
    assert result["status"] == "partial" and result["dtcs_after"] == []
    assert result["cleared"] == ["C161600", "P0133"] and result["session_used"] == ["7D2"]


def test_evaluate_clear_ok_and_remaining_codes():
    ok = clear.evaluate_clear(_clear_steps(**{"7B2": "7BA 01 54"}), "can11", ["P0133"])
    assert ok["status"] == "ok"
    remaining = clear.evaluate_clear(_clear_steps(**{"03": "7E8 04 43 01 01 33"}), "can11", ["P0133"])
    assert remaining["remaining"] == ["P0133"] and remaining["status"] == "partial"


def test_evaluate_clear_aborts_when_moving_and_fails_when_nothing_cleared():
    moving = clear.evaluate_clear(_clear_steps(speed="7E8 03 41 0D 14"), "can11", [])
    assert moving["status"] == "aborted" and moving["precheck"]["speed"] == 20
    none = clear.evaluate_clear(_clear_steps(**{"7E0": "NO DATA", "7D2": "NO DATA", "04": "NO DATA"}), "can11", [])
    assert none["status"] == "failed"
