from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.core.errors import ServiceError
from app.modules.auth.access import admin_required
from app.modules.canlab import references, service
from app.modules.canlab.engine import signals
from app.modules.canlab.forms import (
    ActionForm, CompareForm, InputForm, ObdbSyncForm, ReferenceUrlForm, ReportForm, TruthTextForm, UploadForm,
)
from app.modules.canlab.models import DatasetKind, DatasetSource, LogicStatus, ReferenceStatus, RuleStatus

bp = Blueprint("canlab", __name__, url_prefix="/admin/canlab")


@bp.app_template_global("canlab_report_exists")
def report_exists(report_id) -> bool:
    return service.report_exists(report_id)


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


def _truth_rows(item) -> dict:
    return {
        truth.id: {
            "value": request.form.get(f"value-{truth.id}", truth.value_text),
            "signal_key": request.form.get(f"key-{truth.id}", ""),
            "confirmed": request.form.get(f"confirmed-{truth.id}") == "on",
            "delete": request.form.get(f"delete-{truth.id}") == "on",
        }
        for truth in item.truths
    }


@bp.post("/datasets/<int:dataset_id>/truths")
@admin_required
def update_truths(dataset_id: int):
    if ActionForm().validate_on_submit():
        item = service.get_dataset(dataset_id)
        try:
            service.update_truths(current_user, item, _truth_rows(item))
        except ServiceError as error:
            _flash_error(error)
        else:
            flash("정답값을 저장했습니다.", "success")
    return redirect(url_for("canlab.dataset", dataset_id=dataset_id, _anchor="truths"))


@bp.post("/datasets/<int:dataset_id>/delete")
@admin_required
def delete_dataset(dataset_id: int):
    item = service.get_dataset(dataset_id)
    if ActionForm().validate_on_submit():
        service.delete_dataset(current_user, item)
        flash("데이터를 삭제했습니다.", "success")
    return redirect(url_for("canlab.datasets"))


def _dataset_choice(d) -> tuple[int, str]:
    return d.id, f"#{d.id} {d.vehicle} · {d.filename} ({d.kind_label})"


def _pending_url(wescan_id: int, reverse_ids: list[int]) -> str:
    return url_for("canlab.pending", dataset_id=wescan_id, reverse=reverse_ids)


def _analyse(wescan, reverse_ids: list[int], confirm_first: bool = True):
    """확인할 최종값이 남았으면 확인 화면으로, 아니면 바로 분석한다."""
    if confirm_first and any(not t.confirmed for t in wescan.truths):
        flash("결과지 PDF에서 읽은 최종값이 있습니다. 값과 신호를 확인하고 '확정하고 분석'을 누르세요.", "warning")
        return redirect(_pending_url(wescan.id, reverse_ids))
    try:
        run = service.run_analysis(current_user, wescan.id, reverse_ids)
    except ServiceError as error:
        _flash_error(error)
        return redirect(_pending_url(wescan.id, reverse_ids))
    flash("역산 분석을 마쳤습니다. 결과를 확인하고 '디코딩 규칙 후보 만들기'를 누르세요.", "success")
    return redirect(url_for("canlab.run", run_id=run.id))


@bp.route("/analysis", methods=["GET", "POST"])
@admin_required
def analysis():
    form = InputForm()
    status = 200
    if form.validate_on_submit():
        upload = form.wescan_file.data
        try:
            text, pdf = form.values_text.data or "", None
            values = form.values_file.data
            if values and values.filename and values.filename.lower().endswith(".pdf"):
                pdf = (values.filename, values.read())
            elif values and values.filename:
                text += "\n" + service.values_file_text(values.filename, values.read())
            reverse = [(f.filename, f.read()) for f in form.reverse_files.data or [] if f and f.filename]
            wescan, reverse_sets = service.ingest(
                current_user, car_no=form.car_no.data, wescan=(upload.filename or "wescan.trc", upload.read()),
                values_text=text, values_pdf=pdf, reverse=reverse)
        except ServiceError as error:
            status = _flash_error(error)
        else:
            return _analyse(wescan, [d.id for d in reverse_sets])
    elif request.method == "POST":
        status = 400
    return render_template("canlab/analysis.html", form=form, runs=service.list_runs()), status


