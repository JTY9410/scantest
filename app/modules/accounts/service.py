"""모바일 앱 회원 계정 업무 규칙: 가입, 로그인, SMS 인증, 비밀번호·휴대전화 변경, 탈퇴."""

from datetime import timedelta
from typing import Any

from flask import current_app
from sqlalchemy import delete, select

from app.core import audit
from app.core.errors import ServiceError
from app.core.time import utcnow
from app.extensions import db
from app.modules.accounts import tokens
from app.modules.accounts.models import (
    Company,
    SmsVerification,
    User,
    UserType,
    digits_only,
)
from app.modules.accounts.passwords import hash_password, upgrade_hash_if_needed, verify_password
from app.core.validation import validate

PASSWORD_MIN_LENGTH = 8
# 공개 가입으로 만들 수 있는 유형. 관리자는 `flask create-admin`으로만 만든다.
SELF_REGISTER_TYPES = [UserType.TESTER.value, UserType.OWNER.value]

REGISTER_RULES = {
    "company_id": ["nullable", "integer", ("exists", Company, "id")],
    "type": ["required", ("in", SELF_REGISTER_TYPES)],
    "mobile": ["required", "numeric", ("regex", r"^01[0-9]{8,9}$")],
    "biz_no": ["nullable", "numeric", ("regex", r"^[0-9]{10}$")],
    "tid": ["required", "string", ("unique", User, "tid")],
    "name": ["required", "string", ("max", 255)],
    "email": ["nullable", "string", "email", ("max", 255), ("unique", User, "email")],
    "password": ["required", "string", ("min", PASSWORD_MIN_LENGTH), "confirmed"],
    "password_confirmation": ["required", "string", ("min", PASSWORD_MIN_LENGTH)],
}
REGISTER_MESSAGES = {
    "company_id.exists": "존재하지 않는 기업입니다.",
    "type.in": "유효하지 않은 사용자 타입입니다.",
    "mobile.regex": "유효하지 않은 휴대전화 번호입니다.",
    "biz_no.regex": "유효하지 않은 사업자등록번호입니다.",
}


def _active_user_by_tid(tid: str) -> User | None:
    return db.session.scalar(select(User).where(User.tid == tid, User.deleted_at.is_(None)))


def login(tid: str, password: str) -> tuple[User, dict[str, Any]]:
    user = db.session.scalar(select(User).where(User.tid == tid))
    if user is not None and user.deleted_at is not None:
        raise ServiceError("탈퇴한 사용자입니다.")
    if user is None or not verify_password(user, password):
        raise ServiceError("아이디 또는 비밀번호가 일치하지 않습니다.")
    upgrade_hash_if_needed(user, password)
    user.last_login_at = utcnow()
    pair = tokens.token_pair(user)
    db.session.commit()
    return user, pair


def logout(user: User, jwt_payload: dict | None, refresh_token: str | None) -> None:
    if refresh_token:
        tokens.revoke_refresh_tokens(user, refresh_token)
    if jwt_payload:
        tokens.block_access_token(jwt_payload)
    db.session.commit()


def refresh(refresh_token: str | None) -> dict[str, Any]:
    if not refresh_token:
        raise ServiceError("리프레시 토큰이 필요합니다.")
    token = tokens.find_valid_refresh_token(refresh_token)
    if token is None or token.user is None or token.user.deleted_at is not None:
        raise ServiceError("유효하지 않은 리프레시 토큰입니다.", 401)
    token.deleted_at = utcnow()
    pair = tokens.token_pair(token.user)
    db.session.commit()
    return pair


def reissue_after_invalidation(user: User) -> dict[str, Any]:
    tokens.invalidate_all_tokens(user)
    db.session.flush()
    pair = tokens.token_pair(user)
    db.session.commit()
    return pair


def company_by_code(code: str | None) -> Company:
    company = db.session.scalar(
        select(Company).where(Company.code == code, Company.deleted_at.is_(None))
    )
    if company is None:
        raise ServiceError("존재하지 않는 회사입니다")
    return company


def register(data: dict[str, Any]) -> User:
    validated = validate(data, REGISTER_RULES, REGISTER_MESSAGES)
    user = User(
        company_id=int(validated["company_id"]) if validated.get("company_id") else None,
        type=validated["type"],
        mobile=digits_only(validated["mobile"]),
        biz_no=digits_only(validated.get("biz_no")),
        tid=validated["tid"],
        name=validated["name"],
        email=validated.get("email"),
        password=hash_password(validated["password"]),
    )
    db.session.add(user)
    db.session.flush()
    audit.record(
        "회원가입",
        "User",
        user.id,
        user_id=user.id,
        changes={"tid": user.tid, "type": user.type, "company_id": user.company_id},
    )
    db.session.commit()
    return user


def validate_registration_fields(data: dict[str, Any]) -> None:
    """앱 가입 화면이 입력 중인 필드만 미리 검증한다."""
    rules = {k: v for k, v in REGISTER_RULES.items() if k in data}
    validate(data, rules, REGISTER_MESSAGES, summarize=False)


