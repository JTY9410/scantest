"""관리자 인증 업무 규칙: 로그인, OTP(MFA), 비밀번호 변경."""

import pyotp
import segno
from sqlalchemy import select

from app.core import audit
from app.core.crypto import decrypt, encrypt
from app.core.errors import ServiceError
from app.core.time import utcnow
from app.extensions import db
from app.modules.accounts.models import User, UserType
from app.modules.accounts.passwords import hash_password, upgrade_hash_if_needed, verify_password

INVALID_LOGIN = "아이디 또는 비밀번호가 올바르지 않습니다."
ISSUER = "WecarScan 관리자"


def authenticate(tid: str, password: str) -> User:
    user = db.session.scalar(select(User).where(User.tid == tid))
    valid = (
        user is not None
        and user.deleted_at is None
        and user.type == UserType.ADMIN
        and verify_password(user, password)
    )
    if not valid:
        audit.record("관리자 로그인 실패", "User", user.id if user else None, message=tid[:100])
        db.session.commit()
        raise ServiceError(INVALID_LOGIN, 401)
    upgrade_hash_if_needed(user, password)
    return user


def mark_logged_in(user: User) -> None:
    user.last_login_at = utcnow()
    audit.record("관리자 로그인", "User", user.id, user_id=user.id)
    db.session.commit()


def verify_otp(user: User, code: str) -> bool:
    if not user.totp_secret_enc:
        return False
    return pyotp.TOTP(decrypt(user.totp_secret_enc)).verify(code.strip(), valid_window=1)


def new_otp_secret() -> str:
    return pyotp.random_base32()


def otp_qr_svg(user: User, secret: str) -> str:
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.tid, issuer_name=ISSUER)
    return segno.make(uri, error="m").svg_inline(scale=5, dark="#0b0b0c", light="#ffffff")


def enable_otp(user: User, secret: str, code: str) -> None:
    if not pyotp.TOTP(secret).verify(code.strip(), valid_window=1):
        raise ServiceError("OTP 코드가 맞지 않습니다. 앱에 표시된 6자리를 다시 입력하세요.")
    user.totp_secret_enc = encrypt(secret)
    audit.record("MFA 등록", "User", user.id, user_id=user.id)
    db.session.commit()


def disable_otp(user: User, code: str) -> None:
    if not verify_otp(user, code):
        raise ServiceError("OTP 코드가 맞지 않습니다.")
    user.totp_secret_enc = None
    audit.record("MFA 해제", "User", user.id, user_id=user.id)
    db.session.commit()


def change_password(user: User, current: str, new: str) -> None:
    if not verify_password(user, current):
        raise ServiceError("현재 비밀번호가 맞지 않습니다.")
    if current == new:
        raise ServiceError("새 비밀번호는 현재 비밀번호와 달라야 합니다.")
    user.password = hash_password(new)
    audit.record("관리자 비밀번호 변경", "User", user.id, user_id=user.id)
    db.session.commit()
