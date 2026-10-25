"""지식베이스 화면."""
from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.core.errors import ServiceError
from app.core.pagination import clamp_page, clamp_per_page
from app.modules.auth.access import admin_required
from app.modules.knowledge import alerts, importer, service

bp = Blueprint("knowledge", __name__, url_prefix="/admin/knowledge")


@bp.app_context_processor
def _command_alerts():
    """관리자 화면 상단 배너용 대기 알림 수. 로그인한 관리자에게만, 실패해도 화면은 그린다."""
    def command_alert_count() -> int:
        try:
            if not getattr(current_user, "is_authenticated", False) or not getattr(current_user, "is_admin", False):
                return 0
            return alerts.pending_count()
        except Exception:  # noqa: BLE001 — 배너 때문에 화면이 깨지면 안 된다
            return 0
    return {"command_alert_count": command_alert_count}

_STATUS = {"verified": "검증됨", "draft": "초안", "deprecated": "폐기됨"}


@bp.get("/")
@admin_required
def overview():
    """출처·상태별 지식 건수."""
    return render_template("knowledge/overview.html", inventory=service.inventory(), status_label=_STATUS)


@bp.get("/commands")
@admin_required
def commands():
    """List knowledge commands."""
    status = request.args.get("status", "all")
    maker = request.args.get("maker", "").strip()[:50] or None
    items = service.command_views(status=None if status == "all" else status, maker=maker)
    return render_template(
        "knowledge/commands.html", items=items, status=status, maker=maker or "",
        totals=service.status_totals("command", maker), deletion_alerts=alerts.pending_alerts())


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
    status = request.args.get("status", "all")
    maker = request.args.get("maker", "").strip()[:50] or None
    page = service.page_dtcs(
        status=None if status == "all" else status, maker=maker,
        page=clamp_page(request.args.get("page")),
        per_page=clamp_per_page(request.args.get("per_page"), 50))
    return render_template(
        "knowledge/dtcs.html", page=page, items=page.items, status=status, maker=maker or "",
        totals=service.status_totals("dtc", maker))


@bp.get("/terms")
@admin_required
def terms():
    """용어 목록. DoIP 안내 초안이 없으면 그때 넣는다."""
    status = request.args.get("status", "draft")
    service.ensure_lan_terms()
    from app.extensions import db
    db.session.commit()
    items = service.list_terms(status=status)
    return render_template("knowledge/terms.html", items=items, status=status)


def _save(action, redirect_to: str):
    try:
        action(request.form)
    except ServiceError as exc:
        flash(exc.message, "error")
    except ValueError:
        flash("항목을 찾지 못했습니다.", "error")
    else:
        flash("저장했습니다.", "success")
    return redirect(url_for(redirect_to, status=request.form.get("status") or "draft"))


@bp.post("/commands")
@admin_required
def save_command():
    """명령을 추가하거나 고친다."""
    return _save(service.save_command, "knowledge.commands")


@bp.post("/commands/alerts/<int:alert_id>/delete")
@admin_required
def alert_delete(alert_id: int):
    """삭제 여부 알림: 관리자가 삭제를 고른다."""
    try:
        alerts.resolve_delete(alert_id, current_user.id)
    except ServiceError as exc:
        flash(exc.message, "error")
    else:
        flash("알림의 명령을 삭제했습니다.", "success")
    return redirect(url_for("knowledge.commands"))


@bp.post("/commands/alerts/<int:alert_id>/keep")
@admin_required
def alert_keep(alert_id: int):
    """삭제 여부 알림: 관리자가 유지를 고른다."""
    try:
        alerts.resolve_keep(alert_id, current_user.id)
    except ServiceError as exc:
        flash(exc.message, "error")
    else:
        flash("명령을 유지합니다. 새 실패가 기준을 다시 넘으면 다시 알립니다.", "success")
    return redirect(url_for("knowledge.commands"))


@bp.post("/commands/<int:cmd_id>/delete")
@admin_required
def delete_command(cmd_id: int):
    """명령 한 건을 삭제한다."""
    try:
        service.delete_command(cmd_id)
    except ServiceError as exc:
        flash(exc.message, "error")
    else:
        flash("명령을 삭제했습니다.", "success")
    return redirect(url_for("knowledge.commands", status=request.args.get("status") or "draft"))


