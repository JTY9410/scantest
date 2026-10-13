from collections.abc import Callable
from functools import wraps

from flask import g, request
from sqlalchemy import select

from app.core.errors import ServiceError
from app.core.time import utcnow
from app.extensions import db
from app.modules.accounts.models import User
from app.modules.accounts.tokens import TokenError, decode_access_token
from app.modules.api.http import api_input


def current_user() -> User:
    return g.api_user


def _bearer_token() -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return api_input().get("token")


def _authenticate_jwt(token: str) -> User | None:
    try:
        payload = decode_access_token(token)
    except TokenError:
        return None
    try:
        user = db.session.get(User, int(payload["sub"]))
    except (TypeError, ValueError):
        return None
    if user is None or user.deleted_at is not None:
        raise ServiceError("사용자를 찾을 수 없습니다.", 401)
    if payload.get("token_version", 1) != user.token_version:
        raise ServiceError("토큰이 무효화되었습니다.", 401)
    g.jwt_payload = payload
    return user


def _authenticate_api_key(api_key: str) -> User | None:
    user = db.session.scalar(
        select(User).where(User.api_key == api_key, User.deleted_at.is_(None))
    )
    if user is None:
        return None
    if user.api_key_expired(utcnow()):
        raise ServiceError("API 키가 만료되었습니다.", 401)
    if not user.ip_allowed(request.remote_addr or ""):
        raise ServiceError("허용되지 않은 IP 주소입니다.", 403)
    g.jwt_payload = None
    return user


def require_api_auth(view: Callable) -> Callable:
    """JWT를 먼저 확인하고, 실패하면 api_key 파라미터로 인증한다."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        user = None
        token = _bearer_token()
        if token:
            user = _authenticate_jwt(token)
        if user is None:
            api_key = api_input().get("api_key")
            if api_key:
                user = _authenticate_api_key(str(api_key))
        if user is None:
            raise ServiceError("인증이 필요합니다.", 401)
        g.api_user = user
        return view(*args, **kwargs)

    return wrapper
