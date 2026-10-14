from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.core.errors import ServiceError
from app.modules.auth.access import admin_required
from app.modules.canlab import service
from app.modules.canlab.engine import signals
from app.modules.canlab.forms import ActionForm, AnalysisForm, ReportForm, TruthTextForm, UploadForm
from app.modules.canlab.models import DatasetKind, DatasetSource, RuleStatus
from app.modules.obd.service import list_profiles

bp = Blueprint("canlab", __name__, url_prefix="/admin/canlab")


def _flash_error(error: ServiceError) -> int:
    flash(error.message, "error")
    return error.status


@bp.get("/")
@admin_required
def index():
    return render_template("canlab/index.html", stats=service.overview(), runs=service.list_runs()[:5])


@bp.route("/datasets", methods=["GET", "POST"])
@admin_required
def datasets():
    form = UploadForm()
    status = 200
    if form.validate_on_submit():
        upload = form.file.data
        try:
            dataset = service.upload_dataset(
                current_user, filename=upload.filename or "upload", content=upload.read(),
                kind=form.kind.data, vehicle=form.vehicle.data, note=form.note.data,
            )
        except ServiceError as error:
            status = _flash_error(error)
        else:
            flash("데이터를 등록했습니다.", "success")
            return redirect(url_for("canlab.dataset", dataset_id=dataset.id))
    elif request.method == "POST":
        status = 400
    return render_template("canlab/datasets.html", form=form, datasets=service.list_datasets()), status


@bp.get("/datasets/<int:dataset_id>")
@admin_required
def dataset(dataset_id: int):
    item = service.get_dataset(dataset_id)
    return render_template("canlab/dataset.html", dataset=item, truth_form=TruthTextForm(),
                           action=ActionForm(), signals=signals.SIGNALS,
                           ai_ready=service.ai.available_connection() is not None)


@bp.get("/datasets/<int:dataset_id>/pages/<int:page>.jpg")
@admin_required
def page_image(dataset_id: int, page: int):
    mime, data = service.page_image(service.get_dataset(dataset_id), page)
    return Response(data, mimetype=mime, headers={"Cache-Control": "private, max-age=600"})


@bp.post("/datasets/<int:dataset_id>/pages/<int:page>/ocr")
@admin_required
def ocr(dataset_id: int, page: int):
    if ActionForm().validate_on_submit():
        try:
            count = service.ocr_page(current_user, service.get_dataset(dataset_id), page)
        except ServiceError as error:
            _flash_error(error)
        else:
            flash(f"{page}쪽에서 {count}개 값을 읽었습니다. 확인 후 체크하세요.", "success")
    return redirect(url_for("canlab.dataset", dataset_id=dataset_id, _anchor="truths"))


@bp.post("/datasets/<int:dataset_id>/truths/add")
@admin_required
def add_truths(dataset_id: int):
    form = TruthTextForm()
    if form.validate_on_submit():
        try:
            count = service.add_truths(current_user, service.get_dataset(dataset_id), form.text.data)
        except ServiceError as error:
            _flash_error(error)
        else:
            flash(f"정답값 {count}개를 넣었습니다.", "success")
    else:
        flash("입력할 값을 붙여 넣으세요.", "error")
    return redirect(url_for("canlab.dataset", dataset_id=dataset_id, _anchor="truths"))


@bp.post("/datasets/<int:dataset_id>/truths")
@admin_required
def update_truths(dataset_id: int):
    if ActionForm().validate_on_submit():
        item = service.get_dataset(dataset_id)
        rows = {
            truth.id: {
                "value": request.form.get(f"value-{truth.id}", truth.value_text),
                "signal_key": request.form.get(f"key-{truth.id}", ""),
                "confirmed": request.form.get(f"confirmed-{truth.id}") == "on",
                "delete": request.form.get(f"delete-{truth.id}") == "on",
            }
            for truth in item.truths
        }
        try:
            service.update_truths(current_user, item, rows)
        except ServiceError as error:
            _flash_error(error)
        else:
            flash("정답값을 저장했습니다.", "success")
    return redirect(url_for("canlab.dataset", dataset_id=dataset_id, _anchor="truths"))


@bp.post("/datasets/<int:dataset_id>/delete")
@admin_required
def delete_dataset(dataset_id: int):
    if ActionForm().validate_on_submit():
        service.delete_dataset(current_user, service.get_dataset(dataset_id))
        flash("데이터를 삭제했습니다.", "success")
    return redirect(url_for("canlab.datasets"))


def _dataset_choice(d) -> tuple[int, str]:
    return d.id, f"#{d.id} {d.vehicle} · {d.filename} ({d.kind_label})"


