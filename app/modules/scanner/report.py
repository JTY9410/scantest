"""스캔 해석 결과를 위스캔 기본 보고서 구조로 모은다.

수집(run_scan)과 열람(결과 화면)이 같은 키를 쓴다.
diagnosis_info, vehicle, report, dtc.enhanced.ecus, sensor.ev|ice.
없는 값은 키를 넣지 않는다. 통신이 안 된 제어기는 comm_status=fail, code_count=null.
"""

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.scanner.powertrain import LABELS, classify


def _mask_plate(car_no: str) -> str:
    """번호판 마스킹: 앞 숫자+한글 뒤 ****
    
    예: 88가8888 → 88가****
        123가1234 → 123가****
    """
    if not car_no:
        return car_no
    
    # 한글 찾기
    hangul_pos = -1
    for i, char in enumerate(car_no):
        if '가' <= char <= '힣':
            hangul_pos = i
            break
    
    if hangul_pos == -1:
        # 한글이 없으면 전체 마스킹
        return car_no[:3] + "****" if len(car_no) > 3 else car_no
    
    # 한글 뒤 번호를 ****로
    return car_no[:hangul_pos+1] + "****"


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
    modules = [item["value"] for item in module_temperatures(result)]
    if len(modules) >= 2:
        t_high, t_low = max(modules), min(modules)
    if t_high is not None and t_low is not None:
        spread = round(t_high - t_low, 1)
        rows.append(_judgment("모듈 온도 편차", "모듈 온도 최대-최소 차이 20°C 이하 시 양호", spread, "°C", spread <= 20))
    return rows



UNREAD = "측정불가"


def _row(item: str, standard: str, value, unit: str, ok) -> dict:
    if value is None:
        return {"item": item, "standard": standard, "value": None, "unit": unit, "result": UNREAD}
    return _judgment(item, standard, value, unit, bool(ok(value)))


def _cell_spread(result: dict) -> float | None:
    cells = result.get("cells") or {}
    high, low = _num(cells.get("max")), _num(cells.get("min"))
    if high is None or low is None:
        high, low = _battery_value(result, "max_cell_v"), _battery_value(result, "min_cell_v")
    return round(high - low, 3) if high is not None and low is not None else None


def _module_spread(result: dict) -> float | None:
    t_high, t_low = _battery_value(result, "max_temp"), _battery_value(result, "min_temp")
    modules = [item["value"] for item in module_temperatures(result)]
    if len(modules) >= 2:
        t_high, t_low = max(modules), min(modules)
    return round(t_high - t_low, 1) if t_high is not None and t_low is not None else None


def _spread(result: dict, keys: tuple[str, ...], digits: int = 1) -> float | None:
    values = [v for v in (_battery_value(result, key) for key in keys) if v is not None]
    return round(max(values) - min(values), digits) if len(values) == len(keys) else None


def _diff(result: dict, a: str, b: str, digits: int = 2) -> float | None:
    x, y = _battery_value(result, a), _battery_value(result, b)
    return round(abs(x - y), digits) if x is not None and y is not None else None


# LDC 출력 전압(7E5 22E011)·충전 인렛 온도(744 22E004)는 E-GMP(니로EV는 인렛만)에서 canlab.engine.bms.ECU_FIELDS로
# 읽는다(유력). 구동모터·인버터 온도와 U/V/W 옵셋은 근거 있는 정의가 없어 아직 '측정불가'다(HEV LDC도 미확인).
# 규칙이 생겨 result.battery에 같은 키로 들어오면 그대로 판정한다.
LDC, AUX = "ldc_voltage", "aux_voltage"
INLETS = ("dc_inlet_temp_1", "dc_inlet_temp_2", "ac_inlet_temp_1")
MOTOR_T, INVERTER_T = "motor_temp_front", "inverter_temp_front"
OFFSETS = ("motor_offset_u_front", "motor_offset_v_front", "motor_offset_w_front")


