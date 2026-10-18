"""회사·진단코드 마스터 관리 업무 규칙."""

import json
import re
from typing import Any

from flask import current_app
from sqlalchemy import or_, select

from app.core import audit
from app.core.errors import ServiceError
from app.core.pagination import Page, paginate
from app.extensions import db
from app.modules.accounts.models import Company, User
from app.modules.knowledge.models import KnowledgeDTC
from app.modules.scans.models import Code, Scan

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


_DTC = re.compile(r"^[PCBU][0-9A-F]{4}$", re.I)
_AI_SYSTEM = (
    "당신은 공개된 OBD-II(SAE J2012, ISO 15031-6) 고장코드 설명만 한글로 적습니다. "
    "제조사 비공개 코드는 지어내지 말고 known을 false로 두세요. JSON 배열만 답합니다."
)


def _wanted_codes(text: str) -> list[str]:
    found = []
    for token in re.split(r"[\s,]+", (text or "").upper()):
        if _DTC.fullmatch(token) and token not in found:
            found.append(token)
    return found[:40]


def undescribed_codes(limit: int = 20) -> list[str]:
    """최근 스캔에 있고 마스터 설명이 없는 고장코드."""
    known = {row[0] for row in db.session.execute(
        select(Code.code).where(Code.deleted_at.is_(None), Code.desc.is_not(None)))}
    found = []
    scans = db.session.scalars(select(Scan).where(Scan.deleted_at.is_(None)).order_by(Scan.id.desc()).limit(40))
    for scan in scans:
        data = scan.bms_data if isinstance(scan.bms_data, dict) else {}
        for dtc in data.get("dtcs") or []:
            code = str(dtc.get("code") or "").upper()
            if _DTC.fullmatch(code) and code not in known and code not in found:
                found.append(code)
            if len(found) >= limit:
                return found
    return found


def _parse_ai(text: str) -> list[dict]:
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        raise ServiceError("AI가 고장코드 목록을 돌려주지 않았습니다.")
    try:
        rows = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ServiceError("AI 응답을 읽지 못했습니다.") from exc
    return rows if isinstance(rows, list) else []


def fill_codes_with_ai(actor: User, text: str) -> dict[str, int]:
    """공개 OBD 설명만 codes와 지식베이스 초안에 넣는다. 키가 없으면 등록하지 않는다."""
    from app.modules.canlab import ai

    codes = _wanted_codes(text) or undescribed_codes()
    if not codes:
        raise ServiceError("채울 고장코드가 없습니다. 코드를 입력하거나 설명 없는 스캔을 먼저 저장하세요.")
    prompt = (
        "다음 고장코드마다 공개 표준 설명만 JSON 배열로 답하세요. "
        "항목은 code, type(ev 또는 ice), unit_name, desc, known(true/false)입니다. "
        "known이 false면 desc는 빈 문자열입니다.\n" + ", ".join(codes)
    )
    answer, _provider = ai.ask(_AI_SYSTEM, prompt)
    saved = skipped = 0
    for row in _parse_ai(answer):
        code = str(row.get("code") or "").upper()
        if code not in codes or row.get("known") is not True:
            skipped += 1
            continue
        desc = str(row.get("desc") or "").strip()
        if not desc:
            skipped += 1
            continue
        kind = "ev" if row.get("type") == "ev" else "ice"
        unit = str(row.get("unit_name") or "OBD").strip()[:255] or "OBD"
        existing = db.session.scalar(select(Code).where(Code.code == code, Code.deleted_at.is_(None)))
        if existing is None:
            db.session.add(Code(type=kind, code=code, unit_name=unit, desc=desc[:2000],
                                detail_desc="공개 OBD 표준을 AI로 채움"))
        elif not existing.desc:
            existing.desc = desc[:2000]
            existing.unit_name = existing.unit_name or unit
        else:
            skipped += 1
            continue
        draft = db.session.scalar(select(KnowledgeDTC).where(
            KnowledgeDTC.code == code, KnowledgeDTC.source == "ai_research"))
        if draft is None:
            db.session.add(KnowledgeDTC(
                code=code, description=desc[:2000], source="ai_research",
                source_detail="공개 OBD 표준", status="draft", confidence=0.5))
        saved += 1
    db.session.flush()
    audit.record("진단코드 AI 등록", "Code", None, user_id=actor.id, changes={"saved": saved, "skipped": skipped})
    db.session.commit()
    return {"saved": saved, "skipped": skipped}
