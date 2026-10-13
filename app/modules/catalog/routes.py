from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.core.errors import ServiceError
from app.core.pagination import clamp_page
from app.modules.auth.access import admin_required
from app.modules.catalog import service
from app.modules.catalog.forms import CodeForm, CompanyForm
from app.modules.scans.models import ScanType

bp = Blueprint("catalog", __name__, url_prefix="/admin")


@bp.get("/companies")
@admin_required
def companies():
    q = (request.args.get("q") or "").strip()[:100]
    page = service.search_companies(q, clamp_page(request.args.get("page")))
    return render_template("catalog/companies.html", page=page, q=q)


@bp.route("/companies/new", methods=["GET", "POST"])
@bp.route("/companies/<int:company_id>/edit", methods=["GET", "POST"])
@admin_required
def company_form(company_id: int | None = None):
    company = service.get_company(company_id) if company_id else None
    form = CompanyForm(obj=company)
    if form.validate_on_submit():
        try:
            service.save_company(current_user, form.data, company)
        except ServiceError as error:
            flash(error.message, "error")
        else:
            flash("회사 정보를 저장했습니다.", "success")
            return redirect(url_for("catalog.companies"))
    return render_template("catalog/company_form.html", form=form, company=company)


@bp.get("/codes")
@admin_required
def codes():
    q = (request.args.get("q") or "").strip()[:100]
    code_type = request.args.get("type", "")
    page = service.search_codes(q, code_type, clamp_page(request.args.get("page")))
    return render_template("catalog/codes.html", page=page, q=q, code_type=code_type,
                           types=list(ScanType))


@bp.route("/codes/new", methods=["GET", "POST"])
@bp.route("/codes/<int:code_id>/edit", methods=["GET", "POST"])
@admin_required
def code_form(code_id: int | None = None):
    code = service.get_code(code_id) if code_id else None
    form = CodeForm(obj=code)
    if form.validate_on_submit():
        service.save_code(current_user, form.data, code)
        flash("진단코드를 저장했습니다.", "success")
        return redirect(url_for("catalog.codes"))
    return render_template("catalog/code_form.html", form=form, code=code)
