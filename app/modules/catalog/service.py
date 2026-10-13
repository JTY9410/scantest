"""회사·진단코드 마스터 관리 업무 규칙."""

from typing import Any

from flask import current_app
from sqlalchemy import or_, select

from app.core import audit
from app.core.errors import ServiceError
from app.core.pagination import Page, paginate
from app.extensions import db
from app.modules.accounts.models import Company, User
from app.modules.scans.models import Code

COMPANY_FIELDS = ("code", "name")
CODE_FIELDS = ("type", "code", "unit_name", "unit_type", "desc", "detail_desc", "root_cause",
               "howto_fix1", "howto_fix2", "howto_fix3")


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _apply(actor: User, entity, fields: tuple[str, ...], data: dict[str, Any], relation: str,
           action: str) -> None:
    changes = {}
    for field in fields:
        value = _clean(data.get(field))
        if getattr(entity, field) != value:
            changes[field] = {"before": getattr(entity, field), "after": value}
            setattr(entity, field, value)
    if changes:
        db.session.flush()
        audit.record(action, relation, entity.id, user_id=actor.id, changes=changes)
    db.session.commit()


def search_companies(q: str, page: int) -> Page:
    stmt = select(Company).where(Company.deleted_at.is_(None))
    if q:
        stmt = stmt.where(or_(Company.code.ilike(f"%{q}%"), Company.name.ilike(f"%{q}%")))
    return paginate(stmt.order_by(Company.name, Company.id), page,
                    current_app.config["ADMIN_PAGE_SIZE"])


def get_company(company_id: int) -> Company:
    company = db.session.get(Company, company_id)
    if company is None or company.deleted_at is not None:
        raise ServiceError("회사를 찾을 수 없습니다.", 404)
    return company


def save_company(actor: User, data: dict[str, Any], company: Company | None = None) -> Company:
    code = _clean(data.get("code"))
    duplicate = db.session.scalar(
        select(Company.id).where(Company.code == code, Company.id != (company.id if company else 0))
    )
    if duplicate:
        raise ServiceError("이미 사용 중인 기업코드입니다.")
    if company is None:
        company = Company(code=code, name=_clean(data.get("name")))
        db.session.add(company)
        db.session.flush()
        audit.record("회사 등록", "Company", company.id, user_id=actor.id,
                     changes={"code": company.code, "name": company.name})
        db.session.commit()
        return company
    _apply(actor, company, COMPANY_FIELDS, data, "Company", "회사 수정")
    return company


def search_codes(q: str, code_type: str, page: int) -> Page:
    stmt = select(Code).where(Code.deleted_at.is_(None))
    if code_type in ("ev", "ice"):
        stmt = stmt.where(Code.type == code_type)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(Code.code.ilike(pattern), Code.unit_name.ilike(pattern),
                              Code.desc.ilike(pattern)))
    return paginate(stmt.order_by(Code.type, Code.code, Code.id), page,
                    current_app.config["ADMIN_PAGE_SIZE"])


def get_code(code_id: int) -> Code:
    code = db.session.get(Code, code_id)
    if code is None or code.deleted_at is not None:
        raise ServiceError("진단코드를 찾을 수 없습니다.", 404)
    return code


def save_code(actor: User, data: dict[str, Any], code: Code | None = None) -> Code:
    if code is None:
        code = Code(**{field: _clean(data.get(field)) for field in CODE_FIELDS})
        db.session.add(code)
        db.session.flush()
        audit.record("진단코드 등록", "Code", code.id, user_id=actor.id,
                     changes={"type": code.type, "code": code.code})
        db.session.commit()
        return code
    _apply(actor, code, CODE_FIELDS, data, "Code", "진단코드 수정")
    return code
