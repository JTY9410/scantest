"""스캔하기: 차량정보 조회 → 스캔 계획 → 단계별 응답 해석 → 기록·결과지·스캔 저장.

스캔이 실패해도(응답 없음, 연결 끊김, 해석 오류) 기록과 오류 목록을 저장해 원인을 볼 수 있게 한다.
"""

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from flask import current_app
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core import audit
from app.core.errors import ServiceError
from app.extensions import db
from app.modules.accounts.models import User
from app.modules.canlab.engine import signals
from app.modules.canlab.engine.decode import diagnose
from app.modules.canlab.models import CanDataset, DatasetKind, DatasetSource, DiagnosticReport, ScanLogic
from app.modules.canlab.service import _describe_dtcs, _trace_summary, active_logic, active_rule_refs
from app.modules.obd.models import ObdDialect
from app.modules.scanner import pdf
from app.modules.scanner.interpret import detect_protocol, interpret, record_text
from app.modules.scanner.obd import STATUS_LABELS, SYSTEMS
from app.modules.scanner.plan import DOIP_NOTE
from app.modules.scans import car_info
from app.modules.scans.models import Code, Scan, ScanCode, ScanDocument, ScanType

TRANSPORTS = {"ble": "블루투스(BLE)", "serial": "블루투스 클래식·USB(시리얼)", "wifi": "WiFi", "lte": "LTE 단말기"}
MAX_STEPS = 400
MAX_REPLY = 4000
_COMMAND = re.compile(r"^(AT[A-Z0-9 ]{1,12}|([0-9A-F]{2}){1,8})$")
_HEADER = re.compile(r"^[0-9A-F]{3}([0-9A-F]{5})?$")
_TEXT_FIELDS = {"group": 20, "label": 100, "reason": 200, "error": 200}


def _now() -> datetime:
    return datetime.now(UTC)


def lookup_car(actor: User, car_no: str | None, refresh: bool = False) -> dict[str, Any]:
    """조회 결과를 화면에 보여 줄 형태로. 실패하면 CarInfoError(guide에 안내 문구)."""
    dto, cached = car_info.lookup(actor, car_no, refresh=refresh)
    return {"car_no": car_info.normalize_car_no(car_no), "car": car_info.normalize_dto(dto), "cached": cached}


def clean_steps(raw: Any) -> list[dict]:
    """브라우저·앱·LTE 단말기가 보낸 단계 결과를 검사한다. 명령은 진단 명령 형식만 받는다."""
    if not isinstance(raw, list) or not raw:
        raise ServiceError("스캔 단계 결과가 없습니다.")
    if len(raw) > MAX_STEPS:
        raise ServiceError(f"스캔 단계는 {MAX_STEPS}개까지 받을 수 있습니다.")
    steps = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ServiceError(f"{index}번째 단계 형식이 올바르지 않습니다.")
        command = re.sub(r"\s+", "", str(item.get("command") or "")).upper()
        if command.startswith("AT"):
            command = str(item.get("command")).strip().upper()
        header = (str(item["header"]).strip().upper() if item.get("header") else None)
        if not _COMMAND.match(command) or (header and not _HEADER.match(header)):
            raise ServiceError(f"{index}번째 단계의 명령 또는 주소가 올바르지 않습니다.")
        reply = item.get("reply")
        step = {
            "id": int(item.get("id") or index), "command": command, "header": header,
            "reply": str(reply)[:MAX_REPLY] if reply is not None else None,
            "optional": bool(item.get("optional")), "probe": bool(item.get("probe")),
            "bus": "can" if item.get("bus") == "can" else None,
            "t_ms": float(item.get("tMs") or item.get("t_ms") or 0),
        }
        for key, limit in _TEXT_FIELDS.items():
            value = item.get(key)
            step[key] = str(value)[:limit] if value not in (None, "") else None
        steps.append(step)
    return steps