@bp.route("/analysis/pending/<int:dataset_id>", methods=["GET", "POST"])
@admin_required
def pending(dataset_id: int):
    wescan = service.get_dataset(dataset_id)
    reverse_ids = [i for i in request.args.getlist("reverse", type=int) if i != dataset_id]
    if request.method == "POST":
        if ActionForm().validate_on_submit():
            try:
                service.update_truths(current_user, wescan, _truth_rows(wescan))
            except ServiceError as error:
                _flash_error(error)
            else:
                return _analyse(wescan, reverse_ids, confirm_first=False)
        else:
            flash(CSRF_EXPIRED["message"], "error")
        return redirect(_pending_url(dataset_id, reverse_ids))
    return render_template("canlab/pending.html", dataset=wescan, signals=signals.SIGNALS, action=ActionForm(),
                           reverse=[service.get_dataset(i) for i in reverse_ids])


@bp.get("/analysis/<int:run_id>")
@admin_required
def run(run_id: int):
    return render_template("canlab/run.html", run=service.get_run(run_id), action=ActionForm())


@bp.post("/analysis/<int:run_id>/apply")
@admin_required
def apply_run(run_id: int):
    if not ActionForm().validate_on_submit():
        flash(CSRF_EXPIRED["message"], "error")
        return redirect(url_for("canlab.run", run_id=run_id))
    logic = service.draft_logic(current_user, service.get_run(run_id))
    return redirect(url_for("canlab.logic", logic_id=logic.id))


@bp.route("/compare", methods=["GET", "POST"])
@admin_required
def compare():
    form = CompareForm()
    choices = [(0, "— 파일로 올리기 —")] + [
        (d.id, service.dataset_choice_label(d)) for d in service.scan_trace_datasets()
    ]
    form.dataset_id.choices = choices
    preselect = request.args.get("dataset_id", type=int)
    if request.method == "GET" and preselect and any(preselect == c[0] for c in choices):
        form.dataset_id.data = preselect
    if form.validate_on_submit():
        try:
            text, pdf = form.values_text.data or "", None
            values = form.values_file.data
            if values and values.filename and values.filename.lower().endswith(".pdf"):
                pdf = (values.filename, values.read())
            elif values and values.filename:
                text += "\n" + service.values_file_text(values.filename, values.read())
            scan_upload = form.scan_file.data
            scan_file = None
            if scan_upload and scan_upload.filename:
                scan_file = (scan_upload.filename, scan_upload.read())
            scan_id = request.args.get("scan_id", type=int) or request.form.get("scan_id", type=int)
            compare_row = service.start_compare(
                current_user,
                dataset_id=form.dataset_id.data or None,
                scan_file=scan_file,
                values_text=text,
                values_pdf=pdf,
                scan_id=scan_id,
            )
        except ServiceError as error:
            _flash_error(error)
            return render_template("canlab/compare.html", form=form, compares=service.list_compares()), error.status
        flash("스캔·위스캔 비교를 완료했습니다. AI 초안을 확인하세요.", "success")
        return redirect(url_for("canlab.compare_show", compare_id=compare_row.id))
    return render_template("canlab/compare.html", form=form, compares=service.list_compares())


@bp.get("/compare/<int:compare_id>")
@admin_required
def compare_show(compare_id: int):
    return render_template("canlab/compare_show.html", compare=service.get_compare(compare_id), action=ActionForm())


def _render_logic(logic, status: int = 200):
    return render_template("canlab/logic.html", logic=logic, recommended=service.recommended(logic),
                           options=service.item_options, choices=service.CHOICES, action=ActionForm(),
                           LogicStatus=LogicStatus,
                           ai_ready=service.ai.available_connection() is not None), status


