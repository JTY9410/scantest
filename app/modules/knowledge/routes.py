"""Knowledge base routes."""
from flask import Blueprint, Response, jsonify, render_template, request
from flask_login import current_user

from app.core.errors import ServiceError
from app.modules.auth.access import admin_required
from app.modules.knowledge import importer, service

bp = Blueprint("knowledge", __name__, url_prefix="/admin/knowledge")


@bp.get("/commands")
@admin_required
def commands():
    """List knowledge commands."""
    status = request.args.get("status", "verified")
    maker = request.args.get("maker", "").strip()[:50] or None
    items = service.list_commands(status=status, maker=maker)
    return render_template("knowledge/commands.html", items=items, status=status, maker=maker or "")


@bp.get("/formulas")
@admin_required
def formulas():
    """List decode formulas."""
    status = request.args.get("status", "verified")
    maker = request.args.get("maker", "").strip()[:50] or None
    items = service.list_formulas(status=status, maker=maker)
    return render_template("knowledge/formulas.html", items=items, status=status, maker=maker or "")


@bp.get("/dtcs")
@admin_required
def dtcs():
    """List DTC meanings."""
    status = request.args.get("status", "verified")
    maker = request.args.get("maker", "").strip()[:50] or None
    items = service.list_dtcs(status=status, maker=maker)
    return render_template("knowledge/dtcs.html", items=items, status=status, maker=maker or "")


@bp.get("/terms")
@admin_required
def terms():
    """List glossary terms."""
    status = request.args.get("status", "verified")
    items = service.list_terms(status=status)
    return render_template("knowledge/terms.html", items=items, status=status)


@bp.post("/commands/<int:cmd_id>/verify")
@admin_required
def verify_command(cmd_id: int):
    """Verify a command."""
    service.verify_command(cmd_id, current_user.id)
    return jsonify({"status": "ok"})


@bp.post("/formulas/<int:formula_id>/verify")
@admin_required
def verify_formula(formula_id: int):
    """Verify a formula."""
    service.verify_formula(formula_id, current_user.id)
    return jsonify({"status": "ok"})


@bp.post("/dtcs/<int:dtc_id>/verify")
@admin_required
def verify_dtc(dtc_id: int):
    """Verify a DTC."""
    service.verify_dtc(dtc_id, current_user.id)
    return jsonify({"status": "ok"})
