"""스캔 결과 분석 요약: 배출 점검(레디니스)·고장코드·부품 점검·진단 실행 비율·전기차 배터리 값·값 타당성.

- 주행 중 진단 실행 비율(IUMPR): CARB OBD-II 일반 기준 0.336 미만을 표시한다.
- 전기차 배터리 판정은 위스캔 기본 보고서 기준(report.judgments)으로 하고, 여기서는 값과 OBDb 정상 범위를 보여 준다.
  정상 범위를 벗어난 값은 '이상값'으로 따로 두고 요약 계산(편차·타당성 검사)에서 뺀다.
- SOH가 직접 읽히지 않으면 누적 데이터와 운영 시간으로 역산한다(soh_estimation.py).
"""

from app.modules.scanner import soh_estimation

IUMPR_MINIMUM = 0.336
PACK_SUM_TOLERANCE = 0.03
MODULE_VOLTAGE_TOLERANCE = 1.5


def _item(result: dict, key: str) -> dict | None:
    item = (result.get("battery") or {}).get(key)
    return None if not item or item.get("outlier") else item


def _value(result: dict, key: str) -> float | None:
    item = _item(result, key)
    return item["value"] if item else None


def _range(limits: list | None, unit: str) -> str | None:
    return f"{limits[0]:g} ~ {limits[1]:g} {unit}".strip() if limits else None


def _ev(result: dict) -> list[dict]:
    items = []
    cells = result.get("cells") or {}
    
    # SOH: 직접 읽기 → 없으면 역산 시도
    if soh := _item(result, "soh"):
        items.append({"label": "배터리 건강 상태(SOH)", "value": f"{soh['value']:g} %",
                      "range": _range(soh.get("range"), "%"), "method": "direct"})
    else:
        # SOH 역산 시도
        signals = {}
        for key in ["cum_charge_ah", "cum_discharge_ah", "cum_charge_kwh", "cum_discharge_kwh", 
                    "operating_time_s", "pack_voltage", "pack_current"]:
            if val := _value(result, key):
                signals[key] = val
        
        if signals:
            car_info = result.get("car") or {}
            estimated_soh = soh_estimation.estimate_soh(signals, car_info)
            
            if estimated_soh and estimated_soh.soh is not None:
                method_label = {
                    "coulomb_counting": "누적 충방전량 기반 추정",
                    "energy_throughput": "누적 에너지량 기반 추정",
                    "time_based_fallback": "운영 시간 기반 추정",
                    "fusion": "복합 추정"
                }.get(estimated_soh.method, estimated_soh.method)
                
                value_text = f"{estimated_soh.soh:g} % (추정)"
                if estimated_soh.confidence < 0.7:
                    value_text += f" [신뢰도 {int(estimated_soh.confidence * 100)}%]"
                
                items.append({
                    "label": "배터리 건강 상태(SOH)", 
                    "value": value_text,
                    "range": "60 ~ 100 %",
                    "method": "estimated",
                    "estimation_method": method_label,
                    "assumptions": estimated_soh.assumptions
                })
    
    high, low = _item(result, "max_cell_v"), _item(result, "min_cell_v")
    if cells:
        items.append({"label": "셀 전압", "value": f"최저 {cells['min']:g} V · 최고 {cells['max']:g} V · 편차 "
                      f"{cells['spread_mv']} mV (셀 {cells['count']}개)", "range": _range(cells.get("range"), "V")})
    elif high and low:
        items.append({"label": "셀 전압", "value": f"최저 {low['value']:g} V · 최고 {high['value']:g} V · 편차 "
                      f"{round((high['value'] - low['value']) * 1000)} mV", "range": _range(high.get("range"), "V")})
    t_high, t_low = _item(result, "max_temp"), _item(result, "min_temp")
    if t_high and t_low:
        items.append({"label": "배터리 온도", "value": f"최저 {t_low['value']:g} °C · 최고 {t_high['value']:g} °C · "
                      f"편차 {t_high['value'] - t_low['value']:g} °C", "range": _range(t_high.get("range"), "°C")})
    if isolation := _item(result, "isolation_kohm"):
        text = f"{isolation['value']:,g} kΩ"
        if pack := _value(result, "pack_voltage"):
            text += f" ({isolation['value'] * 1000 / pack:,.0f} Ω/V)"
        items.append({"label": "절연 저항", "value": text, "range": _range(isolation.get("range"), "kΩ")})
    charged, discharged = _value(result, "cum_charge_kwh"), _value(result, "cum_discharge_kwh")
    if charged is not None or discharged is not None:
        text = " · ".join(f"{label} {v:,.0f} kWh" for label, v in (("충전", charged), ("방전", discharged))
                          if v is not None)
        items.append({"label": "누적 에너지", "value": text, "range": None})
    return items