@bp.get("/logics/<int:logic_id>")
@admin_required
def logic(logic_id: int):
    return _render_logic(service.get_logic(logic_id))


@bp.post("/logics/<int:logic_id>/advise")
@admin_required
def advise_logic(logic_id: int):
    if ActionForm().validate_on_submit():
        try:
            _, problem = service.advise_logic(current_user, service.get_logic(logic_id))
        except ServiceError as error:
            _flash_error(error)
        else:
            if problem:
                flash(f"AI 최적안을 받지 못해 기본안을 표시합니다. {problem}", "warning")
            else:
                flash("AI 최적안을 받았습니다. 추천을 확인하고 적용하세요.", "success")
    return redirect(url_for("canlab.logic", logic_id=logic_id))


@bp.post("/logics/<int:logic_id>/confirm")
@admin_required
def confirm_logic(logic_id: int):
    form = ActionForm()
    item = service.get_logic(logic_id)
    if not form.validate_on_submit():
        return _render_logic(item, 400)
    choices = {key[len("choice-"):]: value for key, value in request.form.items() if key.startswith("choice-")}
    try:
        service.confirm_logic(current_user, item, int(form.version.data or 0), choices)
    except ServiceError as error:
        return _render_logic(item, _flash_error(error))
    flash(f"{item.scope_label} 디코딩 규칙(로직 v{item.revision})을 적용했습니다. "
          "다음 스캔부터 이 범위 차량에 이 명령과 수식을 씁니다. 문제가 생기면 변경 이력에서 되돌리세요.", "success")
    return redirect(url_for("canlab.logic", logic_id=logic_id))


@bp.post("/logics/<int:logic_id>/expand")
@admin_required
def expand_logic(logic_id: int):
    if not ActionForm().validate_on_submit():
        flash(CSRF_EXPIRED["message"], "error")
        return redirect(url_for("canlab.logic", logic_id=logic_id))
    try:
        draft = service.draft_expansion(current_user, service.get_logic(logic_id))
    except ServiceError as error:
        _flash_error(error)
        return redirect(url_for("canlab.logic", logic_id=logic_id))
    flash(f"{draft.scope_label} 확대 후보를 만들었습니다. 다른 차종 과거 데이터 비교를 보고 적용하세요.", "success")
    return redirect(url_for("canlab.logic", logic_id=draft.id))


@bp.get("/rules")
@admin_required
def rules():
    return _render_rules()


def _render_rules(status: int = 200):
    return render_template("canlab/rules.html", groups=service.list_rules(), signals=signals.BY_KEY,
                           action=ActionForm(), RuleStatus=RuleStatus, LogicStatus=LogicStatus,
                           drafts=service.draft_logics(), active_logics=service.active_logics(),
                           changes=service.list_changes(), incidents=service.list_incidents()), status


@bp.post("/changes/<int:change_id>/rollback")
@admin_required
def rollback_change(change_id: int):
    if ActionForm().validate_on_submit():
        try:
            change = service.rollback_change(current_user, service.get_change(change_id))
        except ServiceError as error:
            return _render_rules(_flash_error(error))
        flash(f"{change.scope_label}을(를) 변경 이전 기록으로 되돌렸습니다.", "success")
    return redirect(url_for("canlab.rules", _anchor="changes"))


# ── 참고자료 DB ──────────────────────────────────────────────────────────

def _render_references(status: int = 200, url_form=None, sync_form=None):
    return render_template("canlab/references.html", items=references.list_references(), action=ActionForm(),
                           url_form=url_form or ReferenceUrlForm(), sync_form=sync_form or ObdbSyncForm(),
                           ReferenceStatus=ReferenceStatus, signals=signals.BY_KEY,
                           ai_ready=service.ai.available_connection() is not None), status


@bp.get("/references")
@admin_required
def reference_list():
    return _render_references()


