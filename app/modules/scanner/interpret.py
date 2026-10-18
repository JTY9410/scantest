"""스캔 결과 해석: 단계별 응답 → 위스캔 결과(차량 상태값, 고장코드, 배터리, 통신 정보, 오류)."""

import re
from typing import Any

from app.modules.canlab.engine import obdb, signals
from app.modules.canlab.engine.decode import Trace, decode_signals, load_trace
from app.modules.canlab.engine.frames import elm_from_exchanges
from app.modules.canlab.engine.search import Layout, load_references
from app.modules.scanner import obd
from app.modules.scanner.plan import DOIP_NOTE

# 지원하지 않아도 문제가 아닌 상태. 오류 목록이 아니라 '지원 안 함'으로 보여 준다.
# 응답 지연(NRC 78)은 ECU가 살아 있다는 뜻이라 오류로 세지 않는다.
INFO_STATUSES = {"ok", "unsupported", "skipped", "pending"}
BROADCAST = {"can11": "7DF", "can29": "18DB33F1"}
REFERENCE_CONFIDENCE = 0.5
CELL_RANGE = (1.5, 4.6)
_ECU_LABEL = re.compile(r" (?:차대번호|고장코드|고장 당시|부품번호|소프트웨어 버전|BMS 배터리|실주행거리)")
# 실주행거리 제조사 DID 우선순위(위카 앱 dev getClusterRange 순서). 표준 01 A6이 있으면 그것을 쓴다.
ODOMETER_SOURCES = (("7E5", "1050"), ("7C6", "B002"), ("7C6", "B004"), ("7C6", "B001"), ("7C6", "B003"))
ODOMETER_MISMATCH = 0.05
# 같은 고장코드를 여러 서비스로 읽었을 때 대표로 보여 줄 종류 순서
KIND_ORDER = ("현재", "확정", "영구", "대기", "기록")
PRIMARY_ECU = "7E8"


def _ecu_address(ecu: int) -> str:
    """ECU는 응답 주소로 부른다(11비트 7E8, 29비트 18DAF110, K-Line 10)."""
    if ecu > 0x7FF:
        return f"{ecu:08X}"
    return f"{ecu:03X}" if ecu > 0xFF else f"{ecu:02X}"


def _request_of(address: str) -> str | None:
    """응답 주소 → 물리 요청 주소. 11비트는 -8, 29비트는 18DA F1xx → 18DA xxF1."""
    if len(address) == 8 and address.startswith("18DAF1"):
        return f"18DA{address[6:]}F1"
    if len(address) == 3:
        return f"{int(address, 16) - 8:03X}"
    return None


def _merge_dtcs(dtcs: list[dict]) -> list[dict]:
    """(코드 앞 5자, ECU)가 같으면 한 건으로 합치고, 읽은 종류·출처를 모두 남긴다."""
    merged: dict[tuple[str, str], dict] = {}
    for dtc in dtcs:
        key = (dtc["code"][:5], dtc["ecu"])
        if key not in merged:
            merged[key] = dtc | {"kinds": [dtc["kind"]], "sources": [dtc["source"]]}
            continue
        entry = merged[key]
        if dtc["kind"] not in entry["kinds"]:
            entry["kinds"].append(dtc["kind"])
        if dtc["source"] not in entry["sources"]:
            entry["sources"].append(dtc["source"])
        entry["active"] = entry.get("active") or dtc.get("active")
        entry["confirmed"] = entry.get("confirmed") or dtc.get("confirmed")
        if len(dtc["code"]) > len(entry["code"]):
            entry["code"] = dtc["code"]
    result = []
    for entry in merged.values():
        entry["kinds"].sort(key=lambda k: KIND_ORDER.index(k) if k in KIND_ORDER else len(KIND_ORDER))
        result.append(entry | {"kind": entry["kinds"][0], "system": obd.dtc_system(entry["code"])})
    return result


def _primary(candidates: dict[str, set[int]]) -> str | None:
    """대표 ECU: 엔진(7E8)이 있으면 그것, 없으면 지원 PID가 가장 많은 ECU."""
    if PRIMARY_ECU in candidates:
        return PRIMARY_ECU
    return max(candidates, key=lambda a: len(candidates[a]), default=None)