def type_judgments(result: dict, kind: str) -> list[dict]:
    """유형별 주요 진단 데이터(샘플 보고서 7항목). 못 읽은 항목은 '측정불가'로 남긴다. 내연기관은 수치 판정이 없다."""
    if kind == "ice":
        return []
    rows = []
    if kind == "ev":
        rows.append(_row("배터리 수명 (SOH)", "SOH 80% 이상 시 양호", _battery_value(result, "soh"), "%",
                         lambda v: v >= 80))
    rows += [
        _row("절연 저항", "절연저항 500 kΩ 이상 시 양호", _battery_value(result, "isolation_kohm"), "kΩ",
             lambda v: v >= 500),
        _row("셀 전압 편차", "셀 전압 최대-최소 차이 1.0V 이하 시 양호", _cell_spread(result), "V", lambda v: v <= 1),
        _row("모듈 온도 편차", "모듈 온도 최대-최소 차이 20°C 이하 시 양호", _module_spread(result), "°C",
             lambda v: v <= 20),
        _row("LDC 출력 전압", "LDC 출력 전압 12.8V 이상 ~ 15.4V 이하 시 양호", _battery_value(result, LDC), "V",
             lambda v: 12.8 <= v <= 15.4),
        _row("LDC-보조배터리 전압 편차", "LDC-보조배터리 전압 차 1.0V 이하 시 양호", _diff(result, LDC, AUX), "V",
             lambda v: v <= 1),
    ]
    if kind == "ev":
        # [확인 필요] 샘플은 '인렛 온도 최대-최소 차이'라고만 적었다. 어떤 인렛들을 비교하는지는 미확인.
        rows.append(_row("인렛 온도 편차", "인렛 온도 최대-최소 차이 100°C 이하 시 양호", _spread(result, INLETS),
                         "°C", lambda v: v <= 100))
    else:
        rows += [
            _row("모터 온도 편차 (Front)", "MCU 모터-인버터 온도 차(Front) 100°C 이하 시 양호",
                 _diff(result, MOTOR_T, INVERTER_T, 1), "°C", lambda v: v <= 100),
            _row("모터 옵셋 편차 (Front)", "MCU 3상 옵셋 최대-최소 차이(Front) 200 이하 시 양호",
                 _spread(result, OFFSETS, 0), "", lambda v: v <= 200),
        ]
    return rows


_ITEM_KEYS = {
    "배터리 수명 (SOH)": ("soh",), "절연 저항": ("isolation_kohm",), "셀 전압 편차": ("max_cell_v", "min_cell_v"),
    "모듈 온도 편차": ("max_temp", "min_temp"), "LDC 출력 전압": (LDC,), "LDC-보조배터리 전압 편차": (LDC, AUX),
    "인렛 온도 편차": INLETS, "모터 온도 편차 (Front)": (MOTOR_T, INVERTER_T), "모터 옵셋 편차 (Front)": OFFSETS,
}
_GRADE_ORDER = {"확인됨": 0, "유력": 1, "미확인": 2}


def attach_grades(rows: list[dict], result: dict) -> None:
    """완료 데이터 대조 결과면 판정 항목마다 근거 값의 신뢰등급(가장 낮은 것)을 붙인다."""
    battery = result.get("battery") or {}
    for row in rows:
        grades = [(battery.get(k) or {}).get("grade") for k in _ITEM_KEYS.get(row["item"], ())]
        grades = [g for g in grades if g in _GRADE_ORDER]
        if grades and row["value"] is not None:
            row["grade"] = max(grades, key=_GRADE_ORDER.get)


def count_significant_dtcs(dtcs: list[dict]) -> int:
    """점검요 판정에 쓸 고장코드 개수: 확정+현재실패 또는 MIL 코드만 센다.
    
    상태 0x08 (confirmed만 켜짐, 과거 확정·현재 실패 아님)은 세지 않는다.
    상태 0x40/0x50 (testNotCompleted만 켜짐, 미완료)은 세지 않는다.
    incomplete=True인 DTC(멀티프레임 미완성)는 표시만 하고 세지 않는다.
    """
    count = 0
    for dtc in dtcs:
        # 멀티프레임 미완성 DTC
        if dtc.get("incomplete"):
            continue
        # confirmed + active 또는 MIL
        if (dtc.get("confirmed") and dtc.get("active")) or dtc.get("mil"):
            count += 1
    return count


def overall(rows: list[dict], dtc_count: int, *, dtc_read: bool = True, mileage: float | int | None = ...):  # ... = sentinel
    """종합판정. 측정한 항목이 기준을 벗어나거나 확정·현재실패 고장코드가 있으면 '점검요',
    그 밖에 고장코드를 읽지 못했거나 측정불가 항목이 하나라도 있으면 '판정보류', 모두 충족하면 '양호'.
    
    규칙: 측정불가(UNREAD)가 하나라도 있거나 주행거리를 읽지 못했으면 판정보류 (2026-11-15 운영 테스트 결과 반영).
    mileage가 명시적으로 전달되지 않으면(...) 주행거리 체크를 건너뜀(이전 동작 호환).
    """
    if dtc_count or any(row["result"] == "주의" for row in rows):
        return "점검요"
    
    # 고장코드를 읽지 못했거나 측정불가 항목이 하나라도 있거나 주행거리 미수신이면 판정보류
    # mileage가 명시적으로 전달되지 않으면(sentinel) 주행거리 체크 건너뜀
    mileage_check_failed = (mileage is not ... and mileage is None)
    if not dtc_read or any(row["result"] == UNREAD for row in rows) or mileage_check_failed:
        return "판정보류"
    
    return "양호"


