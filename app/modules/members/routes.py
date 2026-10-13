from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.core.errors import ServiceError
from app.modules.accounts.models import UserType
from app.modules.auth.access import admin_required
from app.modules.members import service
from app.modules.members.forms import MemberEditForm

bp = Blueprint("members", __name__, url_prefix="/admin/members")


@bp.get("/")
@admin_required
def index():
    filters = service.MemberFilters.from_args(request.args)
    return render_template(
        "members/index.html",
        page=service.search_members(filters),
        filters=filters,
        companies=service.companies(),
        types=list(UserType),
        statuses=service.STATUSES,
        sorts={
            "-created_at": "최근 가입순",
            "created_at": "오래된 가입순",
            "-last_login_at": "최근 로그인순",
            "name": "이름순",
            "tid": "아이디순",
        },
    )


@bp.get("/<int:user_id>")
@admin_required
def show(user_id: int):
    member = service.get_member(user_id)
    return render_template(
        "members/show.html", member=member, summary=service.member_summary(member)
    )


@bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit(user_id: int):
    member = service.get_member(user_id)
    form = MemberEditForm(obj=member)
    form.company_id.choices = [(0, "소속 없음")] + [(c.id, c.name) for c in service.companies()]
    if request.method == "GET":
        form.company_id.data = member.company_id or 0
        form.mobile.data = member.formatted_mobile
        form.biz_no.data = member.formatted_biz_no
        form.version.data = member.version

    if form.validate_on_submit():
        try:
            version = int(form.version.data or 0)
            service.update_member(current_user, user_id, form.data, version)
        except ServiceError as error:
            flash(error.message, "error")
        else:
            flash("회원 정보를 저장했습니다.", "success")
            return redirect(url_for("members.show", user_id=user_id))
    return render_template("members/edit.html", member=member, form=form)
