from io import BytesIO

from flask import request, send_file
from sqlalchemy import select

from app.core.errors import ServiceError
from app.core.pagination import clamp_page, clamp_per_page, paginate
from app.core.validation import validate
from app.extensions import db
from app.modules.accounts.models import Company, User
from app.modules.api import bp
from app.modules.api.auth import current_user, require_api_auth
from app.modules.api.http import api_input, respond
from app.modules.api.listing import eager, list_payload, load_options, parse_with
from app.modules.api.serializers import (
    applog_dict,
    can_capture_dict,
    code_dict,
    mismatch_dict,
    obd_device_dict,
    obd_profile_dict,
    scan_dict,
)
from app.modules.canlab import service as canlab
from app.modules.obd import devices as obd_devices
from app.modules.obd import service as obd
from app.modules.reports import service as reports
from app.modules.reports.models import CarMismatchReport
from app.modules.scanner import service as scanner
from app.modules.scans import service as scans
from app.modules.scans.car_info import fetch_car_info
from app.modules.scans.models import Code, Scan, ScanCode

NOT_FOUND = "해당 항목을 찾을 수 없습니다."

# ---- 스캔 -------------------------------------------------------------------

SCAN_COLUMNS = {c.key for c in Scan.__table__.columns}
SCAN_RELATIONS = {
    "owner": eager(Scan.owner),
    "tester": eager(Scan.tester),
    "company": eager(Scan.company),
    "scan_codes": eager(Scan.scan_codes),
    "scan_codes.code": eager(Scan.scan_codes, ScanCode.code),
}
SCAN_DEFAULT_WITH = {"owner", "tester", "company", "scan_codes"}

_STR = ["string", ("max", 255)]
SCAN_STORE_RULES = {
    "type": ["required", "string", ("in", ["ev", "ice"])],
    "device_type": ["required", *_STR],
    "device_uid": ["required", *_STR],
    "owner_id": ["nullable", "integer", ("exists", User, "id")],
    "tester_id": ["required", "integer", ("exists", User, "id")],
    "company_id": ["nullable", "integer", ("exists", Company, "id")],
    "scan_vin": ["nullable", *_STR],
    "car_no": ["required", *_STR],
    "car_vin": ["required", *_STR],
    "car_maker": ["nullable", *_STR],
    "car_model": ["required", *_STR],
    "car_submodel": ["nullable", *_STR],
    "car_cc": ["nullable", "integer"],
    "car_year": ["nullable", "integer"],
    "car_fuel": ["nullable", *_STR],
    "car_distance": ["nullable", "integer"],
    "car_battery_capacity": ["nullable", "numeric"],
    "car_discharge_energy": ["nullable", "numeric"],
    "car_charge_energy": ["nullable", "numeric"],
    "raw": ["nullable", "array"],
    "bms_data": ["nullable", "json"],
}
_OPTIONAL_ON_UPDATE = {"car_maker", "car_submodel", "car_cc", "car_year", "car_fuel", "car_distance",
                       "car_battery_capacity", "car_discharge_energy", "car_charge_energy", "raw",
                       "bms_data"}
SCAN_UPDATE_RULES = {
    field: (
        rules
        if field in _OPTIONAL_ON_UPDATE
        else ["sometimes", "required", *[r for r in rules if r not in ("required", "nullable")]]
    )
    for field, rules in SCAN_STORE_RULES.items()
}


def _with_default_relations(scan_id: int, user: User) -> Scan:
    db.session.expire_all()
    return scans.get_visible_scan(user, scan_id, load_options(SCAN_DEFAULT_WITH, SCAN_RELATIONS))


@bp.get("/scans")
@require_api_auth
def scans_index():
    stmt = scans.visible_scans(current_user())
    return respond(list_payload(stmt, Scan, api_input(), SCAN_COLUMNS, SCAN_RELATIONS, scan_dict))


@bp.post("/scans")
@require_api_auth
def scans_store():
    data = validate(api_input(), SCAN_STORE_RULES)
    scan = scans.create_scan(current_user(), data)
    scan = _with_default_relations(scan.id, current_user())
    return respond({"message": "생성되었습니다.", "data": scan_dict(scan, SCAN_DEFAULT_WITH)}, 201)


