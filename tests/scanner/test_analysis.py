from app.modules.scanner import analysis


def _battery(**values):
    return {key: {"value": value} for key, value in values.items()}


def test_summary_readiness_dtcs_monitor_and_iumpr():
    result = {
        "monitor": {"mil": True, "ignition": "불꽃 점화(가솔린)",
                    "tests": [{"name": "실화", "complete": True}, {"name": "촉매", "complete": False}]},
        "dtcs": [{"kind": "현재"}, {"kind": "영구"}, {"kind": "현재"}],
        "monitor_tests": [{"name": "촉매 뱅크1", "passed": True}, {"name": "EGR", "passed": False}],
        "iumpr": {"monitors": [{"name": "촉매 뱅크1", "completed": 1, "conditions": 10, "ratio": 0.1},
                               {"name": "EGR·VVT", "completed": 5, "conditions": 10, "ratio": 0.5},
                               {"name": "증발가스", "completed": 0, "conditions": 0, "ratio": None}]},
    }
    summary = analysis.summarize(result)
    assert summary["readiness"] == {"ignition": "불꽃 점화(가솔린)", "total": 2, "complete": 1, "incomplete": ["촉매"]}
    assert summary["dtc_total"] == 3 and summary["dtc_kinds"] == {"현재": 2, "영구": 1}
    assert [t["name"] for t in summary["monitor_failures"]] == ["EGR"] and summary["monitor_total"] == 2
    assert [m["name"] for m in summary["iumpr_low"]] == ["촉매 뱅크1"]
    assert summary["ev"] == [] and summary["warnings"] == []


def test_ev_values_ranges_outliers_and_plausibility():
    result = {
        "battery": _battery(soh=85.0, max_cell_v=4.10, min_cell_v=3.95, max_temp=30, min_temp=18,
                            isolation_kohm=1000, pack_voltage=400.0, cum_charge_kwh=12000, cum_discharge_kwh=11500),
        "cells": {"count": 96, "min": 3.95, "max": 4.02, "spread_mv": 70, "sum": 385.0, "range": [2.8, 4.2],
                  "outliers": [{"no": 7, "voltage": 2.1}]},
        "voltage": 12.4,
        "values": [{"key": "module_voltage", "value": 14.5}],
    }
    result["battery"]["soh"]["range"] = [0, 100]
    summary = analysis.summarize(result)
    ev = {item["label"]: item for item in summary["ev"]}
    assert list(ev) == ["배터리 건강 상태(SOH)", "셀 전압", "배터리 온도", "절연 저항", "누적 에너지"]
    assert all("grade" not in item for item in summary["ev"])
    assert ev["배터리 건강 상태(SOH)"]["range"] == "0 ~ 100 %" and ev["셀 전압"]["range"] == "2.8 ~ 4.2 V"
    assert "편차 70 mV" in ev["셀 전압"]["value"] and "2,500 Ω/V" in ev["절연 저항"]["value"]
    assert summary["outliers"] == ["셀 7번 2.1 V (정상 범위 2.8 ~ 4.2 V)"]
    warnings = " ".join(summary["warnings"])
    assert "셀 전압 합" in warnings and "BMS 최대 셀 전압" in warnings and "제어 모듈 전압" in warnings


def test_outlier_battery_values_are_listed_and_left_out_of_summary():
    result = {"battery": _battery(max_temp=30, min_temp=40, isolation_kohm=70000)}
    result["battery"]["isolation_kohm"].update(label="절연 저항", unit="kΩ", range=[0, 65535], outlier=True)
    summary = analysis.summarize(result)
    assert summary["outliers"] == ["절연 저항 70000 (정상 범위 0 ~ 65535 kΩ)"]
    assert "절연 저항" not in {item["label"] for item in summary["ev"]}
    assert any("최대 온도가 최소 온도보다 낮습니다" in w for w in summary["warnings"])
