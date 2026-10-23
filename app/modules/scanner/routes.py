import json
from io import BytesIO

from flask import Blueprint, Response, current_app, render_template, request, send_file, url_for
from flask_login import current_user

from app.core import audit
from app.core.errors import ServiceError
from app.extensions import db, limiter
from app.modules.auth.access import admin_required
from app.modules.canlab.service import obd_config
from app.modules.scanner import analysis, clear_service, service
from app.modules.scanner import ai_verify as ai_verify_service
from app.modules.scanner.obd import SYSTEMS
from app.modules.scanner import ethernet
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
            "settingsUrl": url_for("admin.car_info_settings"),
            "aiVerifyUrlTemplate": url_for("scanner.ai_verify", scan_id=0).replace("/0/", "/{id}/")}


@bp.get("/")
@admin_required
def index():
    return render_template("scanner/index.html", obd=obd_config(), config=flow_config(),
                           car_no=(request.args.get("car_no") or "")[:20])


@bp.get("/ethernet")
@admin_required
def ethernet_page():
    """DoIP·J2534 읽기. CAN 스캔과 따로다."""
    return render_template("scanner/ethernet.html")


@bp.get("/ethernet/plan")
@admin_required
def ethernet_plan():
    return {"steps": ethernet.read_plan()}


@bp.post("/ethernet/run")
@admin_required
def ethernet_run():
    """로컬 망의 DoIP 게이트웨이로 읽기 단계를 진행하고 저장한다."""
    data = _body()

    def generate():
        try:
            host, port = ethernet.check_gateway(data.get("host"), data.get("port"))
            steps = None
            for event in ethernet.iter_doip(host, port):
                if event["type"] == "steps":
                    steps = event["steps"]
                else:
                    yield json.dumps(event, ensure_ascii=False) + "\n"
            if not steps:
                raise ServiceError("게이트웨이 응답이 없어 저장하지 않았습니다.")
            scan = service.run_scan(
                current_user, car_no=data.get("carNo"), car=data.get("car") if isinstance(data.get("car"), dict) else None,
                steps=steps, transport="doip", device=host)
        except ServiceError as exc:
            yield json.dumps({"type": "error", "message": exc.message}, ensure_ascii=False) + "\n"
            return
        except (TypeError, ValueError):
            yield json.dumps({"type": "error", "message": "게이트웨이 주소를 확인하세요."}, ensure_ascii=False) + "\n"
            return
        yield json.dumps({"type": "done", "url": url_for("scanner.result", scan_id=scan.id)}, ensure_ascii=False) + "\n"

    return Response(generate(), mimetype="application/x-ndjson")


@bp.post("/ethernet/j2534")
@admin_required
def ethernet_j2534():
    """J2534 장비가 남긴 읽기 기록을 같은 해석으로 저장한다."""
    data = _body()
    try:
        steps = ethernet.parse_j2534(data.get("log") or "")
        scan = service.run_scan(
            current_user, car_no=data.get("carNo"), car=data.get("car") if isinstance(data.get("car"), dict) else None,
            steps=steps, transport="j2534", device="J2534")
    except ServiceError as error:
        return {"message": error.message}, error.status
    return {"id": scan.id, "url": url_for("scanner.result", scan_id=scan.id)}, 201


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
    # 고장코드 지우기는 읽기 계획에 넣지 않는다(POST /admin/scan/<id>/clear-plan, scanner/clear.py).
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
                           systems=SYSTEMS, transports=service.TRANSPORTS,
                           step_groups=analysis.group_steps(result.get("steps")),
                           ai_verify=result.get("ai_verify") if isinstance(result.get("ai_verify"), dict) else None)


@bp.post("/<int:scan_id>/ai-verify")
@admin_required
@limiter.limit("20 per hour")
def ai_verify(scan_id: int):
    """실패·무응답 단계를 AI(또는 규칙)로 검증해 결과 JSON에 붙인다."""
    try:
        scan = get_visible_scan(current_user, scan_id)
        payload = ai_verify_service.verify_scan(current_user, scan)
    except ServiceError as error:
        db.session.rollback()
        return {"message": error.message}, error.status
    return payload, 200


@bp.get("/<int:scan_id>/pdf")
@admin_required
def pdf(scan_id: int):
    document = service.scan_document(get_visible_scan(current_user, scan_id))
    return send_file(BytesIO(document.content), mimetype="application/pdf", as_attachment=True,
                     download_name=document.filename, max_age=0)


@bp.post("/<int:scan_id>/clear-plan")
@admin_required
@limiter.limit("5 per hour")
def clear_plan(scan_id: int):
    """고장코드 지우기 계획(1회용). 확인 창의 차량번호·상태 확인이 필요하다."""
    data = _body()
    try:
        scan = get_visible_scan(current_user, scan_id)
        return clear_service.issue(current_user, scan, car_no=data.get("carNo"), conditions=data.get("conditions"),
                                   source="web")
    except ServiceError as error:
        db.session.rollback()
        return {"message": error.message}, error.status


@bp.post("/<int:scan_id>/clear")
@admin_required
@limiter.limit("5 per hour")
def clear_save(scan_id: int):
    data = _body()
    try:
        scan = get_visible_scan(current_user, scan_id)
        log = clear_service.save(current_user, scan, token=data.get("token"), steps=data.get("steps"))
    except ServiceError as error:
        db.session.rollback()
        return {"message": error.message}, error.status
    return {"id": log.id, "status": log.status, "result": log.result}, 201

