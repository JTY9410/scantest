from datetime import timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from sqlalchemy import func, select

from app.core.audit import Activity
from app.core.crypto import encryption_ready
from app.core.errors import ServiceError
from app.core.time import utcnow
from app.extensions import db
from app.modules.accounts.models import User, UserType
from app.modules.admin import ai_service
from app.modules.admin.forms import AiKeyForm, AiSettingsForm
from app.modules.admin.models import AiProvider
from app.modules.auth.access import admin_required
from app.modules.canlab import service as canlab_service
from app.modules.canlab.forms import ActionForm
from app.modules.reports.models import Applog, CarMismatchReport
from app.modules.scans.models import Scan

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _count(stmt) -> int:
    return db.session.scalar(stmt) or 0


@bp.get("/")
@admin_required
def dashboard():
    week_ago = utcnow() - timedelta(days=7)
    members = dict(
        db.session.execute(
            select(User.type, func.count()).where(User.deleted_at.is_(None)).group_by(User.type)
        ).all()
    )
    stats = {
        "members": sum(members.values()),
        "testers": members.get(UserType.TESTER.value, 0),
        "owners": members.get(UserType.OWNER.value, 0),
        "scans": _count(select(func.count()).select_from(Scan).where(Scan.deleted_at.is_(None))),
        "scans_week": _count(
            select(func.count()).select_from(Scan).where(
                Scan.deleted_at.is_(None), Scan.created_at >= week_ago
            )
        ),
        "reports": _count(
            select(func.count()).select_from(CarMismatchReport).where(
                CarMismatchReport.deleted_at.is_(None)
            )
        ),
        "applogs_week": _count(
            select(func.count()).select_from(Applog).where(Applog.created_at >= week_ago)
        ),
    }
    activities = db.session.scalars(
        select(Activity).order_by(Activity.created_at.desc(), Activity.id.desc()).limit(8)
    ).all()
    return render_template(
        "admin/dashboard.html",
        stats=stats,
        activities=activities,
        connections=ai_service.connections_by_provider(),
        providers=list(AiProvider),
        obd=canlab_service.obd_config(),
        action=ActionForm(),
    )


@bp.get("/ai")
@admin_required
def ai_index():
    return render_template(
        "admin/ai_index.html",
        connections=ai_service.connections_by_provider(),
        providers=list(AiProvider),
        encryption_ready=encryption_ready(),
        features_summary=ai_service.features_summary,
    )


@bp.route("/ai/<provider>", methods=["GET", "POST"])
@admin_required
def ai_edit(provider: str):
    try:
        connection = ai_service.get_connection(provider)
    except ServiceError as error:
        flash(error.message, "error")
        return redirect(url_for("admin.ai_index"))

    form = AiSettingsForm(prefix="settings", obj=connection)
    if request.method == "GET" and connection:
        form.features.data = [k for k, on in (connection.features or {}).items() if on]
        form.version.data = connection.version
    if form.validate_on_submit():
        try:
            ai_service.save_settings(
                current_user,
                provider,
                model=form.model.data,
                features=form.features.data or [],
                monthly_budget=form.monthly_budget.data,
                monthly_token_limit=form.monthly_token_limit.data,
                version=int(form.version.data) if form.version.data else None,
            )
        except ServiceError as error:
            flash(error.message, "error")
        else:
            flash("AI 연결 설정을 저장했습니다.", "success")
            return redirect(url_for("admin.ai_edit", provider=provider))

    return render_template(
        "admin/ai_edit.html",
        provider=AiProvider(provider),
        connection=connection,
        form=form,
        key_form=AiKeyForm(prefix="key"),
        action_form=FlaskForm(),
        encryption_ready=encryption_ready(),
    )


@bp.post("/ai/<provider>/key")
@admin_required
def ai_key(provider: str):
    form = AiKeyForm(prefix="key")
    if form.validate_on_submit():
        try:
            ai_service.replace_key(current_user, provider, form.api_key.data)
        except ServiceError as error:
            flash(error.message, "error")
        else:
            flash("API 키를 암호화해 저장했습니다. 연결 테스트를 실행하세요.", "success")
    else:
        flash("API 키를 확인하세요.", "error")
    return redirect(url_for("admin.ai_edit", provider=provider))


@bp.post("/ai/<provider>/test")
@admin_required
def ai_test(provider: str):
    if FlaskForm().validate_on_submit():
        try:
            connection = ai_service.test_connection(current_user, provider)
        except ServiceError as error:
            flash(error.message, "error")
        else:
            category = "success" if connection.status == "ok" else "error"
            flash(connection.last_test_message, category)
    return redirect(url_for("admin.ai_edit", provider=provider))


@bp.post("/ai/<provider>/revoke")
@admin_required
def ai_revoke(provider: str):
    if FlaskForm().validate_on_submit():
        try:
            ai_service.revoke_key(current_user, provider)
        except ServiceError as error:
            flash(error.message, "error")
        else:
            flash("API 키를 폐기했습니다. 이 공급자를 쓰는 기능도 모두 껐습니다.", "success")
    return redirect(url_for("admin.ai_edit", provider=provider))