def _failed_result(steps: list[dict], message: str) -> dict:
    error = {"id": None, "group": "server", "label": "결과 해석", "header": None, "command": None,
             "status": "server_error", "status_label": STATUS_LABELS["server_error"], "message": message, "raw": ""}
    return {"status": "failed", "protocol": detect_protocol(steps), "voltage": None, "vin": None,
            "vin_sources": {}, "monitor": None, "values": [], "dtcs": [], "systems": {k: 0 for k in SYSTEMS},
            "ecus": [], "calibration_ids": [], "cvns": [], "ecu_names": [], "freeze_frame": None, "battery": {}, "steps": [error], "errors": [error],
            "counts": {"total": len(steps), "ok": 0, "unsupported": 0, "errors": 1}, "notes": [DOIP_NOTE]}


def _describe(dtcs: list[dict]) -> dict[str, Code]:
    """고장코드 마스터의 설명·원인·조치를 붙인다. 고장유형 바이트를 뺀 5자리로도 찾는다."""
    keys = {d["code"] for d in dtcs} | {d["code"][:5] for d in dtcs}
    if not keys:
        return {}
    found = {c.code: c for c in db.session.scalars(
        select(Code).where(Code.code.in_(keys), Code.deleted_at.is_(None)).order_by(Code.id))}
    matched = {}
    for dtc in dtcs:
        code = found.get(dtc["code"]) or found.get(dtc["code"][:5])
        dtc["desc"] = code.desc if code else None
        dtc["root_cause"] = code.root_cause if code else None
        dtc["howto"] = [h for h in (code.howto_fix1, code.howto_fix2, code.howto_fix3) if h] if code else []
        dtc["unit_name"] = code.unit_name if code else None
        if code:
            matched[dtc["code"]] = code
    return matched


def _add_error(result: dict, group: str, label: str, status: str, message: str, first: bool = False) -> None:
    error = {"id": None, "group": group, "label": label, "header": None, "command": None, "status": status,
             "status_label": STATUS_LABELS.get(status, status), "message": message[:300], "raw": ""}
    if first:
        result["errors"].insert(0, error)
    else:
        result["errors"].append(error)
    result["counts"]["errors"] += 1
    if result["status"] == "ok":
        result["status"] = "partial"


def _check_logic(result: dict, logic: ScanLogic | None) -> None:
    """적용 중 스캔 로직이 위스캔과 같은 결과를 내는지 점검해 문제를 '로직 문제'로 남긴다.
    로직 명령이 성공하지 않았거나, 로직 수식으로 값을 읽지 못했으면 문제다.
    로직 명령은 11비트 CAN 주소만 담으므로 11비트 CAN 차량에서만 점검한다."""
    if logic is None or result["status"] == "failed" or (result.get("protocol") or {}).get("bus") != "can11":
        return
    steps: dict[tuple[str | None, str], dict] = {}
    for step in result["steps"]:
        key = (step.get("header"), step.get("command"))
        if key not in steps or step.get("status") == "ok":
            steps[key] = step
    for command in logic.commands:
        header = None if command["header"] == "7DF" else command["header"]
        step = steps.get((header, command["command"]))
        if step is None:
            message = "스캔 계획에 이 명령이 없어 보내지 못했습니다."
        elif step.get("status") != "ok":
            message = f"{step.get('status_label') or step.get('status')}: {step.get('message') or '응답을 받지 못했습니다.'}"
        else:
            continue
        _add_logic_error(result, command.get("label") or f"{command['header']} {command['command']}",
                         command["header"], command["command"], message, step)
    active = {r.rule_id for r in active_rule_refs()}
    for rule in logic.rules:
        value = result["battery"].get(rule["signal_key"])
        if rule["rule_id"] not in active or (value and value.get("rule_id") == rule["rule_id"]):
            continue
        signal = signals.BY_KEY.get(rule["signal_key"])
        _add_logic_error(result, signal.label if signal else rule["signal_key"], None, None,
                         f"로직 수식(v{rule['revision']}: {rule['formula']})으로 값을 읽지 못했거나 물리 범위를 벗어났습니다.")
    result["scan_logic"] = {"id": logic.id, "revision": logic.revision}


