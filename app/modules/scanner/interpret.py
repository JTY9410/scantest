"""스캔 결과 해석: 단계별 응답 → 위스캔 결과(차량 상태값, 고장코드, 배터리, 통신 정보, 오류)."""

import re
from typing import Any

from app.modules.canlab.engine import signals
from app.modules.canlab.engine.decode import Trace, decode_signals, load_trace
from app.modules.canlab.engine.frames import elm_from_exchanges
from app.modules.canlab.engine.search import Layout, load_references
from app.modules.scanner import obd
from app.modules.scanner.plan import DOIP_NOTE

# 지원하지 않아도 문제가 아닌 상태. 오류 목록이 아니라 '지원 안 함'으로 보여 준다.
INFO_STATUSES = {"ok", "unsupported", "skipped"}
BROADCAST = {"can11": "7DF", "can29": "18DB33F1"}
REFERENCE_CONFIDENCE = 0.5


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


def battery_values(trace: Trace, rules: list) -> dict[str, dict]:
    """적용 규칙으로 읽고, 규칙이 없는 신호는 공개 참고 해석으로 읽어 '미검증'으로 표시한다."""
    values = decode_signals(trace.samples, rules)
    for value in values.values():
        value["series"] = [list(p) for p in value["series"][-50:]]
    for item in load_references()["hypotheses"]:
        key = item["signal"]
        if key in values:
            continue
        layout = Layout.from_dict(item)
        rows = trace.samples.get((layout.request_id, layout.did))
        signal = signals.BY_KEY.get(key)
        if not rows or signal is None:
            continue
        value = layout.value(rows[-1][1])
        if value is None or not signal.minimum <= value <= signal.maximum:
            continue
        values[key] = {
            "value": value, "series": [[round(rows[-1][0], 1), value]], "label": signal.label,
            "unit": signal.unit, "rule_id": None, "rule_version": None, "confidence": REFERENCE_CONFIDENCE,
            "formula": layout.formula(), "source": f"{layout.request_id:03X} 22 {layout.did:04X}",
            "reference": True,
        }
    return values


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


def interpret(steps: list[dict], rules: list, record: str) -> tuple[dict[str, Any], Trace]:
    """steps: 계획 단계에 reply(응답 문자열), error(클라이언트 오류), t_ms를 붙인 목록.
    record: record_text로 만든 ELM 기록. 결과와 함께 다시 읽은 Trace를 돌려준다.
    """
    rows: list[dict] = []
    protocol = detect_protocol(steps)
    bus = protocol["bus"]

    voltage = None
    supported: set[int] = set()
    values: list[dict] = []
    monitor: dict | None = None
    dtcs: list[dict] = []
    vins: dict[str, str] = {}
    calids: list[str] = []
    ecu_names: list[str] = []
    ecus: dict[str, dict] = {}

    for step in steps:
        command = (step.get("command") or "").upper()
        error = step.get("error")
        if error == "skipped":
            rows.append(_row(step, "skipped", step.get("reason") or "앞 단계 결과에 따라 건너뛰었습니다."))
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
            address = f"{ecu:03X}" if ecu > 0xFF else f"{ecu:02X}"
            entry = ecus.setdefault(address, {"address": address, "request": step.get("header"),
                                              "label": None, "services": []})
            if step.get("header") and step.get("group") in ("uds", "maker"):
                entry["label"] = entry["label"] or (step.get("label") or "").split(" 차대번호")[0].split(" 고장코드")[0]
            if command[:2] not in entry["services"]:
                entry["services"].append(command[:2])

        first = next(iter(outcome.positive.values()))
        all_payloads = [p for ps in outcome.positive.values() for p in ps]
        if service == 0x01:
            pid = int(command[2:4], 16)
            if pid in obd.SUPPORT_PIDS:
                supported |= obd.supported_pids(all_payloads)
            elif pid == 0x01:
                states = [s for p in all_payloads if (s := obd.monitor_status(p))]
                if states:
                    monitor = {"mil": any(s["mil"] for s in states),
                               "dtc_count": sum(s["dtc_count"] for s in states)}
            elif value := obd.mode01(first[0]):
                values.append(value)
        elif service in (0x03, 0x07, 0x0A):
            kind = {0x03: "확정", 0x07: "대기", 0x0A: "영구"}[service]
            for ecu, payloads in outcome.positive.items():
                for code in obd.obd_dtcs(payloads, bus):
                    dtcs.append({"code": code, "kind": kind, "ecu": f"{ecu:03X}" if ecu > 0xFF else f"{ecu:02X}",
                                 "source": f"OBD {command}", "active": service == 0x03, "confirmed": service != 0x07})
        elif service == 0x09:
            info = command[2:4]
            if info == "02" and (vin := obd.vin_from(command, first)):
                vins.setdefault(vin, "OBD 09 02")
            elif info == "04":
                calids += [c for c in obd.calibration_ids(first) if c not in calids]
            elif info == "0A" and (name := obd.ecu_name(first)) and name not in ecu_names:
                ecu_names.append(name)
        elif command == "22F190":
            if vin := obd.vin_from(command, first):
                vins.setdefault(vin, f"{step.get('header')} 22 F190")
        elif service == 0x19:
            for ecu, payloads in outcome.positive.items():
                for payload in payloads:
                    for dtc in obd.uds_dtcs(payload):
                        dtcs.append(dtc | {"kind": "현재" if dtc["active"] else ("확정" if dtc["confirmed"] else "기록"),
                                           "ecu": step.get("header") or f"{ecu:03X}", "source": "UDS 19 02"})

    trace = load_trace(record)
    battery = battery_values(trace, rules)

    seen: set[tuple[str, str]] = set()
    unique_dtcs = []
    for dtc in dtcs:
        key = (dtc["code"][:5], dtc["ecu"])
        if key in seen:
            continue
        seen.add(key)
        unique_dtcs.append(dtc | {"system": obd.dtc_system(dtc["code"])})
    systems = {key: 0 for key in obd.SYSTEMS}
    for dtc in unique_dtcs:
        systems[dtc["system"]] += 1

    obd_rows = [r for r in rows if r["group"] not in ("device",)]
    errors = [r for r in rows if r["status"] not in INFO_STATUSES]
    answered = any(r["status"] == "ok" for r in obd_rows)
    status = "failed" if not answered else ("partial" if errors else "ok")
    notes = [DOIP_NOTE]
    if bus == "serial":
        notes.append("K-Line·J1850 차량이라 UDS(CAN) 조회는 하지 않았습니다.")
    if any(v.get("reference") for v in battery.values()):
        notes.append("'참고 해석' 값은 공개 자료의 수식으로 읽은 미검증 값입니다. CAN 분석에서 검증하면 확정 값으로 바뀝니다.")

    return {
        "status": status,
        "protocol": protocol,
        "voltage": voltage,
        "vin": next(iter(vins), None),
        "vin_sources": vins,
        "monitor": monitor,
        "values": values,
        "dtcs": unique_dtcs,
        "systems": systems,
        "ecus": list(ecus.values()),
        "calibration_ids": calids,
        "ecu_names": ecu_names,
        "battery": battery,
        "steps": rows,
        "errors": errors,
        "counts": {"total": len(rows), "ok": sum(r["status"] == "ok" for r in rows),
                   "unsupported": sum(r["status"] == "unsupported" for r in rows), "errors": len(errors)},
        "notes": notes,
    }, trace
