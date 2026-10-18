"""스캔 해석 결과를 위스캔 기본 보고서 구조로 모은다.

수집(run_scan)과 열람(결과 화면)이 같은 키를 쓴다.
diagnosis_info, vehicle, report, dtc.enhanced.ecus, sensor.ev|ice.
없는 값은 키를 넣지 않는다. 통신이 안 된 제어기는 comm_status=fail, code_count=null.
"""

from datetime import datetime
from typing import Any

_ECU = {
    "7E0": "엔진", "7E8": "엔진", "7E1": "변속기", "7E9": "변속기",
    "7E2": "ABS", "7EA": "ABS", "7D1": "ABS",
    "7E3": "에어백", "7EB": "에어백",
    "7E4": "배터리", "7EC": "배터리",
    "7E5": "모터", "7ED": "모터",
    "7E6": "통합전력", "7EE": "통합전력",
    "7E7": "차량충전", "7EF": "차량충전",
    "7C6": "에어컨",
}
_FAIL = {"no_data", "timeout", "device_error", "disconnected"}
_BATTERY = {
    "soc": "bms_soc", "soc_display": "bms_display_soc", "soh": "bms_soh",
    "pack_voltage": "bms_pack_voltage", "pack_current": "bms_pack_current",
    "max_temp": "bms_battery_temp_max", "min_temp": "bms_battery_temp_min",
    "max_cell_v": "bms_cell_voltage_max", "min_cell_v": "bms_cell_voltage_min",
    "isolation_kohm": "bms_insulation_resistance",
    "cum_charge_ah": "bms_chg_aca", "cum_discharge_ah": "bms_dischg_aca",
}
_APP_TYPE = {"web": "web", "app": "app", "lte": "lte"}


def _num(value: Any) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _ecu_name(address: str | None) -> str | None:
    return _ECU.get((address or "").upper())


def _present(data: dict) -> dict:
    return {key: value for key, value in data.items() if value is not None and value != ""}


def _ecus(result: dict) -> list[dict]:
    rows: dict[str, dict] = {}

    def row(name: str) -> dict:
        return rows.setdefault(name, {"ecu_name": name, "ok": False, "fail": False, "codes": []})

    for step in result.get("steps") or []:
        name = _ecu_name(step.get("header"))
        if not name:
            continue
        item = row(name)
        if step.get("status") == "ok":
            item["ok"] = True
        elif step.get("status") in _FAIL:
            item["fail"] = True
    for dtc in result.get("dtcs") or []:
        name = _ecu_name(dtc.get("ecu"))
        if not name:
            continue
        item = row(name)
        item["ok"] = True
        code = _present({"code": dtc.get("code"), "status": dtc.get("kind"), "description": dtc.get("desc")})
        if code.get("code"):
            item["codes"].append(code)
    out = []
    for item in rows.values():
        if item["ok"]:
            out.append({"ecu_name": item["ecu_name"], "comm_status": "success",
                         "code_count": len(item["codes"]), "codes": item["codes"]})
        elif item["fail"]:
            out.append({"ecu_name": item["ecu_name"], "comm_status": "fail", "code_count": None})
    return out


def _sensor_ev(result: dict, mileage: float | int | None, car: dict) -> dict | None:
    sensor: dict[str, Any] = {}
    if mileage is not None:
        sensor["vehicle_mileage"] = mileage
    battery = result.get("battery") or {}
    for key, field in _BATTERY.items():
        item = battery.get(key) or {}
        if item.get("value") is not None:
            sensor[field] = item["value"]
    temps = [battery[f"module_temp_{n}"]["value"] for n in range(1, 6)
             if (battery.get(f"module_temp_{n}") or {}).get("value") is not None]
    if temps:
        sensor["bms_module_temperatures"] = temps
    cells = result.get("cells") or {}
    voltages = [c.get("voltage") for c in cells.get("values") or [] if c.get("voltage") is not None]
    if voltages:
        sensor["bms_cell_voltages"] = voltages
    if cells.get("max") is not None:
        sensor.setdefault("bms_cell_voltage_max", cells["max"])
    if cells.get("min") is not None:
        sensor.setdefault("bms_cell_voltage_min", cells["min"])
    capacity = _num(car.get("diag_capacity"))
    if capacity:
        sensor["initial_battery_capacity_kwh"] = capacity
    return sensor or None


