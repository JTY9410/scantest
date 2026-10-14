from flask import Blueprint, render_template, request, url_for
from flask_login import current_user

from app.core.errors import ServiceError
from app.modules.auth.access import admin_required
from app.modules.canlab.service import obd_config
from app.modules.scanner import service
from app.modules.scanner.obd import SYSTEMS
from app.modules.scanner.plan import build_plan
from app.modules.scans.car_info import CarInfoError
from app.modules.scans.service import get_visible_scan

bp = Blueprint("scanner", __name__, url_prefix="/admin/scan")


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.get("/")
@admin_required
def index():
    config = {"lookupUrl": url_for("scanner.lookup"), "planUrl": url_for("scanner.plan"),
              "runUrl": url_for("scanner.run")}
    return render_template("scanner/index.html", obd=obd_config(), config=config,
                           car_no=(request.args.get("car_no") or "")[:20])


@bp.post("/lookup")
@admin_required
def lookup():
    data = _body()
    try:
        return service.lookup_car(current_user, data.get("carNo"), refresh=bool(data.get("refresh")))
    except CarInfoError as error:
        return {"message": error.guide, "kind": error.kind, "detail": error.message}, error.status
    except ServiceError as error:
        return {"message": error.message}, error.status


@bp.post("/plan")
@admin_required
def plan():
    car = _body().get("car")
    return build_plan(car if isinstance(car, dict) else None)


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
        )
    except ServiceError as error:
        return {"message": error.message}, error.status
    return {"id": scan.id, "status": scan.bms_data["status"],
            "url": url_for("scanner.result", scan_id=scan.id)}, 201


@bp.get("/<int:scan_id>")
@admin_required
def result(scan_id: int):
    scan = get_visible_scan(current_user, scan_id)
    return render_template("scanner/result.html", scan=scan, result=service.scan_result(scan), systems=SYSTEMS,
                           transports=service.TRANSPORTS)
