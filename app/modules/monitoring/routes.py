from typing import Any

from flask import Blueprint, render_template, request

from app.core.pagination import clamp_page
from app.modules.auth.access import admin_required
from app.modules.monitoring import service
from app.modules.scanner.learn import answered_commands, list_commands
from app.modules.scans.models import ScanType
# Import audit model to register with SQLAlchemy metadata
from app.modules.definitions.audit_models import PowertrainOverrideAudit  # noqa: F401

bp = Blueprint("monitoring", __name__, url_prefix="/admin")


def _common() -> dict[str, Any]:
    args = request.args
    try:
        user_id = int(args["user_id"]) if args.get("user_id") else None
    except ValueError:
        user_id = None
    return {
        "q": (args.get("q") or "").strip()[:100],
        "user_id": user_id,
        "start": service.parse_day(args.get("start")),
        "end": service.parse_day(args.get("end")),
        "page": clamp_page(args.get("page")),
    }


def _filters(params: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """페이지 이동 링크에 실을 현재 검색 조건(빈 값 제외)."""
    values = {
        "q": params["q"],
        "user_id": params.get("user_id"),
        "start": params["start"].isoformat() if params["start"] else None,
        "end": params["end"].isoformat() if params["end"] else None,
        **extra,
    }
    return {k: v for k, v in values.items() if v not in (None, "")}


@bp.get("/scans")
@admin_required
def scans():
    params = _common()
    scan_type = request.args.get("type", "")
    device = (request.args.get("device") or "").strip()[:100]
    maker = (request.args.get("maker") or "").strip()[:50]
    model = (request.args.get("model") or "").strip()[:50]
    role = request.args.get("role", "") if request.args.get("role") in ("tester", "owner") else ""
    conflict_filter = request.args.get("conflict") == "true"
    page = service.search_scans(
        scan_type=scan_type, device=device, maker=maker, model=model, role=role, conflict=conflict_filter, **params)
    conflict_count = service.conflict_count()
    return render_template(
        "monitoring/scans.html", page=page, params=params, scan_type=scan_type, device=device,
        maker=maker, model=model, role=role, conflict_filter=conflict_filter, conflict_count=conflict_count,
        types=list(ScanType), type_counts=service.scan_type_counts(),
        filters=_filters(params, type=scan_type, device=device, maker=maker, model=model, role=role, conflict=conflict_filter if conflict_filter else None),
        member=service.member_name(params["user_id"]),
    )


@bp.get("/scans/commands")
@admin_required
def scan_commands():
    maker = (request.args.get("maker") or "").strip()[:50]
    return render_template("monitoring/scan_commands.html", maker=maker, commands=list_commands(maker))


@bp.get("/scans/<int:scan_id>")
@admin_required
def scan_show(scan_id: int):
    scan = service.get_scan(scan_id)
    data = scan.bms_data if isinstance(scan.bms_data, dict) else {}
    clear_logs = service.get_scan_clear_logs(scan_id)
    audit_logs = service.get_powertrain_audit_logs(scan_id=scan_id)
    return render_template("monitoring/scan_show.html", scan=scan, answered=answered_commands(data.get("steps")),
                          clear_logs=clear_logs, powertrain_audit_logs=audit_logs)


@bp.post("/scan/<int:scan_id>/override-powertrain")
@admin_required
def override_scan_powertrain(scan_id: int):
    """Manually override scan powertrain classification."""
    from flask import jsonify, session
    from app.extensions import db
    from app.modules.definitions.audit_models import PowertrainOverrideAudit
    
    scan = service.get_scan(scan_id)
    
    new_powertrain = request.json.get("powertrain")
    reason = request.json.get("reason", "").strip()
    
    # Validate powertrain value
    valid_powertrains = ["BEV", "PHEV", "HEV", "FCEV", "ICE", "not_vehicle", "unknown"]
    if new_powertrain not in valid_powertrains:
        return jsonify({"error": "Invalid powertrain value"}), 400
    
    # Record audit
    audit = PowertrainOverrideAudit(
        scan_id=scan_id,
        user_id=session.get("user_id"),
        previous_powertrain=scan.type,
        new_powertrain=new_powertrain,
        previous_source=scan.type_source,
        new_source="manual_override",
        reason=reason or None
    )
    db.session.add(audit)
    
    # Update scan
    scan.type = new_powertrain
    scan.type_source = "manual_override"
    scan.powertrain_conflict = False  # Resolved by manual override
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "scan_id": scan_id,
        "new_powertrain": new_powertrain,
        "audit_id": audit.id
    })


@bp.post("/scan/<int:scan_id>/revert-powertrain")
@admin_required
def revert_scan_powertrain(scan_id: int):
    """Revert scan powertrain to automatic classification."""
    from flask import jsonify, session
    from app.extensions import db
    from app.modules.definitions.audit_models import PowertrainOverrideAudit
    from app.modules.definitions.vehicle_classifier import classify_vehicle_powertrain
    
    scan = service.get_scan(scan_id)
    
    # Reclassify automatically
    pt, pt_source, pt_conf, conflict_info = classify_vehicle_powertrain(
        maker=scan.car_maker,
        model=scan.car_model,
        submodel=scan.car_submodel,
        file_path=None,
        vin=scan.car_vin,
        plate_number=scan.car_no,
        has_bms_commands=bool(scan.bms_data and scan.bms_data.get("battery")),
        diag_fuel=scan.car_fuel
    )
    
    # Record audit
    audit = PowertrainOverrideAudit(
        scan_id=scan_id,
        user_id=session.get("user_id"),
        previous_powertrain=scan.type,
        new_powertrain=pt,
        previous_source=scan.type_source,
        new_source=f"auto_revert:{pt_source}",
        reason="Reverted to automatic classification"
    )
    db.session.add(audit)
    
    # Update scan
    scan.type = pt
    scan.type_source = pt_source
    has_conflict = conflict_info and conflict_info.get("has_conflict", False)
    scan.powertrain_conflict = has_conflict
    scan.plate_powertrain = conflict_info.get("plate_powertrain") if conflict_info else None
    scan.vin_powertrain = conflict_info.get("vin_powertrain") if conflict_info else None
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "scan_id": scan_id,
        "new_powertrain": pt,
        "new_source": pt_source,
        "audit_id": audit.id
    })


@bp.get("/activities")
@admin_required
def activities():
    params = _common()
    params.pop("user_id")
    relation = request.args.get("relation", "")
    page = service.search_activities(relation=relation, **params)
    return render_template(
        "monitoring/activities.html", page=page, params=params, relation=relation,
        relations=service.activity_relations(), filters=_filters(params, relation=relation),
    )


@bp.get("/applogs")
@admin_required
def applogs():
    params = _common()
    log_type = request.args.get("type", "")
    page = service.search_applogs(log_type=log_type, **params)
    return render_template(
        "monitoring/applogs.html", page=page, params=params, log_type=log_type,
        types=service.applog_types(), filters=_filters(params, type=log_type),
        member=service.member_name(params["user_id"]),
    )


@bp.get("/reports")
@admin_required
def reports():
    params = _common()
    page = service.search_reports(**params)
    return render_template(
        "monitoring/reports.html", page=page, params=params, filters=_filters(params),
        member=service.member_name(params["user_id"]),
    )
