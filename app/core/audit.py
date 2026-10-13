from datetime import datetime
from typing import Any

from flask import has_request_context, request
from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.extensions import db

_SECRET_MARKERS = ("password", "secret", "token", "api_key", "key_enc", "authkey")


class Activity(db.Model):
    """감사 기록. 변경자·시각·대상·행동을 남기고 비밀값은 저장하지 않는다."""

    __tablename__ = "activities"
    __table_args__ = (
        Index("ix_activities_relation_relation_id", "relation", "relation_id"),
        Index("ix_activities_relation_type", "relation_type"),
        Index("ix_activities_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    ip: Mapped[str] = mapped_column(String(45), default="")
    relation: Mapped[str] = mapped_column(String(100))
    relation_type: Mapped[str] = mapped_column(String(100))
    relation_id: Mapped[int | None] = mapped_column(BigInteger)
    changes: Mapped[Any | None] = mapped_column(JSON)
    message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user = relationship("User", lazy="joined")


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("[제외]" if any(m in str(k).lower() for m in _SECRET_MARKERS) else scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def record(
    action: str,
    relation: str,
    relation_id: int | None = None,
    *,
    user_id: int | None = None,
    changes: Any = None,
    message: str | None = None,
) -> Activity:
    """감사 기록을 세션에 추가한다. 커밋은 호출한 서비스가 한다."""
    activity = Activity(
        user_id=user_id,
        ip=(request.remote_addr or "") if has_request_context() else "cli",
        relation=relation,
        relation_type=action,
        relation_id=relation_id,
        changes=scrub(changes) if changes else None,
        message=(message or None) and message[:500],
    )
    db.session.add(activity)
    return activity
