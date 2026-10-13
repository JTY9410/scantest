"""Laravel 검증 규칙 중 이 API가 쓰는 것만 같은 의미·같은 한국어 문구로 구현한다."""

import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select

from app.core.errors import ServiceError
from app.extensions import db

ATTRIBUTES = {
    "tid": "아이디",
    "password": "비밀번호",
    "password_confirmation": "비밀번호 확인",
    "mobile": "휴대전화",
    "name": "이름",
    "email": "이메일",
    "type": "사용자 타입",
    "biz_no": "사업자등록번호",
}

MESSAGES = {
    "required": "{a} 필드는 필수입니다.",
    "string": "{a}은(는) 문자열이어야 합니다.",
    "integer": "{a}은(는) 정수여야 합니다.",
    "numeric": "{a}은(는) 숫자여야 합니다.",
    "email": "{a}은(는) 유효한 이메일 주소여야 합니다.",
    "array": "{a}은(는) 배열이어야 합니다.",
    "json": "{a}은(는) 유효한 JSON 문자열이어야 합니다.",
    "date": "{a}은(는) 유효한 날짜가 아닙니다.",
    "confirmed": "{a} 확인이 일치하지 않습니다.",
    "min": "{a}은(는) 최소 {p} 문자여야 합니다.",
    "max": "{a}은(는) {p} 문자보다 클 수 없습니다.",
    "regex": "{a} 형식이 유효하지 않습니다.",
    "in": "선택한 {a}은(는) 유효하지 않습니다.",
    "exists": "선택한 {a}은(는) 유효하지 않습니다.",
    "unique": "이미 사용 중인 {a}입니다.",
}

_IMPLICIT = {"required"}
_MISSING = object()

Rule = str | tuple


def _name(rule: Rule) -> str:
    return rule if isinstance(rule, str) else rule[0]


def _attribute(field: str) -> str:
    return ATTRIBUTES.get(field, field.replace("_", " "))


def _is_int(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value) is not None


def _is_numeric(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float, Decimal)):
        return True
    if isinstance(value, str):
        try:
            Decimal(value)
        except InvalidOperation:
            return False
        return True
    return False


def _check(rule: Rule, field: str, value: Any, data: dict[str, Any]) -> bool:
    name = _name(rule)
    if name == "required":
        return value is not None and value is not _MISSING and value != [] and value != {}
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return _is_int(value)
    if name == "numeric":
        return _is_numeric(value)
    if name == "array":
        return isinstance(value, (list, dict))
    if name == "json":
        if not isinstance(value, str):
            return False
        try:
            json.loads(value)
        except ValueError:
            return False
        return True
    if name == "date":
        if not isinstance(value, str):
            return False
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return True
    if name == "email":
        if not isinstance(value, str):
            return False
        try:
            validate_email(value, check_deliverability=False)
        except EmailNotValidError:
            return False
        return True
    if name == "confirmed":
        return data.get(f"{field}_confirmation") == value
    if name in {"min", "max"}:
        size = len(value) if isinstance(value, (str, list, dict)) else Decimal(str(value))
        return size >= rule[1] if name == "min" else size <= rule[1]
    if name == "regex":
        return re.search(rule[1], str(value)) is not None
    if name == "in":
        return value in rule[1]
    if name in {"exists", "unique"}:
        model, column = rule[1], rule[2]
        if getattr(model, column).type.python_type is int:
            if not _is_int(value):
                return name == "unique"
            value = int(value)
        found = db.session.scalar(
            select(getattr(model, column)).where(getattr(model, column) == value).limit(1)
        )
        return (found is not None) if name == "exists" else (found is None)
    raise ValueError(f"알 수 없는 검증 규칙: {name}")


def validate(
    data: dict[str, Any],
    rules: dict[str, list[Rule]],
    messages: dict[str, str] | None = None,
    *,
    summarize: bool = True,
) -> dict[str, Any]:
    """검증에 통과한 필드만 돌려준다. 실패하면 422 ServiceError."""
    messages = messages or {}
    errors: dict[str, list[str]] = {}
    validated: dict[str, Any] = {}

    for field, field_rules in rules.items():
        names = {_name(r) for r in field_rules}
        present = field in data
        value = data.get(field, _MISSING)
        if "sometimes" in names and not present:
            continue
        if present:
            validated[field] = value
        if "nullable" in names and value is None:
            continue
        for rule in field_rules:
            name = _name(rule)
            if name in {"nullable", "sometimes"}:
                continue
            if value is _MISSING and name not in _IMPLICIT:
                continue
            if _check(rule, field, None if value is _MISSING else value, data):
                continue
            param = rule[1] if isinstance(rule, tuple) and name in {"min", "max"} else ""
            text = messages.get(f"{field}.{name}") or MESSAGES[name].format(
                a=_attribute(field), p=param
            )
            errors.setdefault(field, []).append(text)
            if name in _IMPLICIT:
                break

    if errors:
        all_messages = [m for msgs in errors.values() for m in msgs]
        message = all_messages[0]
        extra = len(all_messages) - 1
        if summarize and extra:
            message += f" (and {extra} more error{'s' if extra > 1 else ''})"
        raise ServiceError(message, 422, errors=errors)
    return validated