def _row(step: dict, status: str, message: str) -> dict:
    return {
        "id": step.get("id"), "group": step.get("group"), "label": step.get("label") or step.get("command"),
        "header": step.get("header"), "command": step.get("command"), "status": status,
        "status_label": obd.STATUS_LABELS.get(status, status), "message": message,
        "raw": re.sub(r"\s+", " ", step.get("reply") or "").strip()[:200],
    }


def _voltage(reply: str | None) -> float | None:
    match = re.search(r"(\d{1,2}\.\d)\s*V", reply or "", re.I)
    return float(match[1]) if match else None


def _rows(trace: Trace, kwp: dict | None, layout: Layout) -> tuple[list, str]:
    """22 DID 응답, 없으면 같은 번호의 구형 KWP 21 응답."""
    rows = trace.samples.get((layout.request_id, layout.did))
    if rows:
        return rows, f"{layout.request_id:03X} 22 {layout.did:04X}"
    rows = (kwp or {}).get((layout.request_id, layout.did)) or []
    return rows, f"{layout.request_id:03X} 21 {layout.did & 0xFF:02X}"


def battery_values(trace: Trace, rules: list, kwp: dict | None = None, model: dict | None = None) -> dict[str, dict]:
    """적용 규칙 → OBDb 차종 정의 → 공개 참고 해석 순서로 읽는다. 규칙이 아닌 값은 '미검증'으로 표시한다.

    kwp: 구형 KWP 21 01·21 05 응답 데이터((요청 ID, 01xx) → [(시각, 데이터)]). 22 01xx 응답이 없을 때만
    같은 배치로 읽는다. model: obdb.match(car) 결과.
    """
    values = decode_signals(trace.samples, rules)
    for value in values.values():
        value["series"] = [list(p) for p in value["series"][-50:]]
    candidates = [(key, layout, f"OBDb {model['repo']}", normal)
                  for key, layout, normal in obdb.signal_layouts(model)] if model else []
    candidates += [(item["signal"], Layout.from_dict(item), "공개 참고 해석", None)
                   for item in load_references()["hypotheses"]]
    for key, layout, origin, normal in candidates:
        signal = signals.BY_KEY.get(key)
        if key in values or signal is None:
            continue
        rows, source = _rows(trace, kwp, layout)
        value = layout.value(rows[-1][1]) if rows else None
        if value is None or not signal.minimum <= value <= signal.maximum:
            continue
        values[key] = {
            "value": value, "series": [[round(rows[-1][0], 1), value]], "label": signal.label,
            "unit": signal.unit, "rule_id": None, "rule_version": None, "confidence": REFERENCE_CONFIDENCE,
            "formula": layout.formula(), "source": source, "origin": origin, "reference": True,
        }
        if normal:
            values[key].update(range=list(normal), outlier=not normal[0] <= value <= normal[1])
    return values


def cell_voltages(trace: Trace, model: dict | None) -> dict | None:
    """OBDb 셀 배치로 읽은 셀 전압. 0 V 등 범위 밖 값(셀이 없는 자리)은 뺀다.

    OBDb 정상 범위를 벗어난 셀은 '이상값'(outliers)으로 따로 두고 최저·최고·편차·합 계산에서 뺀다.
    """
    if not model or not model["cells"]:
        return None
    cells, outliers, normal = [], [], None
    for number, layout, limits in obdb.cell_layouts(model):
        rows = trace.samples.get((layout.request_id, layout.did))
        value = layout.value(rows[-1][1]) if rows else None
        if value is None or not CELL_RANGE[0] <= value <= CELL_RANGE[1]:
            continue
        cell = {"no": number, "voltage": round(value, 3)}
        normal = normal or limits
        (outliers if limits and not limits[0] <= value <= limits[1] else cells).append(cell)
    if not cells:
        return None
    voltages = [c["voltage"] for c in cells]
    return {"values": cells, "count": len(cells), "min": min(voltages), "max": max(voltages),
            "spread_mv": round((max(voltages) - min(voltages)) * 1000), "sum": round(sum(voltages), 1),
            "range": list(normal) if normal else None, "outliers": outliers, "origin": f"OBDb {model['repo']}"}