def request_sms(mobile: str, sms_code_key: str, tid: str | None) -> None:
    mobile = digits_only(mobile) or ""
    if tid:
        user = db.session.scalar(
            select(User).where(User.tid == tid, User.mobile == mobile, User.deleted_at.is_(None))
        )
        if user is None:
            raise ServiceError("아이디와 휴대폰 번호가 일치하지 않습니다")
    code = current_app.config.get("SMS_DEV_CODE")
    if not code:
        raise ServiceError("SMS 발송 설정이 되어 있지 않습니다. 관리자에게 문의하세요.", 503)
    db.session.execute(
        delete(SmsVerification).where(
            SmsVerification.mobile == mobile, SmsVerification.sms_code_key == sms_code_key
        )
    )
    db.session.add(
        SmsVerification(
            mobile=mobile,
            sms_code=code,
            sms_code_key=sms_code_key,
            expires_at=utcnow() + timedelta(minutes=current_app.config["SMS_EXPIRE_MINUTES"]),
            is_verified=False,
        )
    )
    db.session.commit()


def _find_verification(
    mobile: str | None, sms_code: str | None, sms_code_key: str | None, verified: bool
) -> SmsVerification | None:
    return db.session.scalar(
        select(SmsVerification).where(
            SmsVerification.mobile == (digits_only(mobile) or ""),
            SmsVerification.sms_code == str(sms_code or ""),
            SmsVerification.sms_code_key == str(sms_code_key or ""),
            SmsVerification.expires_at > utcnow(),
            SmsVerification.is_verified.is_(verified),
        )
    )


def verify_sms(mobile: str | None, sms_code: str | None, sms_code_key: str | None) -> bool:
    verification = _find_verification(mobile, sms_code, sms_code_key, verified=False)
    if verification is None:
        return False
    verification.is_verified = True
    db.session.commit()
    return True


def _consume_verified(mobile: str | None, sms_code: str | None, sms_code_key: str | None) -> bool:
    """인증을 마친 번호를 한 번만 쓸 수 있게 소비한다."""
    verification = _find_verification(mobile, sms_code, sms_code_key, verified=True)
    if verification is None:
        return False
    db.session.delete(verification)
    return True


def mask_tid(tid: str) -> str:
    if len(tid) <= 3:
        return tid[:1] + "*" + tid[-1:]
    return tid[:2] + "*" * max(0, len(tid) - 4) + tid[-2:]


def find_tid(mobile: str | None) -> User:
    user = db.session.scalar(
        select(User)
        .where(User.mobile == (digits_only(mobile) or ""), User.deleted_at.is_(None))
        .order_by(User.id)
    )
    if user is None:
        raise ServiceError("존재하지 않는 휴대폰 번호입니다")
    return user


def _check_new_password(password: str | None) -> None:
    if not password or len(password) < PASSWORD_MIN_LENGTH:
        raise ServiceError(f"비밀번호는 최소 {PASSWORD_MIN_LENGTH}자 이상이어야 합니다.")


def reset_password_by_sms(data: dict[str, Any]) -> dict[str, Any]:
    password = data.get("password")
    if password != data.get("password_confirmation"):
        raise ServiceError("비밀번호가 일치하지 않습니다.")
    _check_new_password(password)
    user = db.session.scalar(
        select(User).where(
            User.tid == data.get("tid"),
            User.mobile == (digits_only(data.get("mobile")) or ""),
            User.deleted_at.is_(None),
        )
    )
    if user is None:
        raise ServiceError("사용자를 찾을 수 없습니다.")
    if not _consume_verified(data.get("mobile"), data.get("sms_code"), data.get("sms_code_key")):
        raise ServiceError("휴대폰 인증번호가 확인되지 않았습니다")
    user.password = hash_password(password)
    audit.record("비밀번호 재설정", "User", user.id, user_id=user.id)
    return reissue_after_invalidation(user)


def set_mobile(user: User, data: dict[str, Any]) -> dict[str, Any]:
    if not _consume_verified(data.get("mobile"), data.get("sms_code"), data.get("sms_code_key")):
        raise ServiceError("휴대폰 인증번호가 확인되지 않았습니다")
    user.mobile = digits_only(data.get("mobile"))
    audit.record("휴대폰 변경", "User", user.id, user_id=user.id)
    return reissue_after_invalidation(user)


def change_password(user: User, data: dict[str, Any]) -> dict[str, Any]:
    new_password = data.get("new_password")
    if not new_password:
        raise ServiceError("새 비밀번호를 입력해주세요.")
    if new_password != data.get("new_password_confirmation"):
        raise ServiceError("새 비밀번호가 일치하지 않습니다.")
    if not verify_password(user, data.get("password") or ""):
        raise ServiceError("아이디 또는 비밀번호가 일치하지 않습니다.")
    _check_new_password(new_password)
    user.password = hash_password(new_password)
    audit.record("비밀번호 변경", "User", user.id, user_id=user.id)
    return reissue_after_invalidation(user)


def withdraw(user: User, message: str | None) -> None:
    tokens.invalidate_all_tokens(user)
    user.deleted_at = utcnow()
    audit.record("삭제", "User", user.id, user_id=user.id, message=message)
    db.session.commit()
