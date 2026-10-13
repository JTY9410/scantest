from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_limiter.util import get_remote_address
from flask_login import current_user, login_user, logout_user
from flask_wtf import FlaskForm
from markupsafe import Markup

from app.core.crypto import encryption_ready
from app.core.errors import ServiceError
from app.extensions import db, limiter
from app.modules.accounts.models import User
from app.modules.auth import service
from app.modules.auth.access import admin_required
from app.modules.auth.forms import LoginForm, OtpForm, PasswordChangeForm

bp = Blueprint("auth", __name__, url_prefix="/admin")

_PENDING = "mfa_pending_user_id"
_SETUP = "mfa_setup_secret"


def _login_limit() -> str:
    return current_app.config["ADMIN_LOGIN_RATE_LIMIT"]


def _login_key() -> str:
    return f"{get_remote_address()}:{(request.form.get('tid') or '').strip().lower()}"


def _safe_next(target: str | None) -> str:
    if target and target.startswith("/admin") and not target.startswith("//"):
        return target
    return url_for("admin.dashboard")


def _complete_login(user: User, next_url: str | None):
    session.clear()  # 로그인 시 세션을 새로 발급한다.
    login_user(user, fresh=True)
    session.permanent = True
    session["show_install_hint"] = True
    service.mark_logged_in(user)
    return redirect(_safe_next(next_url))


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(_login_limit, key_func=_login_key, methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        try:
            user = service.authenticate(form.tid.data.strip(), form.password.data)
        except ServiceError as error:
            flash(error.message, "error")
            return render_template("auth/login.html", form=form), 401
        next_url = request.args.get("next")
        if user.mfa_enabled:
            db.session.commit()
            session.clear()
            session[_PENDING] = user.id
            session["mfa_next"] = next_url
            return redirect(url_for("auth.mfa"))
        return _complete_login(user, next_url)
    return render_template("auth/login.html", form=form)


@bp.route("/mfa", methods=["GET", "POST"])
@limiter.limit(_login_limit, methods=["POST"])
def mfa():
    user_id = session.get(_PENDING)
    user = db.session.get(User, user_id) if user_id else None
    if user is None or not user.is_admin or not user.is_active:
        session.pop(_PENDING, None)
        return redirect(url_for("auth.login"))
    form = OtpForm()
    if form.validate_on_submit():
        if service.verify_otp(user, form.code.data):
            return _complete_login(user, session.get("mfa_next"))
        flash("OTP 코드가 맞지 않습니다.", "error")
    return render_template("auth/mfa.html", form=form)


@bp.post("/logout")
def logout():
    logout_user()
    session.clear()
    flash("로그아웃했습니다.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/account", methods=["GET", "POST"])
@admin_required
def account():
    password_form = PasswordChangeForm(prefix="pw")
    if password_form.validate_on_submit():
        try:
            service.change_password(
                current_user, password_form.current_password.data, password_form.new_password.data
            )
        except ServiceError as error:
            flash(error.message, "error")
        else:
            flash("비밀번호를 변경했습니다.", "success")
            return redirect(url_for("auth.account"))
    secret = session.get(_SETUP)
    qr = Markup(service.otp_qr_svg(current_user, secret)) if secret else None
    return render_template(
        "auth/account.html",
        password_form=password_form,
        otp_form=OtpForm(prefix="otp"),
        action_form=FlaskForm(),
        setup_secret=secret,
        setup_qr=qr,
        encryption_ready=encryption_ready(),
    )


@bp.post("/account/mfa/start")
@admin_required
def mfa_start():
    if not FlaskForm().validate_on_submit():
        return redirect(url_for("auth.account"))
    if not encryption_ready():
        flash("ENCRYPTION_KEY가 설정되지 않아 OTP를 등록할 수 없습니다.", "error")
        return redirect(url_for("auth.account"))
    session[_SETUP] = service.new_otp_secret()
    return redirect(url_for("auth.account") + "#mfa")


@bp.post("/account/mfa/confirm")
@admin_required
def mfa_confirm():
    form = OtpForm(prefix="otp")
    secret = session.get(_SETUP)
    if secret and form.validate_on_submit():
        try:
            service.enable_otp(current_user, secret, form.code.data)
        except ServiceError as error:
            flash(error.message, "error")
            return redirect(url_for("auth.account") + "#mfa")
        session.pop(_SETUP, None)
        flash("2단계 인증을 켰습니다. 다음 로그인부터 OTP를 입력합니다.", "success")
    else:
        flash("6자리 OTP 코드를 입력하세요.", "error")
    return redirect(url_for("auth.account") + "#mfa")


@bp.post("/account/mfa/cancel")
@admin_required
def mfa_cancel():
    if FlaskForm().validate_on_submit():
        session.pop(_SETUP, None)
    return redirect(url_for("auth.account") + "#mfa")


@bp.post("/account/mfa/disable")
@admin_required
def mfa_disable():
    form = OtpForm(prefix="otp")
    if form.validate_on_submit():
        try:
            service.disable_otp(current_user, form.code.data)
        except ServiceError as error:
            flash(error.message, "error")
        else:
            flash("2단계 인증을 껐습니다.", "success")
    else:
        flash("6자리 OTP 코드를 입력하세요.", "error")
    return redirect(url_for("auth.account") + "#mfa")