def _add_logic_error(result: dict, label: str, header: str | None, command: str | None, message: str,
                     step: dict | None = None) -> None:
    _add_error(result, "logic", label, "logic_error", message)
    result["errors"][-1].update(id=(step or {}).get("id"), header=header, command=command,
                                raw=(step or {}).get("raw") or "")


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def run_scan(actor: User, *, car_no: str | None, car: dict | None, steps: Any, transport: str,
             device: str | None = None, lookup_error: str | None = None, client_error: str | None = None,
             source: str = DatasetSource.WEB, dialect: str | None = None) -> Scan:
    car_no = car_info.normalize_car_no(car_no)
    if not car_no:
        raise ServiceError("차량번호를 입력해주세요.")
    if transport not in TRANSPORTS:
        raise ServiceError("연결 방식을 확인하세요.")
    steps = clean_steps(steps)
    car = car_info.normalize_dto(car) if isinstance(car, dict) else {}
    device = (device or TRANSPORTS[transport]).strip()[:100]
    dialect = dialect if dialect in tuple(ObdDialect) else None
    vehicle = " ".join(str(car.get(k)) for k in ("diag_company", "diag_model", "diag_year") if car.get(k)) \
        or "차량 미확인"
    started = _now()

    protocol = detect_protocol(steps)
    record = record_text(steps, protocol["bus"], {"vehicle": vehicle, "device": device, "transport": transport,
                                                  "dialect": dialect, "started": started.isoformat()})
    trace = None
    try:
        result, trace = interpret(steps, active_rule_refs(), record, car)
    except Exception as exc:  # 해석 오류도 스캔 기록으로 남긴다
        current_app.logger.exception("스캔 결과 해석 실패")
        result = _failed_result(steps, f"결과를 해석하지 못했습니다({type(exc).__name__}). 통신 기록은 저장했습니다.")
    if lookup_error:
        _add_error(result, "lookup", "차량정보 조회", "lookup_error", str(lookup_error), first=True)
    if client_error:
        _add_error(result, "client", "스캔 진행", "client_error", str(client_error))
    _check_logic(result, active_logic())
    matched = _describe(result["dtcs"])
    if result["vin"] and car.get("diag_car_id"):
        result["vin_match"] = result["vin"] == str(car["diag_car_id"]).upper()

    content = record.encode()
    dataset = CanDataset(
        kind=DatasetKind.LIVE_CAPTURE, source=source, vehicle=vehicle[:100],
        filename=f"scan-{started:%Y%m%d-%H%M%S}.txt", sha256=hashlib.sha256(content).hexdigest(),
        size=len(content), content=content, summary=_trace_summary(trace) if trace else {},
        note=f"스캔하기 · {TRANSPORTS[transport]}", uploaded_by=actor.id,
    )
    db.session.add(dataset)
    db.session.flush()

    diagnosis = diagnose(trace) if trace else {"vin": None, "ecus": [], "dtcs": {}, "dtc_checked_ecus": [],
                                               "transaction_count": 0}
    _describe_dtcs(diagnosis)
    diagnosis["errors"] = result["errors"]
    diagnosis["obd"] = {k: v for k, v in result.items() if k not in ("battery", "vin", "vin_sources", "errors")}
    used = sorted({(v["rule_id"], v["rule_version"]) for v in result["battery"].values() if v.get("rule_id")})
    report = DiagnosticReport(
        dataset_id=dataset.id, vehicle=dataset.vehicle, values=result["battery"], diagnosis=diagnosis,
        rules_used=[{"rule_id": rid, "revision": rev} for rid, rev in used],
        created_by=actor.id, created_at=_now(),
    )
    db.session.add(report)
    db.session.flush()

    odometer = next((v["value"] for v in result["values"] if v["key"] == "odometer"), None)
    is_ev = "전기" in str(car.get("diag_fuel") or "") or any(k == "soc" for k in result["battery"])
    scan = Scan(
        type=ScanType.EV if is_ev else ScanType.ICE, device_type=transport, device_uid=device,
        tester_id=actor.id, company_id=actor.company_id, scan_vin=result["vin"], car_no=car_no,
        car_vin=str(car.get("diag_car_id") or result["vin"] or "미확인"), car_maker=car.get("diag_company"),
        car_model=str(car.get("diag_model") or "미확인"), car_submodel=car.get("diag_submodel"),
        car_cc=_int(car.get("diag_displacement")), car_year=_int(car.get("diag_year")),
        car_fuel=car.get("diag_fuel"), car_distance=int(odometer) if odometer is not None else None,
        raw=[d["code"] for d in result["dtcs"]],
        bms_data={
            "source": "scanner", "report_id": report.id, "dataset_id": dataset.id, "status": result["status"],
            "transport": transport, "device": device, "dialect": dialect, "car": car,
            "battery": {k: {"label": v["label"], "value": v["value"], "unit": v["unit"],
                            "reference": bool(v.get("reference")), "source": v.get("source"),
                            "origin": v.get("origin"), "range": v.get("range"), "outlier": bool(v.get("outlier"))}
                        for k, v in result["battery"].items()},
            **{k: v for k, v in result.items() if k != "battery"},
        },
    )
    db.session.add(scan)
    db.session.flush()
    for code in {c.id: c for c in matched.values()}.values():
        db.session.add(ScanCode(type=scan.type, scan_id=scan.id, code_id=code.id))
    document = _save_document(scan)
    if document is None:
        _add_error(result, "pdf", "결과 PDF", "pdf_error", "결과 PDF를 만들지 못했습니다. 결과 화면에서 다시 내려받으세요.")
        scan.bms_data.update(status=result["status"], errors=result["errors"], counts=result["counts"])
        flag_modified(scan, "bms_data")
    audit.record("스캔하기", "Scan", scan.id, user_id=actor.id,
                 changes={"status": result["status"], "transport": transport, "steps": len(steps),
                          "errors": result["counts"]["errors"], "dtcs": len(result["dtcs"]),
                          "report": report.id, "dataset": dataset.id, "pdf": document.size if document else None})
    db.session.commit()
    return scan