def _battery_value(result: dict, key: str) -> float | int | None:
    item = (result.get("battery") or {}).get(key) or {}
    if item.get("outlier"):
        return None
    return _num(item.get("value"))


def _judgment(item: str, standard: str, value: float | int, unit: str, ok: bool) -> dict:
    return {"item": item, "standard": standard, "value": value, "unit": unit,
            "result": "양호" if ok else "주의"}


def judgments(result: dict) -> list[dict]:
    """위스캔 기본 보고서의 판정. 읽은 값이 있는 항목만 만든다."""
    rows = []
    if (soh := _battery_value(result, "soh")) is not None:
        rows.append(_judgment("배터리 수명 (SOH)", "SOH 80% 이상 시 양호", soh, "%", soh >= 80))
    if (iso := _battery_value(result, "isolation_kohm")) is not None:
        rows.append(_judgment("절연 저항", "절연저항 500 kΩ 이상 시 양호", iso, "kΩ", iso >= 500))
    cells = result.get("cells") or {}
    high, low = _num(cells.get("max")), _num(cells.get("min"))
    if high is None or low is None:
        high, low = _battery_value(result, "max_cell_v"), _battery_value(result, "min_cell_v")
    if high is not None and low is not None:
        spread = round(high - low, 3)
        rows.append(_judgment("셀 전압 편차", "셀 전압 최대-최소 차이 1.0V 이하 시 양호", spread, "V", spread <= 1))
    t_high, t_low = _battery_value(result, "max_temp"), _battery_value(result, "min_temp")
    modules = [value for n in range(1, 19)
               if (value := _battery_value(result, f"module_temp_{n}")) is not None]
    if len(modules) >= 2:
        t_high, t_low = max(modules), min(modules)
    if t_high is not None and t_low is not None:
        spread = round(t_high - t_low, 1)
        rows.append(_judgment("모듈 온도 편차", "모듈 온도 최대-최소 차이 20°C 이하 시 양호", spread, "°C", spread <= 20))
    return rows


def basic_report(*, scan_id: int, diagnosed_at: datetime, car_no: str, car: dict, result: dict,
                 report_id: int | None, pdf_url: str | None, app_version: str | None = None,
                 app_type: str | None = None) -> dict:
    """해석 결과와 차량정보로 기본 보고서를 만든다."""
    fuel = str(car.get("diag_fuel") or "")
    is_ev = "전기" in fuel or "EV" in fuel.upper() or "수소" in fuel or bool(result.get("battery"))
    mileage = next((_num(v.get("value")) for v in result.get("values") or [] if v.get("key") == "odometer"), None)
    year = _num(car.get("diag_year"))
    vehicle = _present({
        "vehicle_number": car_no,
        "vin": result.get("vin") or car.get("diag_car_id") or None,
        "mileage": mileage,
        "mileage_edited": False if mileage is not None else None,
        "manufacturer": car.get("diag_company"),
        "model": car.get("diag_model"),
        "year": int(year) if isinstance(year, float) and year.is_integer() else year,
        "fuel_type": car.get("diag_fuel"),
    })
    if is_ev:
        sensor = {"ev": _sensor_ev(result, mileage, car), "ice": None}
    else:
        sensor = {"ev": None, "ice": {"vehicle_mileage": mileage} if mileage is not None else None}
    return {
        "diagnosis_info": _present({
            "diagnosis_id": scan_id,
            "diagnosis_type": "BASIC",
            "diagnosed_at": diagnosed_at.isoformat(),
            "app_version": app_version,
            "app_type": _APP_TYPE.get(app_type or "", app_type),
        }),
        "vehicle": vehicle,
        "report": _present({
            "report_id": report_id,
            "report_created_at": diagnosed_at.isoformat(),
            "report_download_url": pdf_url,
        }),
        "dtc": {"enhanced": {"ecus": _ecus(result)}},
        "sensor": sensor,
        "judgments": judgments(result),
    }
