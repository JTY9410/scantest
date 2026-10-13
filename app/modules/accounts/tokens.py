import hashlib
import secrets
import string
from datetime import datetime, timedelta

import jwt
from flask import current_app, has_request_context, request
from sqlalchemy import select, update

from app.core.time import utcnow
from app.extensions import db
from app.modules.accounts.models import JwtBlocklist, RefreshToken, User

ALGORITHM = "HS256"
# Laravel jwt-auth가 넣던 provider 해시. 두 서버가 같은 비밀키를 쓰는 동안 토큰이 서로 호환되도록 유지한다.
_PRV = hashlib.sha1(b"App\\Models\\User").hexdigest()
_ALPHANUM = string.ascii_letters + string.digits


class TokenError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.message = message
        self.status = status


def random_token(length: int = 64) -> str:
    return "".join(secrets.choice(_ALPHANUM) for _ in range(length))


def ttl_seconds() -> int:
    return current_app.config["JWT_TTL_MINUTES"] * 60


def issue_access_token(user: User) -> str:
    now = utcnow()
    payload = {
        "iss": (
            request.url_root.rstrip("/") + "/api/auth/login" if has_request_context() else "wecarscan"
        ),
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds())).timestamp()),
        "jti": random_token(16),
        "sub": str(user.id),
        "prv": _PRV,
        "token_version": user.token_version,
    }
    return jwt.encode(payload, current_app.config["JWT_SECRET"], algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            current_app.config["JWT_SECRET"],
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub"], "verify_sub": False},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("토큰이 만료되었습니다.") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("유효하지 않은 토큰입니다.") from exc
    jti = payload.get("jti")
    if jti and db.session.get(JwtBlocklist, jti):
        raise TokenError("무효화된 토큰입니다.")
    return payload


def block_access_token(payload: dict) -> None:
    jti = payload.get("jti")
    if not jti or db.session.get(JwtBlocklist, jti):
        return
    expires = datetime.fromtimestamp(payload["exp"], tz=utcnow().tzinfo)
    db.session.add(JwtBlocklist(jti=jti, expires_at=expires))


def create_refresh_token(user: User) -> RefreshToken:
    token = RefreshToken(
        user_id=user.id,
        token=random_token(64),
        expires_at=utcnow() + timedelta(minutes=current_app.config["JWT_REFRESH_TTL_MINUTES"]),
    )
    db.session.add(token)
    return token


def find_valid_refresh_token(value: str) -> RefreshToken | None:
    return db.session.scalar(
        select(RefreshToken).where(
            RefreshToken.token == value,
            RefreshToken.expires_at > utcnow(),
            RefreshToken.deleted_at.is_(None),
        )
    )


def revoke_refresh_tokens(user: User, token_value: str | None = None) -> None:
    stmt = update(RefreshToken).where(
        RefreshToken.user_id == user.id, RefreshToken.deleted_at.is_(None)
    )
    if token_value is not None:
        stmt = stmt.where(RefreshToken.token == token_value)
    db.session.execute(stmt.values(deleted_at=utcnow()))


def invalidate_all_tokens(user: User) -> None:
    """토큰 버전을 올려 기존 액세스 토큰을 모두 무효화하고 리프레시 토큰을 폐기한다."""
    user.token_version = (user.token_version or 1) + 1
    revoke_refresh_tokens(user)


def token_pair(user: User) -> dict:
    access = issue_access_token(user)
    refresh = create_refresh_token(user)
    return {
        "access_token": access,
        "refresh_token": refresh.token,
        "token_type": "bearer",
        "expires_in": ttl_seconds(),
    }