@bp.get("/scans/<int:scan_id>")
@require_api_auth
def scans_show(scan_id: int):
    requested = parse_with(api_input().get("with"), SCAN_RELATIONS)
    scan = scans.get_visible_scan(
        current_user(), scan_id, load_options(requested, SCAN_RELATIONS)
    )
    return respond({"data": scan_dict(scan, requested)})


@bp.route("/scans/<int:scan_id>", methods=["PUT", "PATCH"])
@require_api_auth
def scans_update(scan_id: int):
    data = validate(api_input(), SCAN_UPDATE_RULES)
    scans.update_scan(current_user(), scan_id, data)
    scan = _with_default_relations(scan_id, current_user())
    return respond({"message": "수정되었습니다.", "data": scan_dict(scan, SCAN_DEFAULT_WITH)})


@bp.delete("/scans/<int:scan_id>")
@require_api_auth
def scans_destroy(scan_id: int):
    scans.delete_scan(current_user(), scan_id)
    return respond({"message": "삭제되었습니다."})


@bp.post("/scans/getCarInfo")
@require_api_auth
def scans_car_info():
    return respond({"data": fetch_car_info(current_user(), api_input().get("car_no"))})


@bp.post("/scans/<int:scan_id>/email")
@require_api_auth
def scans_email(scan_id: int):
    validate(api_input(), {"email": ["required", "email"]})
    scans.get_visible_scan(current_user(), scan_id)
    # 이메일 발송은 기존 서버에서도 미구현이었다. 앱 호환을 위해 같은 응답을 유지한다.
    return respond({"message": "이메일이 성공적으로 전송되었습니다. [테스트!]", "scan_id": str(scan_id)})


@bp.get("/scans/<int:scan_id>/pdf")
@require_api_auth
def scans_pdf(scan_id: int):
    scan = scans.get_visible_scan(current_user(), scan_id)
    if api_input().get("download"):
        document = scanner.scan_document(scan)
        return send_file(BytesIO(document.content), mimetype="application/pdf", as_attachment=True,
                         download_name=document.filename, max_age=0)
    # 기존 서버는 PDF를 만들지 않고 이 응답만 줬다. 앱 호환을 위해 download 없이는 같은 응답을 유지한다.
    return respond({"message": "PDF가 성공적으로 생성되었습니다. [테스트!]", "scan_id": str(scan_id)})


# ---- 진단 코드 ---------------------------------------------------------------

CODE_COLUMNS = {c.key for c in Code.__table__.columns}


@bp.get("/codes")
@require_api_auth
def codes_index():
    stmt = select(Code).where(Code.deleted_at.is_(None))
    return respond(list_payload(stmt, Code, api_input(), CODE_COLUMNS, {}, code_dict))


@bp.get("/codes/<int:code_id>")
@require_api_auth
def codes_show(code_id: int):
    code = db.session.scalar(select(Code).where(Code.id == code_id, Code.deleted_at.is_(None)))
    if code is None:
        raise ServiceError(NOT_FOUND, 404)
    return respond({"data": code_dict(code)})


# ---- 차량 불일치 신고 ----------------------------------------------------------

REPORT_COLUMNS = {c.key for c in CarMismatchReport.__table__.columns}
REPORT_RELATIONS = {"user": eager(CarMismatchReport.user)}


@bp.get("/carMismatchReports")
@require_api_auth
def reports_index():
    stmt = reports.visible_reports(current_user())
    return respond(
        list_payload(
            stmt, CarMismatchReport, api_input(), REPORT_COLUMNS, REPORT_RELATIONS, mismatch_dict
        )
    )


@bp.post("/carMismatchReports")
@require_api_auth
def reports_store():
    data = validate(
        api_input(),
        {
            "car_no": ["required", "string", ("max", 20)],
            "api_vin": ["required", "string", ("max", 17)],
            "scan_vin": ["required", "string", ("max", 17)],
        },
    )
    report = reports.create_report(current_user(), data)
    report = reports.get_report(current_user(), report.id, [REPORT_RELATIONS["user"]()])
    return respond({"message": "생성되었습니다.", "data": mismatch_dict(report, {"user"})}, 201)


