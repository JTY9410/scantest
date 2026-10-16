from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from sqlalchemy import select

from app.core.errors import ServiceError
from app.extensions import db
from app.modules.accounts.models import Company
from app.modules.auth.access import admin_required
from app.modules.api.http import api_input
from app.modules.obd import devices, service, telematics
from app.modules.obd.forms import ObdProfileForm, TelematicsDeviceForm

bp = Blueprint("obd", __name__, url_prefix="/admin/obd")


def _device_form() -> TelematicsDeviceForm:
    form = TelematicsDeviceForm(prefix="device")
    companies = db.session.scalars(select(Company).where(Company.deleted_at.is_(None)).order_by(Company.name))
    form.company_id.choices = [(0, "없음")] + [(c.id, c.name) for c in companies]
    return form


def _index(device_form=None, new_token=None, status=200):
    return render_template("obd/index.html", profiles=service.list_profiles(), devices=telematics.list_devices(),
                           device_form=device_form or _device_form(), action=FlaskForm(),
                           new_token=new_token, remembered=devices.list_recent()), status


@bp.get("/")
@admin_required
def index():
    # 관리자 OBD 목록을 열 때 위스캔 BLE 기본 프로필이 없으면 한 번 만든다(웹 이름 필터는 obd-link.js에도 있음).
    service.ensure_bwsi_profile()
    return _index()


@bp.post("/my-devices")
@admin_required
def my_device_save():
    try:
        device, created = devices.remember(current_user, "web", api_input())
    except ServiceError as error:
        return {"message": error.message, **error.extra}, error.status
    return {"id": device.id}, 201 if created else 200


@bp.delete("/my-devices/<int:device_id>")
@admin_required
def my_device_forget(device_id: int):
    try:
        devices.forget(current_user, device_id)
    except ServiceError as error:
        return {"message": error.message}, error.status
    return {"message": "삭제되었습니다."}


@bp.post("/devices")
@admin_required
def device_register():
    form = _device_form()
    if not form.validate_on_submit():
        return _index(form, status=400)
    try:
        device, token = telematics.register(current_user, serial=form.serial.data, name=form.name.data,
                                            company_id=form.company_id.data)
    except ServiceError as error:
        flash(error.message, "error")
        return _index(form, status=error.status)
    return _index(new_token={"device": device, "token": token}, status=201)


@bp.post("/devices/<int:device_id>/token")
@admin_required
def device_token(device_id: int):
    if not FlaskForm().validate_on_submit():
        return redirect(url_for("obd.index"))
    device = telematics.get_device(device_id)
    token = telematics.rotate_token(current_user, device)
    return _index(new_token={"device": device, "token": token})


@bp.post("/devices/<int:device_id>/toggle")
@admin_required
def device_toggle(device_id: int):
    if FlaskForm().validate_on_submit():
        device = telematics.get_device(device_id)
        telematics.set_enabled(current_user, device, not device.enabled)
        flash(f"{device.name} 단말기를 {'사용' if device.enabled else '중지'}로 바꿨습니다.", "success")
    return redirect(url_for("obd.index", _anchor="devices-title"))


@bp.route("/new", methods=["GET", "POST"])
@bp.route("/<int:profile_id>/edit", methods=["GET", "POST"])
@admin_required
def form(profile_id: int | None = None):
    profile = service.get_profile(profile_id) if profile_id else None
    form = ObdProfileForm(obj=profile)
    if request.method == "GET" and profile:
        form.init_commands.data = "\n".join(profile.init_commands)
        form.read_commands.data = "\n".join(profile.read_commands)
        form.version.data = profile.version

    status = 200
    if form.validate_on_submit():
        try:
            version = int(form.version.data or 0) if profile else None
            service.save_profile(current_user, form.data, profile, version)
        except ServiceError as error:
            flash(error.message, "error")
            status = error.status
        else:
            flash("OBD2 프로필을 저장했습니다.", "success")
            return redirect(url_for("obd.index"))
    return render_template("obd/form.html", form=form, profile=profile), status