def powertrain_of(scan, result: dict) -> dict:
    """저장된 스캔 유형을 우선한다(수동 변경·일괄 재분류 반영)."""
    car = dict(result.get("car")) if isinstance(result.get("car"), dict) else {}
    for key, attr in (("diag_fuel", "car_fuel"), ("diag_model", "car_model"), ("diag_submodel", "car_submodel")):
        if not car.get(key) and getattr(scan, attr, None):
            car[key] = getattr(scan, attr)
    stored = result.get("powertrain") if isinstance(result.get("powertrain"), dict) else None
    scan_type = getattr(scan, "type", None)
    if stored and stored.get("type") == scan_type:
        kind = dict(stored)
    elif scan_type in LABELS:
        kind = classify(car, result, manual=scan_type)
    else:
        kind = classify(car, result)
    source = getattr(scan, "type_source", None)
    if source:
        from app.modules.scanner.powertrain import SOURCES
        kind["source"], kind["source_label"] = source, SOURCES.get(source, source)
    return kind


def basic_report(*, scan_id: int, diagnosed_at: datetime, car_no: str, car: dict, result: dict,
                 report_id: int | None, pdf_url: str | None, app_version: str | None = None,
                 app_type: str | None = None) -> dict:
    """해석 결과와 차량정보로 기본 보고서를 만든다."""
    from app.modules.scanner.pdf import mask_plate
    
    kind = result.get("powertrain") if isinstance(result.get("powertrain"), dict) else classify(car, result)
    is_ev = kind["type"] in ("ev", "hev") and bool(result.get("battery") or kind["type"] == "ev")
    mileage = next((_num(v.get("value")) for v in result.get("values") or [] if v.get("key") == "odometer"), None)
    year = _num(car.get("diag_year"))
    vehicle = _present({
        "vehicle_number": mask_plate(car_no),
        "vin": result.get("vin") or car.get("diag_car_id") or None,
        "mileage": mileage,
        "mileage_edited": False if mileage is not None else None,
        "manufacturer": car.get("diag_company"),
        "model": car.get("diag_model"),
        "year": int(year) if isinstance(year, float) and year.is_integer() else year,
        "fuel_type": car.get("diag_fuel"),
        "powertrain": kind["type"],
    })
    if is_ev:
        sensor = {"ev": _sensor_ev(result, mileage, car), "ice": None}
    else:
        sensor = {"ev": None, "ice": {"vehicle_mileage": mileage} if mileage is not None else None}
    # Collect additional info (beyond WESCAN standard)
    additional_info = _collect_additional_info(result, is_ev)
    
    # Collect issues (errors, conflicts, missing values)
    issues = _collect_issues(result, car, kind)
    
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
        "additional_info": additional_info,
        "issues": issues,
    }


def _collect_additional_info(result: dict, is_ev: bool) -> dict:
    """Collect additional information beyond WESCAN standard report."""
    info = {}
    
    # Freeze frame data (고장 당시 값)
    freeze_values = result.get("freeze")
    if freeze_values:
        info["freeze_frame"] = {
            "count": len(freeze_values),
            "available": True
        }
    
    # UDS snapshot data (제어기 고장 당시 데이터)
    snapshot_count = sum(1 for ecu in result.get("diagnosis", {}).get("ecus", []) 
                        if ecu.get("snapshots"))
    if snapshot_count > 0:
        info["uds_snapshots"] = {
            "count": snapshot_count,
            "available": True
        }
    
    # Module temperatures (모듈 온도)
    if is_ev:
        modules = module_temperatures(result)
        if modules:
            info["module_temperatures"] = {
                "count": len(modules),
                "available": True
            }
        
        # Cell voltages (셀 전압)
        cells = cell_voltages(result)
        if cells:
            info["cell_voltages"] = {
                "count": len(cells),
                "available": True
            }
    
    # Real-time values (실시간 데이터)
    values = result.get("values", [])
    if values:
        info["realtime_values"] = {
            "count": len(values),
            "available": True
        }
    
    # Monitor results (배출 부품 점검)
    monitors = result.get("monitors", [])
    if monitors:
        info["emission_monitors"] = {
            "count": len(monitors),
            "available": True
        }
    
    return info