@bp.get("/carMismatchReports/<int:report_id>")
@require_api_auth
def reports_show(report_id: int):
    requested = parse_with(api_input().get("with"), REPORT_RELATIONS)
    report = reports.get_report(
        current_user(), report_id, load_options(requested, REPORT_RELATIONS)
    )
    return respond({"data": mismatch_dict(report, requested)})


# ---- 앱 로그 ------------------------------------------------------------------


def _laravel_paginator(page, items: list) -> dict:
    base = request.base_url

    def url(number: int) -> str:
        return f"{base}?page={number}"

    window = range(max(1, page.page - 3), min(page.last_page, page.page + 3) + 1)
    links = [{"url": url(page.page - 1) if page.has_prev else None, "label": "&laquo; Previous",
              "active": False}]
    links += [{"url": url(n), "label": str(n), "active": n == page.page} for n in window]
    links.append({"url": url(page.page + 1) if page.has_next else None, "label": "Next &raquo;",
                  "active": False})
    return {
        "current_page": page.page,
        "data": items,
        "first_page_url": url(1),
        "from": page.first_index,
        "last_page": page.last_page,
        "last_page_url": url(page.last_page),
        "links": links,
        "next_page_url": url(page.page + 1) if page.has_next else None,
        "path": base,
        "per_page": page.per_page,
        "prev_page_url": url(page.page - 1) if page.has_prev else None,
        "to": page.last_index,
        "total": page.total,
    }


@bp.get("/applogs")
@require_api_auth
def applogs_index():
    params = api_input()
    stmt = reports.visible_applogs(current_user(), params)
    page = paginate(stmt, clamp_page(params.get("page")), clamp_per_page(params.get("per_page")))
    return respond(_laravel_paginator(page, [applog_dict(log) for log in page.items]))


@bp.post("/applogs")
@require_api_auth
def applogs_store():
    data = validate(
        api_input(),
        {
            "timestamp": ["required", "date"],
            "user_id": ["nullable", "integer", ("exists", User, "id")],
            "type": ["required", "string", ("max", 255)],
            "message": ["required", "string", ("max", 2000)],
            "desc": ["nullable", "string"],
        },
    )
    log = reports.create_applog(current_user(), data)
    return respond(applog_dict(log), 201)


@bp.get("/applogs/<int:log_id>")
@require_api_auth
def applogs_show(log_id: int):
    return respond(applog_dict(reports.get_applog(current_user(), log_id)))


# ---- 블루투스 OBD2 연결 프로필 (기존 서버에 없던 신규 API) ----------------------------

@bp.get("/obdProfiles")
@require_api_auth
def obd_profiles_index():
    return respond({"data": [obd_profile_dict(p) for p in obd.enabled_profiles()]})


# ---- 한 번 연결한 진단기 기억 (신규 API) -------------------------------------------------

@bp.get("/obdDevices")
@require_api_auth
def obd_devices_index():
    return respond({"data": [obd_device_dict(d) for d in obd_devices.list_for(current_user())]})


@bp.post("/obdDevices")
@require_api_auth
def obd_devices_store():
    device, created = obd_devices.remember(current_user(), "app", api_input())
    return respond({"message": "저장되었습니다.", "data": obd_device_dict(device)}, 201 if created else 200)


@bp.delete("/obdDevices/<int:device_id>")
@require_api_auth
def obd_devices_destroy(device_id: int):
    obd_devices.forget(current_user(), device_id)
    return respond({"message": "삭제되었습니다."})


# ---- CAN 수집 (신규 API) ------------------------------------------------------------

@bp.get("/canCaptureRequests")
@require_api_auth
def can_capture_requests():
    return respond({"data": canlab.capture_requests()})


@bp.post("/canCaptures")
@require_api_auth
def can_captures_store():
    data = validate(api_input(), {
        "vehicle": ["required", "string", ("max", 100)],
        "device_name": ["nullable", "string", ("max", 100)],
        "exchanges": ["required", "array"],
    })
    report = canlab.store_app_capture(current_user(), data["vehicle"], data["exchanges"],
                                      data.get("device_name"))
    return respond({"message": "생성되었습니다.", "data": can_capture_dict(report)}, 201)
