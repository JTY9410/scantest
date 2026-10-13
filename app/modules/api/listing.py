"""기존 CrudOperations 트레이트의 search / order / with / page 규칙을 구현한다.

search=field:value||field:op:value   (op: = != <> > >= < <= like in)
order=field:asc|desc||...
with=relation,relation.nested
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Select, String, cast, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import ServiceError
from app.core.pagination import clamp_page, clamp_per_page, paginate
from app.modules.api.casing import snake

_OPERATORS = {"=", "!=", "<>", ">", ">=", "<", "<=", "like", "in"}


def _coerce(column, raw: str) -> Any:
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        return raw
    try:
        if python_type is int:
            return int(raw)
        if python_type is Decimal:
            return Decimal(raw)
        if python_type is bool:
            return raw.lower() in {"1", "true"}
        if python_type is datetime:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, InvalidOperation) as exc:
        raise ServiceError(f"검색 값 형식이 올바르지 않습니다: {raw}", 400) from exc
    return raw


def _column(model, field: str, allowed: set[str]):
    name = snake(field)
    if name not in allowed:
        raise ServiceError(f"사용할 수 없는 필드입니다: {field}", 400)
    return getattr(model, name)


def _like(column, raw: str) -> ColumnElement:
    target = column if isinstance(column.type, String) else cast(column, String)
    pattern = raw if "%" in raw else f"%{raw}%"
    return target.ilike(pattern)


def _condition(model, condition: str, allowed: set[str]) -> ColumnElement | None:
    parts = condition.split(":")
    if len(parts) == 2:
        column = _column(model, parts[0], allowed)
        return column == _coerce(column, parts[1])
    if len(parts) == 3:
        column = _column(model, parts[0], allowed)
        op, raw = parts[1].lower(), parts[2]
        if op not in _OPERATORS:
            raise ServiceError(f"사용할 수 없는 검색 연산자입니다: {parts[1]}", 400)
        if op == "in":
            return column.in_([_coerce(column, v) for v in raw.split(",")])
        if op == "like":
            values = [v.strip() for v in raw.split(",")]
            if len(values) > 1:
                return or_(*(_like(column, v) for v in values))
            return _like(column, raw)
        value = _coerce(column, raw)
        return {
            "=": column == value,
            "!=": column != value,
            "<>": column != value,
            ">": column > value,
            ">=": column >= value,
            "<": column < value,
            "<=": column <= value,
        }[op]
    return None


def apply_search(stmt: Select, model, search: str | None, allowed: set[str]) -> Select:
    if not search:
        return stmt
    for condition in str(search).split("||"):
        clause = _condition(model, condition, allowed)
        if clause is not None:
            stmt = stmt.where(clause)
    return stmt


def apply_order(stmt: Select, model, order: str | None, allowed: set[str]) -> Select:
    if order:
        for condition in str(order).split("||"):
            parts = condition.split(":")
            if len(parts) == 2:
                column = _column(model, parts[0], allowed)
                stmt = stmt.order_by(column.desc() if parts[1].lower() == "desc" else column.asc())
    return stmt


def parse_with(value: str | None, relations: dict[str, Any]) -> set[str]:
    """`with` 파라미터를 snake_case 관계 경로 집합으로 바꾼다."""
    if not value:
        return set()
    requested = set()
    for item in str(value).split(","):
        item = item.strip()
        if not item:
            continue
        path = ".".join(snake(p) for p in item.split("."))
        if path not in relations:
            raise ServiceError(f"포함할 수 없는 관계입니다: {item}", 400)
        requested.add(path)
    return requested


def load_options(requested: set[str], relations: dict[str, Any]) -> list:
    return [relations[path]() for path in sorted(requested)]


def list_payload(
    stmt: Select,
    model,
    params: dict[str, Any],
    allowed: set[str],
    relations: dict[str, Any],
    serialize,
) -> dict[str, Any]:
    stmt = apply_search(stmt, model, params.get("search"), allowed)
    stmt = apply_order(stmt, model, params.get("order"), allowed)
    requested = parse_with(params.get("with"), relations)
    stmt = stmt.options(*load_options(requested, relations))
    stmt = stmt.order_by(model.created_at.desc(), model.id.desc())
    page = paginate(stmt, clamp_page(params.get("page")), clamp_per_page(params.get("per_page")))
    return {
        "data": [serialize(item, requested) for item in page.items],
        "meta": {
            "current_page": page.page,
            "last_page": page.last_page,
            "per_page": page.per_page,
            "total": page.total,
        },
    }


def eager(*attrs) -> Any:
    """관계 경로를 selectinload 옵션 생성 함수로 만든다."""

    def build():
        option = selectinload(attrs[0])
        for attr in attrs[1:]:
            option = option.selectinload(attr)
        return option

    return build
