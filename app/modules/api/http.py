from typing import Any

from flask import Response, g, jsonify, request

from app.core.errors import ServiceError
from app.modules.api.casing import camelize, snakeize

# Laravel TrimStrings 미들웨어가 공백을 지우지 않던 필드
_UNTRIMMED = {"password", "password_confirmation", "current_password"}


def _normalize(data: Any, key: str | None = None) -> Any:
    if isinstance(data, dict):
        return {k: _normalize(v, k) for k, v in data.items()}
    if isinstance(data, list):
        return [_normalize(v) for v in data]
    if isinstance(data, str):
        value = data if key in _UNTRIMMED else data.strip()
        return None if value == "" else value
    return data


def api_input() -> dict[str, Any]:
    """쿼리와 본문(JSON 또는 폼)을 합쳐 snake_case 키로 돌려준다."""
    if "api_input" not in g:
        merged: dict[str, Any] = {k: v for k, v in request.args.items()}
        body = request.get_json(silent=True) if request.is_json else None
        if isinstance(body, dict):
            merged.update(body)
        else:
            merged.update(request.form.to_dict())
        g.api_input = snakeize(_normalize(merged))
    return g.api_input


def respond(payload: Any, status: int = 200) -> Response:
    response = jsonify(camelize(payload))
    response.status_code = status
    return response


def error_response(error: ServiceError) -> Response:
    return respond({"message": error.message, **error.extra}, error.status)
