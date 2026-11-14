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


@bp.post("/scan/<int:scan_id>/override-fields")
@admin_required
def override_scan_fields(scan_id: int):
    """Manually override scan classification fields (powertrain, fuel, maker, model, year, battery)."""
    from flask import jsonify, session
    from app.extensions import db
    from app.modules.definitions.audit_models import PowertrainOverrideAudit
    
    scan = service.get_scan(scan_id)
    data = request.json
    reason = data.get("reason", "").strip()
    user_id = session.get("user_id")
    
    changes = []
    
    # Powertrain
    if "powertrain" in data and data["powertrain"]:
        valid_powertrains = ["BEV", "PHEV", "HEV", "FCEV", "ICE", "not_vehicle", "unknown"]
        if data["powertrain"] not in valid_powertrains:
            return jsonify({"error": "Invalid powertrain value"}), 400
        if scan.type != data["powertrain"]:
            audit = PowertrainOverrideAudit(
                scan_id=scan_id, user_id=user_id,
                field_name="powertrain",
                previous_value=scan.type, new_value=data["powertrain"],
                previous_powertrain=scan.type, new_powertrain=data["powertrain"],
                previous_source=scan.type_source, new_source="manual_override",
                reason=reason or None
            )
            db.session.add(audit)
            scan.type = data["powertrain"]
            scan.type_source = "manual_override"
            scan.powertrain_conflict = False
            changes.append("powertrain")
    
    # Fuel
    if "fuel" in data and data["fuel"]:
        if scan.car_fuel != data["fuel"]:
            audit = PowertrainOverrideAudit(
                scan_id=scan_id, user_id=user_id,
                field_name="fuel",
                previous_value=scan.car_fuel, new_value=data["fuel"],
                new_source="manual_override",
                reason=reason or None
            )
            db.session.add(audit)
            scan.car_fuel = data["fuel"]
            changes.append("fuel")
    
    # Maker
    if "maker" in data and data["maker"]:
        if scan.car_maker != data["maker"]:
            audit = PowertrainOverrideAudit(
                scan_id=scan_id, user_id=user_id,
                field_name="maker",
                previous_value=scan.car_maker, new_value=data["maker"],
                new_source="manual_override",
                reason=reason or None
            )
            db.session.add(audit)
            scan.car_maker = data["maker"]
            changes.append("maker")
    
    # Model
    if "model" in data and data["model"]:
        if scan.car_model != data["model"]:
            audit = PowertrainOverrideAudit(
                scan_id=scan_id, user_id=user_id,
                field_name="model",
                previous_value=scan.car_model, new_value=data["model"],
                new_source="manual_override",
                reason=reason or None
            )
            db.session.add(audit)
            scan.car_model = data["model"]
            changes.append("model")
    
    # Year
    if "year" in data and data["year"]:
        try:
            year = int(data["year"])
            if scan.car_year != year:
                audit = PowertrainOverrideAudit(
                    scan_id=scan_id, user_id=user_id,
                    field_name="year",
                    previous_value=str(scan.car_year) if scan.car_year else None,
                    new_value=str(year),
                    new_source="manual_override",
                    reason=reason or None
                )
                db.session.add(audit)
                scan.car_year = year
                changes.append("year")
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid year value"}), 400
    
    # Battery spec
    if "battery_spec_id" in data and data["battery_spec_id"]:
        try:
            spec_id = int(data["battery_spec_id"])
            if scan.battery_spec_id != spec_id:
                audit = PowertrainOverrideAudit(
                    scan_id=scan_id, user_id=user_id,
                    field_name="battery_spec",
                    previous_value=str(scan.battery_spec_id) if scan.battery_spec_id else None,
                    new_value=str(spec_id),
                    new_source="manual_override",
                    reason=reason or None
                )
                db.session.add(audit)
                scan.battery_spec_id = spec_id
                changes.append("battery_spec")
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid battery spec ID"}), 400
    
    if not changes:
        return jsonify({"error": "No changes requested"}), 400
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "scan_id": scan_id,
        "changes": changes
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


@bp.get("/api/battery-specs/list")
def list_battery_specs():
    """List battery specs for dropdown, optionally filtered by maker/model."""
    from app.modules.battery.models import BatterySpec
    from sqlalchemy import or_
    
    maker = request.args.get("maker", "").strip()
    model = request.args.get("model", "").strip()
    
    stmt = select(BatterySpec).where(BatterySpec.is_active == True).order_by(
        BatterySpec.maker, BatterySpec.model, BatterySpec.model_year.desc()
    )
    
    if maker:
        stmt = stmt.where(BatterySpec.maker.ilike(f"%{maker}%"))
    if model:
        stmt = stmt.where(BatterySpec.model.ilike(f"%{model}%"))
    
    specs = list(db.session.scalars(stmt.limit(50)).all())
    
    return jsonify([{
        "id": s.id,
        "maker": s.maker,
        "model": s.model,
        "trim_grade": s.trim_grade,
        "model_year": s.model_year,
        "usable_kwh": float(s.usable_kwh) if s.usable_kwh else None,
        "gross_kwh": float(s.gross_kwh) if s.gross_kwh else None,
        "source_type": s.source_type,
        "source_url": s.source_url
    } for s in specs])


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