@bp.route("/analysis", methods=["GET", "POST"])
@admin_required
def analysis():
    form = AnalysisForm()
    form.trace_ids.choices = [_dataset_choice(d) for d in service.trace_datasets()]
    form.truth_dataset_id.choices = [_dataset_choice(d) for d in service.truth_datasets()]
    status = 200
    if form.validate_on_submit():
        try:
            run = service.run_analysis(current_user, form.trace_ids.data, form.truth_dataset_id.data,
                                       apply=form.apply.data)
        except ServiceError as error:
            status = _flash_error(error)
        else:
            flash(f"분석을 마쳤습니다. 새로 적용한 규칙 {run.activated_count}개." if form.apply.data
                  else "검증만 했습니다. 규칙은 바꾸지 않았습니다.", "success")
            return redirect(url_for("canlab.run", run_id=run.id))
    elif request.method == "POST":
        status = 400
    return render_template("canlab/analysis.html", form=form, runs=service.list_runs()), status


@bp.get("/analysis/<int:run_id>")
@admin_required
def run(run_id: int):
    return render_template("canlab/run.html", run=service.get_run(run_id))


@bp.get("/rules")
@admin_required
def rules():
    return render_template("canlab/rules.html", groups=service.list_rules(), signals=signals.BY_KEY,
                           action=ActionForm(), RuleStatus=RuleStatus)


def _rule_action(rule_id: int, change, done: str):
    form = ActionForm()
    status = 200
    if form.validate_on_submit():
        try:
            change(current_user, service.get_rule(rule_id), int(form.version.data or 0))
        except ServiceError as error:
            status = _flash_error(error)
        else:
            flash(done, "success")
    if status != 200:
        return render_template("canlab/rules.html", groups=service.list_rules(), signals=signals.BY_KEY,
                               action=ActionForm(), RuleStatus=RuleStatus), status
    return redirect(url_for("canlab.rules"))


@bp.post("/rules/<int:rule_id>/activate")
@admin_required
def activate_rule(rule_id: int):
    return _rule_action(rule_id, service.activate_rule, "규칙을 적용했습니다. 운영 결과지에 바로 반영됩니다.")


@bp.post("/rules/<int:rule_id>/retire")
@admin_required
def retire_rule(rule_id: int):
    return _rule_action(rule_id, service.retire_rule, "규칙 적용을 해제했습니다.")


@bp.route("/reports", methods=["GET", "POST"])
@admin_required
def reports():
    form = ReportForm()
    form.dataset_id.choices = [_dataset_choice(d) for d in service.trace_datasets()]
    if request.method == "GET" and request.args.get("dataset_id", type=int):
        form.dataset_id.data = request.args.get("dataset_id", type=int)
    status = 200
    if form.validate_on_submit():
        try:
            report = service.create_report(current_user, service.get_dataset(form.dataset_id.data))
        except ServiceError as error:
            status = _flash_error(error)
        else:
            return redirect(url_for("canlab.report", report_id=report.id))
    elif request.method == "POST":
        status = 400
    return render_template("canlab/reports.html", form=form, reports=service.list_reports()), status


@bp.get("/reports/<int:report_id>")
@admin_required
def report(report_id: int):
    item = service.get_report(report_id)
    return render_template("canlab/report.html", report=item, charts=service.chart_data(item),
                           summary=item.ai_summary or service.template_summary(item),
                           action=ActionForm(), ai_ready=service.ai.available_connection() is not None)


@bp.post("/reports/<int:report_id>/ai")
@admin_required
def report_ai(report_id: int):
    if ActionForm().validate_on_submit():
        try:
            service.summarize_with_ai(current_user, service.get_report(report_id))
        except ServiceError as error:
            _flash_error(error)
        else:
            flash("AI 보고서를 만들었습니다.", "success")
    return redirect(url_for("canlab.report", report_id=report_id))


@bp.route("/live", methods=["GET", "POST"])
@admin_required
def live():
    if request.method == "POST":
        form = ActionForm()
        if not form.validate_on_submit():
            return {"message": "보안 토큰이 만료되었습니다. 새로고침하세요."}, 400
        try:
            dataset = service.upload_dataset(
                current_user, filename=request.form.get("filename", "live.txt")[:100],
                content=(request.form.get("content") or "").encode(), kind=DatasetKind.LIVE_CAPTURE,
                vehicle=request.form.get("vehicle") or "미입력", source=DatasetSource.WEB,
            )
        except ServiceError as error:
            return {"message": error.message}, error.status
        return {"id": dataset.id, "url": url_for("canlab.dataset", dataset_id=dataset.id),
                "report_url": url_for("canlab.reports", dataset_id=dataset.id)}, 201
    profiles = [p for p in list_profiles() if p.enabled and p.transport == "ble"]
    requests, from_rules = service.capture_requests(), True
    if not requests:
        # 적용 규칙이 없을 때는 프로필의 조회 명령으로 기초데이터를 모은다.
        requests, from_rules = [{"header": p.request_header, "command": c} for p in profiles[:1]
                                if p.request_header for c in p.read_commands], False
    return render_template("canlab/live.html", profiles=profiles, requests=requests, from_rules=from_rules,
                           action=ActionForm())