def _outliers(result: dict) -> list[str]:
    found = [f"{item['label']} {item['value']:g} (정상 범위 {_range(item['range'], item.get('unit') or '')})"
             for item in (result.get("battery") or {}).values() if item.get("outlier")]
    cells = result.get("cells") or {}
    found += [f"셀 {c['no']}번 {c['voltage']:g} V (정상 범위 {_range(cells['range'], 'V')})"
              for c in cells.get("outliers") or []]
    return found


def _checks(result: dict) -> list[str]:
    """서로 맞지 않는 값. 해석 배치가 차종과 다르거나 센서 이상일 수 있다."""
    warnings = []
    cells = result.get("cells") or {}
    pack = _value(result, "pack_voltage")
    if cells and pack and cells["count"] >= 80 and abs(cells["sum"] - pack) / pack > PACK_SUM_TOLERANCE:
        warnings.append(f"셀 전압 합({cells['sum']:g} V)과 팩 전압({pack:g} V)이 3% 넘게 다릅니다. "
                        "읽지 못한 셀이 있거나 해석 배치가 차종과 다를 수 있습니다.")
    high, low = _value(result, "max_cell_v"), _value(result, "min_cell_v")
    if None not in (high, low) and high < low:
        warnings.append("최대 셀 전압이 최소 셀 전압보다 낮습니다. 해석 배치를 확인하세요.")
    if cells and high is not None and abs(cells["max"] - high) > 0.05:
        warnings.append(f"셀별 최대값({cells['max']:g} V)과 BMS 최대 셀 전압({high:g} V)이 다릅니다.")
    t_high, t_low = _value(result, "max_temp"), _value(result, "min_temp")
    if None not in (t_high, t_low) and t_high < t_low:
        warnings.append("배터리 최대 온도가 최소 온도보다 낮습니다. 해석 배치를 확인하세요.")
    module = next((v["value"] for v in result.get("values") or [] if v["key"] == "module_voltage"), None)
    if module is not None and result.get("voltage") is not None \
            and abs(module - result["voltage"]) > MODULE_VOLTAGE_TOLERANCE:
        warnings.append(f"제어 모듈 전압({module:g} V)과 단말기 측정 전압({result['voltage']:g} V)이 "
                        f"{MODULE_VOLTAGE_TOLERANCE:g} V 넘게 다릅니다. 접지·배선을 확인하세요.")
    return warnings


_QUIET = {"ok", "unsupported", "skipped", "pending"}


def group_steps(steps: list[dict] | None) -> list[dict]:
    """같은 주소의 단계를 묶고, 실패가 많은 제어기를 앞에 둔다."""
    groups: dict[str, list[dict]] = {}
    for step in steps or []:
        groups.setdefault(str(step.get("header") or "기본"), []).append(step)

    def fails(rows: list[dict]) -> int:
        return sum(1 for step in rows if step.get("status") not in _QUIET)

    ordered = sorted(groups.items(), key=lambda item: (-fails(item[1]), item[0]))
    return [{"header": header, "steps": rows, "fails": fails(rows)} for header, rows in ordered]


def summarize(result: dict) -> dict:
    monitor = result.get("monitor") or {}
    tests = monitor.get("tests") or []
    dtcs = result.get("dtcs") or []
    kinds: dict[str, int] = {}
    for dtc in dtcs:
        kinds[dtc["kind"]] = kinds.get(dtc["kind"], 0) + 1
    iumpr = result.get("iumpr") or {}
    return {
        "readiness": {"ignition": monitor.get("ignition"), "total": len(tests),
                      "complete": sum(t["complete"] for t in tests),
                      "incomplete": [t["name"] for t in tests if not t["complete"]]} if tests else None,
        "mil": monitor.get("mil") if monitor else None,
        "dtc_total": len(dtcs),
        "dtc_kinds": kinds,
        "monitor_failures": [t for t in result.get("monitor_tests") or [] if not t["passed"]],
        "monitor_total": len(result.get("monitor_tests") or []),
        "iumpr_low": [m for m in iumpr.get("monitors") or []
                      if m["conditions"] and m["ratio"] is not None and m["ratio"] < IUMPR_MINIMUM],
        "ev": _ev(result),
        "outliers": _outliers(result),
        "warnings": _checks(result),
    }
