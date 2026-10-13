from typing import Any

from flask import Blueprint, render_template, request

from app.core.pagination import clamp_page
from app.modules.auth.access import admin_required
from app.modules.monitoring import service
from app.modules.scans.models import ScanType

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
    page = service.search_scans(scan_type=scan_type, **params)
    return render_template(
        "monitoring/scans.html", page=page, params=params, scan_type=scan_type,
        types=list(ScanType), filters=_filters(params, type=scan_type),
        member=service.member_name(params["user_id"]),
    )


@bp.get("/scans/<int:scan_id>")
@admin_required
def scan_show(scan_id: int):
    return render_template("monitoring/scan_show.html", scan=service.get_scan(scan_id))


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