def _collect_issues(result: dict, car: dict, kind: dict) -> dict:
    """Collect issues: errors, conflicts, missing values."""
    issues = {}
    
    # Errors (오류 기록)
    errors = result.get("errors", [])
    if errors:
        issues["errors"] = {
            "count": len(errors),
            "summary": [e.get("label", "Unknown error") for e in errors[:5]]
        }
    
    # Powertrain conflict (동력원 충돌)
    # Note: This info is in scan object, not in result dict
    # We'll check it from car dict if available
    if car.get("powertrain_conflict"):
        issues["powertrain_conflict"] = {
            "detected": True,
            "plate_type": car.get("plate_powertrain"),
            "vin_type": car.get("vin_powertrain")
        }
    
    # Missing critical values (주요 값 출처 없음)
    sensor = result.get("battery", {})
    missing_critical = []
    
    if kind.get("type") in ("ev", "hev"):
        if not sensor.get("soc") and not sensor.get("display_soc"):
            missing_critical.append("SOC (충전 상태)")
        if not sensor.get("soh"):
            missing_critical.append("SOH (배터리 건강)")
    
    if missing_critical:
        issues["missing_critical_values"] = {
            "count": len(missing_critical),
            "list": missing_critical  # Changed from 'items' to avoid Jinja2 conflict with dict.items()
        }
    
    # Status summary
    status = result.get("status")
    if status in ("fail", "partial"):
        issues["scan_status"] = {
            "status": status,
            "message": "스캔 실패" if status == "fail" else "일부 항목 오류"
        }
    
    return issues


_GROUP_ECU = {
    "7E0": "engine", "7E8": "engine", "7E1": "tm", "7E9": "tm",
    "7E4": "bms", "7EC": "bms", "7E5": "mcu", "7ED": "mcu",
    "7E6": "power", "7EE": "power", "7E7": "charge", "7EF": "charge",
}
_GROUP_SYSTEM = {"chassis": "chassis", "body": "body", "network": "network", "transmission": "tm"}
_GROUP_LABELS = {
    "engine": "엔진", "tm": "변속기", "bms": "BMS (배터리)", "mcu": "MCU (모터)", "power": "통합전력",
    "charge": "차량충전", "other": "P 코드 기타", "chassis": "샤시", "body": "바디", "network": "통신",
}
# 샘플 보고서 계통: 전기차 8 · 하이브리드 8(플러그인은 차량충전 추가) · 내연기관 6.
GROUP_KEYS = {
    "ev": ("bms", "mcu", "power", "charge", "other", "chassis", "body", "network"),
    "hev": ("engine", "tm", "bms", "mcu", "other", "chassis", "body", "network"),
    "phev": ("engine", "tm", "bms", "mcu", "charge", "other", "chassis", "body", "network"),
    "ice": ("engine", "tm", "other", "chassis", "body", "network"),
}
_GROUPS = tuple((key, _GROUP_LABELS[key]) for key in GROUP_KEYS["ev"])
_MODULE = re.compile(r"^module_temp_(?:(\d+)|([Bb]\d+))$")


def module_temperatures(result: dict) -> list[dict]:
    """모듈 온도. 이상값은 빼서 번호 순으로 돌려준다. B17/B18 같은 알파벳 번호도 포함."""
    rows = []
    for key, item in (result.get("battery") or {}).items():
        if not (match := _MODULE.match(key)) or item.get("outlier") or _num(item.get("value")) is None:
            continue
        # 숫자 번호 또는 B17/B18 같은 알파벳 번호
        no_str = match.group(1) or match.group(2)
        rows.append({"no": no_str, "value": _num(item.get("value"))})
    # 숫자는 정수로, B17은 문자열 그대로 정렬
    def sort_key(row):
        no = row["no"]
        if no.isdigit():
            return (0, int(no))
        return (1, no.upper())
    return sorted(rows, key=sort_key)


def cell_voltages(result: dict) -> list[dict]:
    cells = result.get("cells") or {}
    return [{"no": cell.get("no"), "voltage": _num(cell.get("voltage"))}
            for cell in cells.get("values") or [] if _num(cell.get("voltage")) is not None]


def _dtc_group(dtc: dict, keys: tuple[str, ...]) -> str:
    key = _GROUP_ECU.get(str(dtc.get("ecu") or "").upper())
    if key in keys:
        return key
    system = _GROUP_SYSTEM.get(dtc.get("system"))
    if system in keys:
        return system
    code = str(dtc.get("code") or "").upper()
    prefix = {"C": "chassis", "B": "body", "U": "network"}.get(code[:1])
    return prefix if prefix in keys else "other"


def dtc_groups(result: dict, kind: str = "ev") -> list[dict]:
    """유형별 계통 집계(전기차·하이브리드 8, 내연기관 6). 고장코드는 한 계통에만 센다."""
    keys = GROUP_KEYS.get(kind, GROUP_KEYS["ev"])
    counts = {key: 0 for key in keys}
    for dtc in result.get("dtcs") or []:
        counts[_dtc_group(dtc, keys)] += 1
    return [{"key": key, "label": _GROUP_LABELS[key], "count": counts[key]} for key in keys]