@bp.post("/dtcs")
@admin_required
def save_dtc():
    """고장코드 뜻을 추가하거나 고친다."""
    return _save(service.save_dtc, "knowledge.dtcs")


@bp.post("/dtcs/upload")
@admin_required
def upload_dtcs():
    """엑셀·PDF에서 고장코드를 읽어 초안으로 저장한다."""
    return _upload(request, "dtc", "knowledge.dtcs")


@bp.post("/commands/upload")
@admin_required
def upload_commands():
    """엑셀·PDF에서 읽기 명령을 읽어 초안으로 저장한다."""
    return _upload(request, "command", "knowledge.commands")


def _upload(req, kind: str, redirect_to: str):
    from app.modules.knowledge.uploads import import_command_file, import_dtc_file

    file = req.files.get("file")
    maker = (req.form.get("maker") or "").strip()[:50] or None
    if file is None or not file.filename:
        flash("파일을 선택하세요.", "error")
        return redirect(url_for(redirect_to))
    try:
        content = file.read()
        if kind == "dtc":
            stats = import_dtc_file(file.filename, content, maker)
            flash(f"고장코드 {stats['found']}건 중 {stats['saved']}건을 초안으로 저장했습니다.", "success")
        else:
            stats = import_command_file(file.filename, content, maker)
            flash(f"명령 {stats['found']}건 중 {stats['saved']}건을 초안으로 저장했습니다. "
                  f"세션·지우기 명령 {stats['skipped']}건은 넣지 않았습니다.", "success")
    except ServiceError as exc:
        flash(exc.message, "error")
    return redirect(url_for(redirect_to, status="all"))


@bp.post("/dtcs/<int:dtc_id>/delete")
@admin_required
def delete_dtc(dtc_id: int):
    """고장코드 뜻 한 건을 삭제한다."""
    try:
        service.delete_dtc(dtc_id)
    except ServiceError as exc:
        flash(exc.message, "error")
    else:
        flash("고장코드를 삭제했습니다.", "success")
    return redirect(url_for("knowledge.dtcs", status=request.args.get("status") or "draft"))


@bp.post("/dtcs/analyze")
@admin_required
def analyze_dtcs():
    """설명 없는 고장코드 초안을 AI로 분석한다."""
    try:
        stats = service.analyze_unknown_dtcs()
    except ServiceError as exc:
        flash(exc.message, "error")
    else:
        flash(f"공개 설명 {stats['described']}건, 추정 {stats['guessed']}건을 초안에 남겼습니다. "
              f"건너뜀 {stats['skipped']}건. 검증 전에는 스캔 설명에 쓰지 않습니다.", "success")
    return redirect(url_for("knowledge.dtcs", status="draft"))


@bp.post("/terms")
@admin_required
def save_term():
    """용어를 추가하거나 고친다."""
    return _save(service.save_term, "knowledge.terms")


@bp.post("/terms/<int:term_id>/delete")
@admin_required
def delete_term(term_id: int):
    """용어 한 건을 삭제한다."""
    try:
        service.delete_term(term_id)
    except ServiceError as exc:
        flash(exc.message, "error")
    else:
        flash("용어를 삭제했습니다.", "success")
    return redirect(url_for("knowledge.terms", status=request.args.get("status") or "draft"))


@bp.post("/commands/<int:cmd_id>/verify")
@admin_required
def verify_command(cmd_id: int):
    """명령을 검증한다."""
    try:
        service.verify_command(cmd_id, current_user.id)
    except ServiceError as exc:
        return jsonify({"error": exc.message}), exc.status
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
            return jsonify({"error": "로그 내용이 없습니다."}), 400
        
        try:
            if log_type == "elm":
                parsed = importer.parse_elm_log(content)
            elif log_type == "gscan":
                parsed = importer.parse_gscan_log(content)
            else:
                return jsonify({"error": "알 수 없는 로그 형식입니다."}), 400
            
            diff_result = importer.diff_against_known(parsed, maker=maker)
            
            return render_template("knowledge/import_result.html", 
                                   diff=diff_result, maker=maker, parsed_count=len(parsed))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    return render_template("knowledge/import.html")


