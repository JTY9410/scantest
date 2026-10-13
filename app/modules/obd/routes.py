from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.core.errors import ServiceError
from app.modules.auth.access import admin_required
from app.modules.obd import service
from app.modules.obd.forms import ObdProfileForm

bp = Blueprint("obd", __name__, url_prefix="/admin/obd")


@bp.get("/")
@admin_required
def index():
    return render_template("obd/index.html", profiles=service.list_profiles())


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