def dtc_rows(result: dict, kind: str = "ev") -> list[dict]:
    """고장 코드 상세(코드·계통·제어기·상태·설명)."""
    keys = GROUP_KEYS.get(kind, GROUP_KEYS["ev"])
    rows = []
    for dtc in result.get("dtcs") or []:
        rows.append({"code": dtc.get("code") or "-", "group": _GROUP_LABELS[_dtc_group(dtc, keys)],
                     "ecu": _ecu_name(dtc.get("ecu")) or dtc.get("ecu") or "-",
                     "status": dtc.get("kind") or "-", "desc": dtc.get("desc") or "미확인",
                     "is_ai": dtc.get("knowledge_source") == "ai"})
    return rows


def _measure(label: str, value: float | int | None, unit: str, digits: int | None = None) -> dict:
    if value is None:
        text = "-"
    elif isinstance(value, float):
        text = f"{value:,.{digits}f}" if digits is not None else f"{value:,.4g}"
    else:
        text = f"{value:,}"
    return {"label": label, "value": value, "text": text, "unit": unit}


def _local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(ZoneInfo("Asia/Seoul"))


HEADINGS = {
    "ev": ("EV TECHNICAL INSPECTION REPORT", "EV 기술 진단 보고서", "WESCAN 진단 솔루션 기반 · 전기차 고전압 시스템 정밀 진단"),
    "hev": ("HEV TECHNICAL INSPECTION REPORT", "HEV 기술 진단 보고서",
            "WESCAN 진단 솔루션 기반 · 하이브리드 고전압 시스템 정밀 진단"),
    "ice": ("OBD-II DIAGNOSTIC REPORT", "자동차 DTC 진단 보고서", "WESCAN 진단 솔루션 기반 · 주요 ECU 고장 코드 진단"),
}