def record_text(steps: list[dict], bus: str | None, meta: dict[str, str]) -> str:
    exchanges = []
    for step in steps:
        command = (step.get("command") or "").upper()
        if command.startswith("AT") or step.get("reply") is None:
            continue
        exchanges.append({"t_ms": step.get("t_ms") or 0, "command": command,
                          "header": step.get("header") or BROADCAST.get(bus or "", "7DF"),
                          "reply": step.get("reply")})
    return elm_from_exchanges(exchanges, meta, bus=bus)


def detect_protocol(steps: list[dict]) -> dict:
    protocol = {"code": None, "name": "알 수 없음", "bus": None}
    for step in steps:
        if (step.get("command") or "").upper() == "ATDPN" and step.get("reply"):
            code, name, bus = obd.protocol_of(step["reply"])
            if code:
                protocol = {"code": code, "name": name, "bus": bus}
    return protocol


def interpret(steps: list[dict], rules: list, record: str, car: dict | None = None) -> tuple[dict[str, Any], Trace]:
    """steps: 계획 단계에 reply(응답 문자열), error(클라이언트 오류), t_ms를 붙인 목록.
    record: record_text로 만든 ELM 기록. car: 차량정보(OBDb 차종 선택용). 결과와 함께 다시 읽은 Trace를 돌려준다.
    """
    rows: list[dict] = []
    protocol = detect_protocol(steps)
    bus = protocol["bus"]

    voltage = None
    supported: set[int] = set()
    supported_by_ecu: dict[str, set[int]] = {}
    ecu_values: dict[str, dict[str, dict]] = {}
    readiness: dict[str, dict] = {}
    drive_readiness: dict[str, dict] = {}
    monitor_tests: list[dict] = []
    iumpr: dict | None = None
    snapshots: list[dict] = []
    kwp: dict[tuple[int, int], list[tuple[float, bytes]]] = {}
    dtcs: list[dict] = []
    vins: dict[str, str] = {}
    calids: list[str] = []
    cvns: list[str] = []
    ecu_names: list[str] = []
    ecus: dict[str, dict] = {}
    freeze: dict[str, Any] = {"dtc": None, "values": []}
    odometers: dict[tuple[str, str], int] = {}

    for step in steps:
        command = (step.get("command") or "").upper()
        error = step.get("error")
        if error == "skipped":
            reason = step.get("reason") or "앞 단계 결과에 따라 건너뛰었습니다."
            rows.append(_row(step, "unsupported" if "지원하지 않는" in reason else "skipped", reason))
            continue
        if command.startswith("AT"):
            if error or step.get("reply") is None:
                outcome = obd.evaluate("00", None, None, error)
                rows.append(_row(step, outcome.status, outcome.message))
            elif (failure := obd.elm_error(step["reply"])) is not None:
                rows.append(_row(step, *failure))
            else:
                if command == "ATRV":
                    voltage = _voltage(step["reply"])
                rows.append(_row(step, "ok", re.sub(r"\s+", " ", step["reply"]).strip()[:60]))
            continue
        if step.get("bus") == "can" and bus and not bus.startswith("can"):
            rows.append(_row(step, "skipped", "K-Line·J1850 차량이라 CAN 전용(UDS) 조회를 건너뛰었습니다."))
            continue

        outcome = obd.evaluate(command, step.get("reply"), bus, error)
        status, message = outcome.status, outcome.message
        if status in ("no_data", "negative") and step.get("optional"):
            status, message = "unsupported", f"이 차량·ECU가 지원하지 않습니다({message})"
        if command[:2] == "01" and len(command) == 4 and status == "no_data" and supported \
                and int(command[2:], 16) not in supported:
            status, message = "unsupported", "지원 항목 목록에 없는 PID입니다."
        rows.append(_row(step, status, message))
        if not outcome.positive:
            continue

        service = int(command[:2], 16)
        for ecu, payloads in outcome.positive.items():
            address = _ecu_address(ecu)
            entry = ecus.setdefault(address, {"address": address, "request": _request_of(address) or step.get("header"),
                                              "label": None, "services": []})
            if step.get("header") and step.get("group") in ("uds", "maker"):
                entry["label"] = entry["label"] or _ECU_LABEL.split(step.get("label") or "")[0]
            if command[:2] not in entry["services"]:
                entry["services"].append(command[:2])

        first = next(iter(outcome.positive.values()))
        for ecu, payloads in outcome.positive.items():
            address = _ecu_address(ecu)
            for payload in payloads:
                if service == 0x01:
                    pid = payload[1] if len(payload) > 1 else None
                    if pid in obd.SUPPORT_PIDS:
                        found = obd.supported_pids([payload])
                        supported |= found
                        supported_by_ecu.setdefault(address, set()).update(found)
                    elif pid in (0x01, 0x41) and (state := obd.readiness(payload)):
                        (readiness if pid == 0x01 else drive_readiness)[address] = state
                    else:
                        for value in obd.mode01_values(payload):
                            ecu_values.setdefault(address, {})[value["key"]] = value
                elif service == 0x06:
                    monitor_tests += [t | {"ecu": address} for t in obd.mode06_tests(payload)]
                elif service == 0x19 and command[2:4] == "04" and (snapshot := obd.uds_snapshot(payload)):
                    snapshots.append(snapshot | {"ecu": address})
                elif service == 0x21 and step.get("header"):
                    kwp.setdefault((int(step["header"], 16), 0x0100 | payload[1]), []).append(
                        (float(step.get("t_ms") or 0), payload[2:]))

        if service == 0x02:
            if command[2:4] == "02":
                freeze["dtc"] = freeze["dtc"] or obd.freeze_dtc(first[0])
            elif value := obd.freeze_value(first[0]):
                freeze["values"].append(value)
        elif service in (0x03, 0x07, 0x0A):
            kind = {0x03: "확정", 0x07: "대기", 0x0A: "영구"}[service]
            for ecu, payloads in outcome.positive.items():
                for code in obd.obd_dtcs(payloads, bus):
                    dtcs.append({"code": code, "kind": kind, "ecu": _ecu_address(ecu), "source": f"OBD {command}",
                                 "active": service == 0x03, "confirmed": service != 0x07})
        elif service == 0x09:
            info = command[2:4]
            if info == "02" and (vin := obd.vin_from(command, first)):
                vins.setdefault(vin, "OBD 09 02")
            elif info == "04":
                calids += [c for c in obd.calibration_ids(first) if c not in calids]
            elif info == "0A" and (name := obd.ecu_name(first)) and name not in ecu_names:
                ecu_names.append(name)
            elif info == "06":
                cvns += [c for c in obd.cvns(first) if c not in cvns]
            elif info in ("08", "0B"):
                iumpr = iumpr or obd.iumpr(info, first)
        elif command == "22F190":
            if vin := obd.vin_from(command, first):
                vins.setdefault(vin, f"{step.get('header')} 22 F190")
        elif service == 0x22 and command[2:] in obd.ODOMETER_DIDS and step.get("header"):
            for payloads in outcome.positive.values():
                if (km := obd.maker_odometer(command[2:], payloads[0][3:])) is not None:
                    odometers.setdefault((str(step["header"]).upper(), command[2:]), km)
        elif service == 0x22 and command[2:] in obd.ECU_IDENT_DIDS:
            field_name = obd.ECU_IDENT_DIDS[command[2:]][0]
            for ecu, payloads in outcome.positive.items():
                if text := obd.ecu_ident(payloads[0]):
                    ecus[_ecu_address(ecu)][field_name] = text
        elif service == 0x19 and command[2:4] in ("02", "15"):
            permanent = command[2:4] == "15"
            for ecu, payloads in outcome.positive.items():
                for payload in payloads:
                    for dtc in obd.uds_dtcs(payload):
                        kind = "영구" if permanent else (
                            "현재" if dtc["active"] else ("확정" if dtc["confirmed"] else "기록"))
                        dtcs.append(dtc | {"kind": kind, "ecu": _ecu_address(ecu),
                                           "source": f"UDS 19 {command[2:4]}"})

    trace = load_trace(record)
    model = obdb.match(car)
    battery = battery_values(trace, rules, kwp, model)
    cells = cell_voltages(trace, model)

    unique_dtcs = _merge_dtcs(dtcs)
    systems = {key: 0 for key in obd.SYSTEMS}
    for dtc in unique_dtcs:
        systems[dtc["system"]] += 1

    primary = _primary(supported_by_ecu | {a: supported_by_ecu.get(a, set()) for a in ecu_values})
    values = list(ecu_values.get(primary, {}).values())
    other_values = [{"ecu": a, "label": (ecus.get(a) or {}).get("label"), "values": list(v.values())}
                    for a, v in ecu_values.items() if a != primary and v]
    notes_extra: list[str] = []
    if odometers and not any(v["key"] == "odometer" for v in values):
        source = next((k for k in ODOMETER_SOURCES if k in odometers), None)
        cluster = next((k for k in ODOMETER_SOURCES[1:] if k in odometers), None)
        if source and source[1] == "1050" and cluster:
            bms, clu = odometers[source], odometers[cluster]
            if abs(bms - clu) > max(100, clu * ODOMETER_MISMATCH):
                notes_extra.append(f"실주행거리: 7E5 22 1050({bms:,} km)과 계기판 22 {cluster[1]}({clu:,} km)이 달라 "
                                   "계기판 값을 썼습니다. 실차 확인이 필요합니다.")
                source = cluster
        if source:
            values.append({"key": "odometer", "label": "누적 주행거리(실주행거리)", "unit": "km",
                           "value": odometers[source], "source": f"{source[0]} 22 {source[1]}",
                           "reference": True})
            notes_extra.append(f"누적 주행거리는 제조사 DID {source[0]} 22 {source[1]}의 미검증 해석입니다(표준 01 A6 없음).")
    monitor = None
    if readiness:
        main = readiness.get(primary) or next(iter(readiness.values()))
        monitor = {"mil": any(s["mil"] for s in readiness.values()),
                   "dtc_count": sum(s["dtc_count"] for s in readiness.values()),
                   "ignition": main["ignition"], "tests": main["tests"],
                   "drive_tests": (drive_readiness.get(primary) or next(iter(drive_readiness.values()), {})
                                   ).get("tests", [])}

    obd_rows = [r for r in rows if r["group"] not in ("device",)]
    errors = [r for r in rows if r["status"] not in INFO_STATUSES]
    answered = any(r["status"] == "ok" for r in obd_rows)
    status = "failed" if not answered else ("partial" if errors else "ok")
    notes = [DOIP_NOTE, *notes_extra]
    if bus == "serial":
        notes.append("K-Line·J1850 차량이라 UDS(CAN) 조회는 하지 않았습니다.")
    if any(v.get("reference") for v in battery.values()):
        notes.append("'참고 해석' 값은 공개 자료의 수식으로 읽은 미검증 값입니다. CAN 분석에서 검증하면 확정 값으로 바뀝니다.")
    if model and (cells or any(v.get("origin", "").startswith("OBDb") for v in battery.values())):
        notes.append(f"차종별 배터리 신호 정의: {obdb.ATTRIBUTION} ({model['repo']}).")

    return {
        "status": status,
        "protocol": protocol,
        "voltage": voltage,
        "vin": next(iter(vins), None),
        "vin_sources": vins,
        "monitor": monitor,
        "primary_ecu": primary,
        "values": values,
        "ecu_values": other_values,
        "dtcs": unique_dtcs,
        "systems": systems,
        "ecus": list(ecus.values()),
        "calibration_ids": calids,
        "cvns": cvns,
        "ecu_names": ecu_names,
        "freeze_frame": freeze if freeze["dtc"] or freeze["values"] else None,
        "monitor_tests": monitor_tests,
        "iumpr": iumpr,
        "snapshots": snapshots,
        "battery": battery,
        "cells": cells,
        "steps": rows,
        "errors": errors,
        "counts": {"total": len(rows), "ok": sum(r["status"] == "ok" for r in rows),
                   "unsupported": sum(r["status"] == "unsupported" for r in rows), "errors": len(errors)},
        "notes": notes,
    }, trace