def _save_document(scan: Scan) -> ScanDocument | None:
    """결과 PDF를 만들어 스캔에 붙인다. 실패해도 스캔 저장은 계속한다."""
    try:
        content = pdf.render(scan, scan.bms_data)
    except Exception:
        current_app.logger.exception("스캔 결과 PDF 생성 실패")
        return None
    document = ScanDocument(scan_id=scan.id, filename=pdf.filename(scan), content=content, size=len(content),
                            sha256=hashlib.sha256(content).hexdigest())
    db.session.add(document)
    return document


def scan_document(scan: Scan) -> ScanDocument:
    """저장된 결과 PDF. 없으면(생성 실패, 이전 스캔) 지금 만든다."""
    scan_result(scan)
    document = db.session.scalar(select(ScanDocument).where(ScanDocument.scan_id == scan.id))
    if document is None:
        document = _save_document(scan)
        if document is None:
            raise ServiceError("결과 PDF를 만들지 못했습니다. 잠시 후 다시 시도하세요.", 500)
        db.session.commit()
    return document


def scan_result(scan: Scan) -> dict:
    """결과 화면용. 스캔하기로 만든 스캔만 위스캔 형식 결과가 있다."""
    data = scan.bms_data if isinstance(scan.bms_data, dict) else {}
    if data.get("source") != "scanner":
        raise ServiceError("스캔하기로 만든 결과가 아닙니다.", 404)
    return data