@bp.post("/collect")
@admin_required
def collect():
    """공개 표준 명령·수식·고장코드 명칭을 모은다."""
    from app.modules.knowledge.collect import collect_public

    stats = collect_public()
    flash(f"공개 표준을 저장했습니다. 명령 {stats['commands']}건, 수식 {stats['formulas']}건, "
          f"고장코드 {stats['dtcs']}건, AI 명칭 {stats['ai']}건.", "success")
    return redirect(url_for("knowledge.dtcs"))


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
        return jsonify({"error": "파일이 없습니다."}), 400
    
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "파일 이름이 없습니다."}), 400
    
    try:
        data = file.read().decode("utf-8")
        parsed = jsonify(data).get_json()
        count = importer.import_knowledge_json(parsed)
        return jsonify({"status": "ok", "count": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/commands/<int:command_id>/promote", methods=["POST"])
@admin_required
def promote_command_route(command_id):
    """명령어 승격"""
    from app.modules.knowledge.service import promote_command
    from flask_login import current_user
    
    evidence = request.form.get("evidence", "")
    return_status = request.form.get("return_status", "experimental")
    
    if promote_command(command_id, current_user.id, evidence):
        flash("명령어가 verified 상태로 승격되었습니다.", "success")
    else:
        flash("승격 실패", "error")
    
    return redirect(url_for("knowledge.commands", status=return_status))


@bp.route("/commands/<int:command_id>/demote", methods=["POST"])
@admin_required
def demote_command_route(command_id):
    """명령어 강등"""
    from app.modules.knowledge.service import demote_command
    from flask_login import current_user
    
    reason = request.form.get("reason", "")
    return_status = request.form.get("return_status", "verified")
    
    if demote_command(command_id, current_user.id, reason):
        flash("명령어가 experimental 상태로 강등되었습니다.", "warning")
    else:
        flash("강등 실패", "error")
    
    return redirect(url_for("knowledge.commands", status=return_status))


@bp.route("/commands/bulk-promote", methods=["POST"])
@admin_required
def bulk_promote_commands():
    """명령어 일괄 승격"""
    from app.modules.knowledge.service import promote_command
    from flask_login import current_user
    
    ids = request.form.getlist("ids")
    evidence = request.form.get("evidence", "")
    
    success_count = 0
    for cmd_id in ids:
        try:
            if promote_command(int(cmd_id), current_user.id, evidence):
                success_count += 1
        except Exception:
            pass
    
    flash(f"{success_count}개 명령어가 승격되었습니다.", "success")
    return redirect(url_for("knowledge.commands", status="experimental"))


@bp.route("/formulas/<int:formula_id>/promote", methods=["POST"])
@admin_required
def promote_formula_route(formula_id):
    """수식 승격"""
    from app.modules.knowledge.service import promote_formula
    from flask_login import current_user
    
    evidence = request.form.get("evidence", "")
    return_status = request.form.get("return_status", "experimental")
    
    if promote_formula(formula_id, current_user.id, evidence):
        flash("수식이 verified 상태로 승격되었습니다.", "success")
    else:
        flash("승격 실패", "error")
    
    return redirect(url_for("knowledge.formulas", status=return_status))


@bp.route("/formulas/<int:formula_id>/demote", methods=["POST"])
@admin_required
def demote_formula_route(formula_id):
    """수식 강등"""
    from app.modules.knowledge.service import demote_formula
    from flask_login import current_user
    
    reason = request.form.get("reason", "")
    return_status = request.form.get("return_status", "verified")
    
    if demote_formula(formula_id, current_user.id, reason):
        flash("수식이 experimental 상태로 강등되었습니다.", "warning")
    else:
        flash("강등 실패", "error")
    
    return redirect(url_for("knowledge.formulas", status=return_status))


@bp.route("/formulas/bulk-promote", methods=["POST"])
@admin_required
def bulk_promote_formulas():
    """수식 일괄 승격"""
    from app.modules.knowledge.service import promote_formula
    from flask_login import current_user
    
    ids = request.form.getlist("ids")
    evidence = request.form.get("evidence", "")
    
    success_count = 0
    for formula_id in ids:
        try:
            if promote_formula(int(formula_id), current_user.id, evidence):
                success_count += 1
        except Exception:
            pass
    
    flash(f"{success_count}개 수식이 승격되었습니다.", "success")
    return redirect(url_for("knowledge.formulas", status="experimental"))
