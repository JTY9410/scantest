import enum
import re
from datetime import datetime

from flask_login import UserMixin
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.extensions import db


class UserType(enum.StrEnum):
    ADMIN = "admin"
    TESTER = "tester"
    OWNER = "owner"

    @property
    def label(self) -> str:
        return {"admin": "관리자", "tester": "테스터", "owner": "소유자"}[self.value]


def digits_only(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"[^0-9]", "", str(value))


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class Company(TimestampMixin, SoftDeleteMixin, db.Model):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
    code: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))


class User(UserMixin, TimestampMixin, SoftDeleteMixin, db.Model):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("type IN ('admin', 'tester', 'owner')", name="type_valid"),
        Index("ix_users_type", "type"),
        Index("ix_users_mobile", "mobile"),
        Index("ix_users_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    type: Mapped[str] = mapped_column(String(20))
    mobile: Mapped[str | None] = mapped_column(String(255))
    biz_no: Mapped[str | None] = mapped_column(String(255))
    tid: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password: Mapped[str] = mapped_column(String(255))
    token_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    api_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    api_host: Mapped[str | None] = mapped_column(Text)
    api_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    # 고장코드 지우기 권한(2026-10-18 대표 결정). 기본은 없음. 웹은 관리자 + MFA, 앱은 관리자·테스터만.
    can_clear_dtc: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    company: Mapped[Company | None] = relationship(lazy="joined")

    __mapper_args__ = {"version_id_col": version}

    @property
    def is_active(self) -> bool:  # Flask-Login
        return self.deleted_at is None

    @property
    def is_admin(self) -> bool:
        return self.type == UserType.ADMIN

    @property
    def mfa_enabled(self) -> bool:
        return bool(self.totp_secret_enc)

    @property
    def type_label(self) -> str:
        try:
            return UserType(self.type).label
        except ValueError:
            return self.type

    @property
    def formatted_biz_no(self) -> str | None:
        if not self.biz_no:
            return None
        return re.sub(r"^(\d{3})(\d{2})(\d{5})$", r"\1-\2-\3", self.biz_no)

    @property
    def formatted_mobile(self) -> str | None:
        if not self.mobile:
            return None
        return re.sub(r"^(\d{3})(\d{3,4})(\d{4})$", r"\1-\2-\3", self.mobile)

    def api_key_expired(self, now: datetime) -> bool:
        return self.api_expires_at is not None and self.api_expires_at <= now

    def ip_allowed(self, ip: str) -> bool:
        if not self.api_host:
            return False
        hosts = [h.strip() for h in self.api_host.split(",") if h.strip()]
        if "*" in hosts:
            return True
        for host in hosts:
            if host == ip:
                return True
            if host.endswith("*") and ip.startswith(host.rstrip("*")):
                return True
        return False


class RefreshToken(TimestampMixin, SoftDeleteMixin, db.Model):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class JwtBlocklist(db.Model):
    """로그아웃한 액세스 토큰(jti). 만료 시각이 지나면 정리해도 된다."""

    __tablename__ = "jwt_blocklist"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SmsVerification(TimestampMixin, db.Model):
    __tablename__ = "sms_verifications"
    __table_args__ = (Index("ix_sms_verifications_mobile_key", "mobile", "sms_code_key"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
    mobile: Mapped[str] = mapped_column(String(255))
    sms_code: Mapped[str] = mapped_column(String(20))
    sms_code_key: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