def inspection(scan, result: dict) -> dict:
    """WeSCAN 기본 진단 보고서(전기차 EV · 하이브리드 HEV · 내연기관 OBD-II)에 넣을 값.

    읽지 못한 칸은 '-'다. 없는 측정값을 만들지 않는다.
    """
    when = _local(getattr(scan, "created_at", None))
    car = result.get("car") if isinstance(result.get("car"), dict) else {}
    pt = powertrain_of(scan, result)
    kind = pt["type"]
    group_kind = "phev" if kind == "hev" and pt.get("plugin") else kind
    soh = _battery_value(result, "soh")
    mileage = next((_num(item.get("value")) for item in result.get("values") or []
                    if item.get("key") == "odometer"), None)
    if mileage is None and getattr(scan, "car_distance", None) is not None:
        mileage = _num(scan.car_distance)
    judged = type_judgments(result, kind)
    if result.get("source") == "reconcile":
        attach_grades(judged, result)
    passed = sum(row["result"] == "양호" for row in judged)
    unread = sum(row["result"] == UNREAD for row in judged)
    dtcs = result.get("dtcs") or []
    ecus = _ecus(result)
    dtc_read = bool(dtcs) or any(e["comm_status"] == "success" for e in ecus) or not result.get("steps")
    significant_dtc_count = count_significant_dtcs(dtcs)
    verdict = overall(judged, significant_dtc_count, dtc_read=dtc_read, mileage=mileage)
    if kind != "ev":
        soh_note = "하이브리드 차량은 SOH를 판정하지 않습니다." if kind == "hev" else ""
    elif soh is None:
        soh_note = "SOH를 읽지 못했습니다."
    elif soh >= 80:
        soh_note = f"양호 판정 기준 80%를 {soh - 80:.1f}%p 상회합니다."
    else:
        soh_note = f"양호 판정 기준 80%에 {80 - soh:.1f}%p 못 미칩니다."
    if kind == "ice":
        judgment_note = "고장 코드 진단 보고서(수치 판정 항목 없음)"
    elif passed == len(judged):
        judgment_note = f"진단 항목 {len(judged)}개 전항 충족"
    else:
        judgment_note = f"진단 항목 {len(judged)}개 중 양호 {passed}개" + (f" · 측정불가 {unread}개" if unread else "")
    cells = cell_voltages(result)
    cell_stat = result.get("cells") or {}
    cell_max = _num(cell_stat.get("max"))
    cell_min = _num(cell_stat.get("min"))
    if cell_max is None or cell_min is None:
        cell_max, cell_min = _battery_value(result, "max_cell_v"), _battery_value(result, "min_cell_v")
    
    # 최저 셀 번호 두 기준 (요약 DID vs 셀별 계산)
    min_cell_summary = _battery_value(result, "min_cell_no")  # 0101 요약에서 읽은 번호
    min_cell_calculated = []  # 셀별 전압에서 계산한 번호들
    if cells and cell_min is not None:
        min_cell_calculated = [c["no"] for c in cells if c.get("voltage") == cell_min]
    
    # 두 기준이 모두 있고 불일치하면 표시
    cell_no_mismatch = None
    if min_cell_summary is not None and min_cell_calculated and min_cell_summary not in min_cell_calculated:
        cell_no_mismatch = {
            "summary": int(min_cell_summary),
            "calculated": min_cell_calculated,
            "voltage": cell_min,
        }
    modules = module_temperatures(result)
    module_values = [row["value"] for row in modules]
    temp_max = max(module_values) if module_values else _battery_value(result, "max_temp")
    temp_min = min(module_values) if module_values else _battery_value(result, "min_temp")
    groups = dtc_groups(result, group_kind)
    charge_codes = sum(1 for d in dtcs if _GROUP_ECU.get(str(d.get("ecu") or "").upper()) == "charge")
    code = f"WeSCAN-{(when or datetime.now(ZoneInfo('Asia/Seoul'))):%Y%m%d}-{int(getattr(scan, 'id', 0) or 0):08d}"
    maker = getattr(scan, "car_maker", None) or car.get("diag_company")
    model = getattr(scan, "car_model", None) or car.get("diag_model")
    if kind == "ev":
        power = [
            _measure("보조 배터리 SOC", _battery_value(result, "aux_soc"), "%", 1),
            _measure("보조 배터리 전압", _battery_value(result, AUX), "V", 1),
            _measure("LDC 출력 전압", _battery_value(result, LDC), "V", 1),
            _measure("DC 인렛 온도 1", _battery_value(result, INLETS[0]), "℃", 1),
            _measure("DC 인렛 온도 2", _battery_value(result, INLETS[1]), "℃", 1),
            _measure("AC 인렛 온도 1", _battery_value(result, INLETS[2]), "℃", 1),
            _measure("인버터 온도 (Front)", _battery_value(result, INVERTER_T), "℃", 1),
            _measure("충전 계통 고장코드", charge_codes, "건", 0),
            _measure("배터리 입구 온도", _battery_value(result, "inlet_temp"), "℃", 1),
            _measure("인버터 커패시터 전압", _battery_value(result, "inverter_cap_voltage"), "V", 1),
        ]
    elif kind == "hev":
        power = [
            _measure("보조 배터리 SOC", _battery_value(result, "aux_soc"), "%", 1),
            _measure("보조 배터리 전압", _battery_value(result, AUX), "V", 1),
            _measure("LDC 출력 전압", _battery_value(result, LDC), "V", 1),
            _measure("인버터 온도 (Front)", _battery_value(result, INVERTER_T), "℃", 1),
            _measure("구동 모터 온도 (Front)", _battery_value(result, MOTOR_T), "℃", 1),
            _measure("U상 전류센서 오프셋 (Front)", _battery_value(result, OFFSETS[0]), "", 0),
            _measure("V상 전류센서 오프셋 (Front)", _battery_value(result, OFFSETS[1]), "", 0),
            _measure("W상 전류센서 오프셋 (Front)", _battery_value(result, OFFSETS[2]), "", 0),
        ]
        if pt.get("plugin"):
            # 플러그인 하이브리드: 충전 항목(표시만, 판정 기준은 샘플에 없음).
            power += [
                _measure("DC 인렛 온도 1", _battery_value(result, INLETS[0]), "℃", 1),
                _measure("AC 인렛 온도 1", _battery_value(result, INLETS[2]), "℃", 1),
                _measure("충전 계통 고장코드", charge_codes, "건", 0),
            ]
    else:
        power = []
    heading = HEADINGS[kind]
    # Collect additional info and issues for WESCAN report structure
    is_ev_kind = kind in ("ev", "hev")
    additional_info = _collect_additional_info(result, is_ev_kind)
    issues = _collect_issues(result, car, pt)
    
    return {
        "kind": kind,
        "kind_label": LABELS[kind] + (" (플러그인)" if pt.get("plugin") else "") + (" (수소)" if pt.get("hydrogen") else ""),
        "powertrain": pt,
        "plugin": bool(pt.get("plugin")),
        "hydrogen": bool(pt.get("hydrogen")),
        "heading_en": heading[0], "heading": heading[1], "subheading": heading[2],
        "pages": 2 if kind == "ice" else 5,
        "code": code,
        "issued_on": when.strftime("%Y.%m.%d") if when else "-",
        "diagnosed_at": when.strftime("%Y. %m. %d.") if when else "-",
        "vehicle": {
            "manufacturer": maker or "-",
            "model": model or "-",
            "year": getattr(scan, "car_year", None) or car.get("diag_year") or "-",
            "fuel": getattr(scan, "car_fuel", None) or car.get("diag_fuel") or "-",
            "number": _mask_plate(getattr(scan, "car_no", None) or "-"),
            "vin": result.get("vin") or getattr(scan, "car_vin", None) or "-",
            "mileage": mileage,
            "mileage_text": f"{mileage:,.0f} km" if mileage is not None else "-",
        },
        "title": " ".join(part for part in (maker, model) if part),
        "soh": soh,
        "soh_note": soh_note,
        "mileage_note": f"주행거리 {mileage:,.0f} km 시점 진단" if mileage is not None else "주행거리를 읽지 못했습니다.",
        "overall": verdict,
        "judgment_note": judgment_note,
        "unread": unread,
        "dtc_clear": not dtcs,
        "dtc_count": len(dtcs),
        "significant_dtc_count": significant_dtc_count,
        "dtc_read": dtc_read,
        "dtc_rows": dtc_rows(result, group_kind),
        "groups": groups,
        "judgments": judged,
        "reconcile": (lambda rc: rc if rc else None)(
            result.get("reconcile") if result.get("source") == "reconcile" else None
        ),
        "reference": result.get("reference") or {},
        "bms": [] if kind == "ice" else [
            _measure("SOC (표시)", _battery_value(result, "soc_display")
                     if _battery_value(result, "soc_display") is not None else _battery_value(result, "soc"), "%", 1),
            _measure("SOH", soh, "%", 1),
            _measure("팩 전압", _battery_value(result, "pack_voltage"), "V", 1),
            _measure("팩 전류", _battery_value(result, "pack_current"), "A", 1),
            _measure("최고 온도", temp_max, "℃", 1),
            _measure("최저 온도", temp_min, "℃", 1),
            _measure("절연 저항", _battery_value(result, "isolation_kohm"), "kΩ", 0),
            _measure("내부 저항", None, ""),
            _measure("셀 최고 전압", cell_max, "V", 2),
            _measure("셀 최저 전압", cell_min, "V", 2),
            _measure("급속 충전 횟수", _battery_value(result, "quick_charge_count"), "회", 0),
            _measure("완속 충전 횟수", _battery_value(result, "normal_charge_count"), "회", 0),
        ],
        "power": power,
        "cells": cells,
        "cell_min": cell_min,
        "cell_max": cell_max,
        "cell_spread": round(cell_max - cell_min, 3) if cell_max is not None and cell_min is not None else None,
        "cell_no_mismatch": cell_no_mismatch,
        "modules": modules,
        "module_min": temp_min if modules else None,
        "module_max": temp_max if modules else None,
        "module_spread": round(max(module_values) - min(module_values), 1) if len(module_values) >= 2 else None,
        "additional_info": additional_info,
        "issues": issues,
    }


