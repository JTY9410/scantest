"""앱 스캔하기 API. 웹 스캔하기와 같은 서버 계획(build_plan)을 받아 실행하고 원응답을 올리면 서버가 해석한다."""

from flask import url_for

from app.modules.api import bp
from app.modules.api.auth import current_user, require_api_auth
from app.modules.api.http import api_input, respond
from app.modules.canlab.models import DatasetSource
from app.modules.scanner import service
from app.modules.scanner.plan import build_plan
from app.modules.scans import car_info
from app.modules.scans.car_info import CarInfoError


@bp.get("/scanPlan")
@require_api_auth
def scan_plan():
    car_no = api_input().get("car_no")
    try:
        found, lookup_error = service.lookup_car(current_user(), car_no), None
    except CarInfoError as error:
        if error.kind == "missing":
            raise
        found, lookup_error = {"car_no": car_info.normalize_car_no(car_no), "car": None}, error.guide
    return respond({"data": {"car_no": found["car_no"], "car": found["car"], "lookup_error": lookup_error,
                             **build_plan(found["car"], expand=True)}})


@bp.post("/scanRuns")
@require_api_auth
def scan_runs_store():
    data = api_input()
    car = data.get("car")
    scan = service.run_scan(
        current_user(), car_no=data.get("car_no"), car=car if isinstance(car, dict) else None,
        steps=data.get("steps"), transport=str(data.get("transport") or ""), device=data.get("device"),
        lookup_error=data.get("lookup_error"), client_error=data.get("client_error"), source=DatasetSource.APP,
    )
    return respond({"message": "생성되었습니다.", "data": {
        "id": scan.id, "status": scan.bms_data["status"], "errors": scan.bms_data["errors"],
        "pdf_url": url_for("api.scans_pdf", scan_id=scan.id, download=1),
    }}, 201)
