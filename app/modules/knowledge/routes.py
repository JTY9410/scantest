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


@bp.route("/import", methods=["GET", "POST"])
@admin_required
def import_logs():
    """Import and analyze logs."""
    if request.method == "POST":
        log_type = request.form.get("log_type", "elm")
        content = request.form.get("content", "")
        maker = request.form.get("maker", "").strip()[:50] or None
        
        if not content:
            return jsonify({"error": "No content provided"}), 400
        
        try:
            if log_type == "elm":
                parsed = importer.parse_elm_log(content)
            elif log_type == "gscan":
                parsed = importer.parse_gscan_log(content)
            else:
                return jsonify({"error": "Unknown log type"}), 400
            
            diff_result = importer.diff_against_known(parsed, maker=maker)
            
            return render_template("knowledge/import_result.html", 
                                   diff=diff_result, maker=maker, parsed_count=len(parsed))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    return render_template("knowledge/import.html")


@bp.post("/seed")
@admin_required
def seed_standard():
    """Seed standard OBD2 data."""
    count = importer.seed_standard_obd2()
    return jsonify({"status": "ok", "count": count})


@bp.get("/export")
@admin_required
def export_json():
    """Export knowledge as JSON."""
    data = importer.export_knowledge_json()
    return Response(
        jsonify(data).get_data(as_text=True),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=knowledge_export_{data['exported_at'][:10]}.json"}
    )


@bp.post("/import-json")
@admin_required
def import_json():
    """Import knowledge from JSON."""
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400
    
    try:
        data = file.read().decode("utf-8")
        parsed = jsonify(data).get_json()
        count = importer.import_knowledge_json(parsed)
        return jsonify({"status": "ok", "count": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