def tesla_inspection(scan) -> dict:
    """Tesla 업로드 스캔의 진단 보고서 view.
    
    scan.bms_data에서 Tesla 디코딩 데이터를 읽어 WESCAN EV 진단서 형식으로 변환.
    """
    when = _local(getattr(scan, "created_at", None))
    tesla_data = scan.bms_data or {}
    decoded = tesla_data.get('decoded', {})
    soh_result = tesla_data.get('soh', {})
    
    # 차량 정보
    manufacturer = tesla_data.get('manufacturer', 'Tesla')
    model = tesla_data.get('model', 'Model 3')
    year = tesla_data.get('year')
    vin = tesla_data.get('vin', scan.scan_vin or scan.car_vin)
    
    # 에너지 (0x352)
    energy_data = decoded.get('energy', {})
    current_full = energy_data.get('nominal_full_pack_energy')  # kWh
    remaining = energy_data.get('nominal_energy_remaining')  # kWh
    
    # SOC (0x292)
    soc_data = decoded.get('soc', {})
    soc = soc_data.get('soc_ave')  # %
    
    # 브릭 전압 (0x401)
    bricks_data = decoded.get('bricks', {})
    brick_min_v = bricks_data.get('min_voltage')  # V
    brick_max_v = bricks_data.get('max_voltage')  # V
    brick_min_no = bricks_data.get('min_brick_num')
    brick_max_no = bricks_data.get('max_brick_num')
    brick_spread = round(brick_max_v - brick_min_v, 3) if brick_max_v and brick_min_v else None
    
    # 온도 (0x332)
    temps_data = decoded.get('temps', {})
    temp_max = temps_data.get('max_temp')  # °C
    temp_min = temps_data.get('min_temp')  # °C
    
    # 팩 전압/전류 (0x132)
    pack_data = decoded.get('pack', {})
    pack_voltage = pack_data.get('pack_voltage')  # V
    pack_current = pack_data.get('pack_current')  # A
    
    # SOH (community reference)
    soh_pct = soh_result.get('soh_pct')
    soh_note = soh_result.get('calculation_note', '')
    reference_kwh = soh_result.get('reference_kwh')
    reference_source = soh_result.get('reference_source', '')
    soh_available = soh_result.get('soh_available', False)
    
    # 판정
    judgment = tesla_data.get('judgment', '판정보류')
    judgment_reason = tesla_data.get('judgment_reason', '커뮤니티 기준 / 측정불가')
    
    # 측정불가 항목
    unmeasurable_items = []
    if not current_full:
        unmeasurable_items.append({"item": "만충 에너지", "reason": "0x352 데이터 미수신"})
    if not soc:
        unmeasurable_items.append({"item": "SOC", "reason": "0x292 데이터 미수신"})
    if not brick_min_v or not brick_max_v:
        unmeasurable_items.append({"item": "브릭 전압", "reason": "0x401 데이터 미수신"})
    if not temp_max or not temp_min:
        unmeasurable_items.append({"item": "배터리 온도", "reason": "0x332 데이터 미수신"})
    if not pack_voltage:
        unmeasurable_items.append({"item": "팩 전압", "reason": "0x132 데이터 미수신"})
    
    # 추가 수집 정보 및 문제점
    additional_issues = []
    additional_issues.append("Tesla 차량은 OBD-II 진단 프로토콜 대신 CAN 브로드캐스트 방식으로 데이터를 수집합니다.")
    additional_issues.append("제공되는 SOH 값은 커뮤니티 기준을 바탕으로 한 참고치이며, Tesla 공식 측정값이 아닙니다.")
    if not soh_available:
        additional_issues.append(f"SOH 계산 불가: {soh_note}")
    additional_issues.append("일부 항목(셀별 전압, 급속/완속 충전 횟수 등)은 Tesla CAN 메시지에서 제공되지 않습니다.")
    
    code = f"WeSCAN-{(when or datetime.now(ZoneInfo('Asia/Seoul'))):%Y%m%d}-{int(getattr(scan, 'id', 0) or 0):08d}"
    
    return {
        "kind": "ev",
        "kind_label": "전기차 (Tesla)",
        "powertrain": {"type": "ev", "source": "tesla_upload", "plugin": False, "hydrogen": False},
        "plugin": False,
        "hydrogen": False,
        "heading_en": "ELECTRIC VEHICLE DIAGNOSTIC REPORT",
        "heading": "전기차 진단 보고서",
        "subheading": "TESLA BATTERY DIAGNOSTIC",
        "pages": 5,
        "code": code,
        "issued_on": when.strftime("%Y.%m.%d") if when else "-",
        "diagnosed_at": when.strftime("%Y. %m. %d.") if when else "-",
        "vehicle": {
            "manufacturer": manufacturer,
            "model": model,
            "year": year or "-",
            "fuel": "electric",
            "number": _mask_plate(scan.car_no),
            "vin": vin or "-",
            "mileage": None,
            "mileage_text": "-",
        },
        "title": f"{manufacturer} {model}",
        "soh": soh_pct,
        "soh_note": f"SOH 참고치(미검증): {soh_note}" if soh_note else "SOH를 읽지 못했습니다.",
        "mileage_note": "주행거리 정보가 제공되지 않습니다.",
        "overall": judgment,
        "judgment_note": judgment_reason,
        "unread": len(unmeasurable_items),
        "dtc_clear": True,
        "dtc_count": 0,
        "significant_dtc_count": 0,
        "dtc_read": False,
        "dtc_rows": [],
        "groups": [],
        "judgments": [],
        "reconcile": None,
        "reference": {
            "bol_energy_kwh": reference_kwh,
            "source": reference_source,
        } if reference_kwh else {},
        "bms": [
            _measure("만충 에너지", current_full, "kWh", 1),
            _measure("잔여 에너지", remaining, "kWh", 1),
            _measure("SOC", soc, "%", 1),
            _measure("SOH 참고치", soh_pct, "%", 1) if soh_pct else _measure("SOH 참고치", None, ""),
            _measure("팩 전압", pack_voltage, "V", 1),
            _measure("팩 전류", pack_current, "A", 1),
            _measure("최고 온도", temp_max, "℃", 1),
            _measure("최저 온도", temp_min, "℃", 1),
            _measure("브릭 최고 전압", brick_max_v, "V", 3),
            _measure("브릭 최저 전압", brick_min_v, "V", 3),
            _measure("브릭 전압 편차", brick_spread, "V", 3),
            _measure("최고 전압 브릭 번호", brick_max_no, "", 0),
            _measure("최저 전압 브릭 번호", brick_min_no, "", 0),
        ],
        "power": [],
        "cells": [],  # Tesla는 96개 브릭 전체 데이터를 제공하지 않음
        "cell_min": brick_min_v,
        "cell_max": brick_max_v,
        "cell_spread": brick_spread,
        "cell_no_mismatch": None,
        "modules": [],
        "module_min": temp_min,
        "module_max": temp_max,
        "module_spread": round(temp_max - temp_min, 1) if temp_max and temp_min else None,
        "additional_info": unmeasurable_items,
        "issues": additional_issues,
        "tesla_specific": True,  # Flag for PDF rendering
    }