@bp.post("/references/sync")
@admin_required
def reference_sync():
    form = ObdbSyncForm()
    if not form.validate_on_submit():
        return _render_references(400, sync_form=form)
    try:
        saved, failed = references.sync_obdb(current_user, form.repo.data, form.keywords.data)
    except ServiceError as error:
        return _render_references(_flash_error(error), sync_form=form)
    flash(f"OBDb 차종 정의 {saved}개를 저장했습니다." + (f" 받지 못한 저장소: {', '.join(failed)}" if failed else ""),
          "warning" if failed else "success")
    return redirect(url_for("canlab.reference_list"))


@bp.post("/references/url")
@admin_required
def reference_register():
    form = ReferenceUrlForm()
    if not form.validate_on_submit():
        return _render_references(400, url_form=form)
    try:
        ref = references.register_url(current_user, form.url.data, form.title.data, form.maker.data, form.model.data)
    except ServiceError as error:
        return _render_references(_flash_error(error), url_form=form)
    if ref.problem:
        flash(f"자료를 저장했지만 해석 항목을 만들지 못했습니다. {ref.problem}", "warning")
    else:
        flash(f"자료를 저장하고 해석 항목 {len(ref.items)}개를 만들었습니다. 확인 후 승인하세요.", "success")
    return redirect(url_for("canlab.reference_list", _anchor=f"ref-{ref.id}"))


def _reference_action(ref_id: int, change, done: str):
    form = ActionForm()
    if form.validate_on_submit():
        try:
            ref = change(references.get_reference(ref_id), int(form.version.data or 0))
        except ServiceError as error:
            return _render_references(_flash_error(error))
        flash(done.format(len(ref.items)), "success")
    return redirect(url_for("canlab.reference_list", _anchor=f"ref-{ref_id}"))


@bp.post("/references/<int:ref_id>/approve")
@admin_required
def reference_approve(ref_id: int):
    return _reference_action(ref_id, lambda ref, v: references.review(current_user, ref, v, True),
                             "참고자료를 승인했습니다. 다음 분석부터 해석 항목 {}개를 씁니다.")


@bp.post("/references/<int:ref_id>/reject")
@admin_required
def reference_reject(ref_id: int):
    return _reference_action(ref_id, lambda ref, v: references.review(current_user, ref, v, False),
                             "참고자료를 반려했습니다.")


@bp.post("/references/<int:ref_id>/retry")
@admin_required
def reference_retry(ref_id: int):
    return _reference_action(ref_id, lambda ref, v: references.reextract(current_user, ref, v),
                             "AI로 다시 정리했습니다. 해석 항목 {}개.")


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
        return _render_rules(status)
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


CSRF_EXPIRED = {"message": "보안 토큰이 만료되었습니다. 새로고침하세요."}


@bp.route("/live", methods=["GET", "POST"])
@admin_required
def live():
    if request.method == "POST":
        if not ActionForm().validate_on_submit():
            return CSRF_EXPIRED, 400
        try:
            dataset = service.upload_dataset(
                current_user, filename=request.form.get("filename", "live.txt")[:100],
                content=(request.form.get("content") or "").encode(), kind=DatasetKind.LIVE_CAPTURE,
                vehicle=request.form.get("vehicle") or "미입력", source=DatasetSource.WEB,
            )
            if request.form.get("report") == "1":
                report = service.create_report(current_user, dataset)
                report_url = url_for("canlab.report", report_id=report.id)
            else:
                report_url = url_for("canlab.reports", dataset_id=dataset.id)
        except ServiceError as error:
            return {"message": error.message}, error.status
        return {"id": dataset.id, "url": url_for("canlab.dataset", dataset_id=dataset.id),
                "report_url": report_url}, 201
    return render_template("canlab/live.html", obd=service.obd_config(), action=ActionForm())


@bp.post("/live/preview")
@admin_required
def live_preview():
    if not ActionForm().validate_on_submit():
        return CSRF_EXPIRED, 400
    try:
        return service.preview_capture((request.form.get("content") or "").encode())
    except ServiceError as error:
        return {"message": error.message}, error.status
