"""Laravel 모델 toArray()와 같은 필드를 snake_case로 만든다(응답 직전에 camelCase로 바뀐다)."""

from datetime import UTC
from decimal import Decimal
from typing import Any

from app.core.time import iso
from app.modules.accounts.models import Company, User
from app.modules.canlab.models import DiagnosticReport
from app.modules.obd.models import ObdDevice, ObdProfile
from app.modules.reports.models import Applog, CarMismatchReport
from app.modules.scans.models import Code, Scan, ScanCode


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _wants(requested: set[str], name: str) -> bool:
    return name in requested or any(r.startswith(name + ".") for r in requested)


def _nested(requested: set[str], name: str) -> set[str]:
    prefix = name + "."
    return {r[len(prefix) :] for r in requested if r.startswith(prefix)}


def user_dict(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "company_id": user.company_id,
        "type": user.type,
        "mobile": user.mobile,
        "biz_no": user.formatted_biz_no,
        "tid": user.tid,
        "name": user.name,
        "email": user.email,
        "email_verified_at": iso(user.email_verified_at),
        "token_version": user.token_version,
        "created_at": iso(user.created_at),
        "updated_at": iso(user.updated_at),
        "deleted_at": iso(user.deleted_at),
        "api_host": user.api_host,
        "api_expires_at": iso(user.api_expires_at),
    }


def company_dict(company: Company | None, requested: set[str] | None = None) -> dict | None:
    if company is None:
        return None
    return {
        "id": company.id,
        "code": company.code,
        "name": company.name,
        "created_at": iso(company.created_at),
        "updated_at": iso(company.updated_at),
        "deleted_at": iso(company.deleted_at),
    }


def code_dict(code: Code | None, requested: set[str] | None = None) -> dict | None:
    if code is None:
        return None
    return {
        "id": code.id,
        "type": code.type,
        "code": code.code,
        "unit_name": code.unit_name,
        "unit_type": code.unit_type,
        "desc": code.desc,
        "detail_desc": code.detail_desc,
        "root_cause": code.root_cause,
        "howto_fix1": code.howto_fix1,
        "howto_fix2": code.howto_fix2,
        "howto_fix3": code.howto_fix3,
        "created_at": iso(code.created_at),
        "updated_at": iso(code.updated_at),
        "deleted_at": iso(code.deleted_at),
    }


def scan_code_dict(item: ScanCode, requested: set[str]) -> dict[str, Any]:
    data = {
        "id": item.id,
        "type": item.type,
        "scan_id": item.scan_id,
        "code_id": item.code_id,
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
        "deleted_at": iso(item.deleted_at),
    }
    if "code" in requested:
        data["code"] = code_dict(item.code)
    return data


def scan_dict(scan: Scan, requested: set[str]) -> dict[str, Any]:
    data = {
        "id": scan.id,
        "type": scan.type,
        "device_type": scan.device_type,
        "device_uid": scan.device_uid,
        "owner_id": scan.owner_id,
        "tester_id": scan.tester_id,
        "company_id": scan.company_id,
        "scan_vin": scan.scan_vin,
        "car_no": scan.car_no,
        "car_vin": scan.car_vin,
        "car_maker": scan.car_maker,
        "car_model": scan.car_model,
        "car_submodel": scan.car_submodel,
        "car_cc": scan.car_cc,
        "car_year": scan.car_year,
        "car_fuel": scan.car_fuel,
        "car_distance": scan.car_distance,
        "car_battery_capacity": _decimal(scan.car_battery_capacity),
        "car_discharge_energy": _decimal(scan.car_discharge_energy),
        "car_charge_energy": _decimal(scan.car_charge_energy),
        "raw": scan.raw,
        "bms_data": scan.bms_data,
        "created_at": iso(scan.created_at),
        "updated_at": iso(scan.updated_at),
        "deleted_at": iso(scan.deleted_at),
    }
    if "owner" in requested:
        data["owner"] = user_dict(scan.owner)
    if "tester" in requested:
        data["tester"] = user_dict(scan.tester)
    if "company" in requested:
        data["company"] = company_dict(scan.company)
    if _wants(requested, "scan_codes"):
        nested = _nested(requested, "scan_codes")
        data["scan_codes"] = [scan_code_dict(sc, nested) for sc in scan.scan_codes]
    return data


def mismatch_dict(report: CarMismatchReport, requested: set[str]) -> dict[str, Any]:
    data = {
        "id": report.id,
        "user_id": report.user_id,
        "car_no": report.car_no,
        "api_vin": report.api_vin,
        "scan_vin": report.scan_vin,
        "created_at": iso(report.created_at),
        "updated_at": iso(report.updated_at),
        "deleted_at": iso(report.deleted_at),
    }
    if "user" in requested:
        data["user"] = user_dict(report.user)
    return data


def applog_dict(log: Applog, requested: set[str] | None = None) -> dict[str, Any]:
    return {
        "id": log.id,
        "timestamp": (
            log.timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f") if log.timestamp else None
        ),
        "user_id": log.user_id,
        "type": log.type,
        "message": log.message,
        "desc": log.desc,
        "created_at": iso(log.created_at),
        "updated_at": iso(log.updated_at),
    }


def can_capture_dict(report: DiagnosticReport) -> dict[str, Any]:
    dataset = report.dataset
    summary = dataset.summary
    return {
        "id": dataset.id,
        "kind": dataset.kind,
        "vehicle": dataset.vehicle,
        "transactions": summary["transactions"],
        "dids": summary["dids"],
        "vin": summary["vin"],
        "created_at": iso(dataset.created_at),
        "report": {
            "id": report.id,
            "values": {key: {"label": v["label"], "value": v["value"], "unit": v["unit"]}
                       for key, v in report.values.items()},
            "dtcs": [dict(d, ecu=ecu) for ecu, codes in report.diagnosis["dtcs"].items() for d in codes],
            "dtc_checked_ecus": report.diagnosis["dtc_checked_ecus"],
        },
    }


def obd_profile_dict(profile: ObdProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "name": profile.name,
        "transport": profile.transport,
        "device_name_prefix": profile.device_name_prefix,
        "service_uuid": profile.service_uuid,
        "write_uuid": profile.write_uuid,
        "notify_uuid": profile.notify_uuid,
        "init_commands": profile.init_commands,
        "request_header": profile.request_header,
        "response_header": profile.response_header,
        "read_commands": profile.read_commands,
        "response_timeout_ms": profile.response_timeout_ms,
        "dialect": profile.dialect,
        "can_bitrate": profile.can_bitrate,
        "updated_at": iso(profile.updated_at),
    }


def obd_device_dict(device: ObdDevice) -> dict[str, Any]:
    return {
        "id": device.id,
        "platform": device.platform,
        "transport": device.transport,
        "name": device.name,
        "dialect": device.dialect,
        "chip": device.chip,
        "version": device.version,
        "service_uuid": device.service_uuid,
        "write_uuid": device.write_uuid,
        "notify_uuid": device.notify_uuid,
        "protocol": device.protocol,
        "settings": device.settings,
        "last_connected_at": iso(device.last_connected_at),
    }
