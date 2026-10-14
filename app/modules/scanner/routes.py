from io import BytesIO

from flask import Blueprint, render_template, request, send_file, url_for
from flask_login import current_user

from app.core import audit
from app.core.errors import ServiceError
from app.extensions import db
from app.modules.auth.access import admin_required
from app.modules.canlab.service import obd_config
from app.modules.scanner import analysis, service
from app.modules.scanner.obd import SYSTEMS
from app.modules.scanner.plan import build_plan
from app.modules.scans import car_info
from app.modules.scans.car_info import CarInfoError
from app.modules.scans.service import get_visible_scan

bp = Blueprint("scanner", __name__, url_prefix="/admin/scan")


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def flow_config() -> dict:
    """스캔 흐름(스캔하기 화면, 대시보드 카드)이 쓰는 주소와 차량정보 조회 설정 여부."""
    return {"lookupUrl": url_for("scanner.lookup"), "planUrl": url_for("scanner.plan"),
            "runUrl": url_for("scanner.run"), "keyMissing": not car_info.configured(),
            "settingsUrl": url_for("admin.car_info_settings")}


@bp.get("/")
@admin_required
def index():
    return render_template("scanner/index.html", obd=obd_config(), config=flow_config(),
                           car_no=(request.args.get("car_no") or "")[:20])


@bp.post("/lookup")
@admin_required
def lookup():
    data = _body()
    try:
        return service.lookup_car(current_user, data.get("carNo"), refresh=bool(data.get("refresh")))
    except CarInfoError as error:
        db.session.rollback()
        audit.record("차량정보 조회 실패", "Scan", user_id=current_user.id,
                     changes={"car_no": car_info.normalize_car_no(data.get("carNo")), "kind": error.kind,
                              "status": error.status, "message": error.message[:300]})
        db.session.commit()
        return {"message": error.guide, "kind": error.kind, "detail": error.message}, error.status
    except ServiceError as error:
        return {"message": error.message}, error.status


@bp.post("/plan")
@admin_required
def plan():
    car = _body().get("car")
    return build_plan(car if isinstance(car, dict) else None, expand=True)


@bp.post("/run")
@admin_required
def run():
    data = _body()
    car = data.get("car")
    try:
        scan = service.run_scan(
            current_user, car_no=data.get("carNo"), car=car if isinstance(car, dict) else None,
            steps=data.get("steps"), transport=str(data.get("transport") or ""),
            device=data.get("device"), lookup_error=data.get("lookupError"),
            client_error=data.get("clientError"), dialect=data.get("dialect"),
        )
    except ServiceError as error:
        return {"message": error.message}, error.status
    return {"id": scan.id, "status": scan.bms_data["status"],
            "url": url_for("scanner.result", scan_id=scan.id)}, 201


@bp.get("/<int:scan_id>")
@admin_required
def result(scan_id: int):
    scan = get_visible_scan(current_user, scan_id)
    result = service.scan_result(scan)
    return render_template("scanner/result.html", scan=scan, result=result, summary=analysis.summarize(result),
                           systems=SYSTEMS, transports=service.TRANSPORTS)


@bp.get("/<int:scan_id>/pdf")
@admin_required
def pdf(scan_id: int):
    document = service.scan_document(get_visible_scan(current_user, scan_id))
    return send_file(BytesIO(document.content), mimetype="application/pdf", as_attachment=True,
                     download_name=document.filename, max_age=0)
