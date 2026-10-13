from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.modules.accounts.models import SoftDeleteMixin, TimestampMixin, User


class CarMismatchReport(TimestampMixin, SoftDeleteMixin, db.Model):
    """차량정보 조회 결과와 스캔 차대번호가 다를 때 앱이 보내는 신고."""

    __tablename__ = "car_mismatch_reports"
    __table_args__ = (Index("ix_car_mismatch_reports_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    car_no: Mapped[str] = mapped_column(String(20))
    api_vin: Mapped[str] = mapped_column(String(17))
    scan_vin: Mapped[str] = mapped_column(String(17))

    user: Mapped[User] = relationship()


class Applog(TimestampMixin, db.Model):
    """모바일 앱이 올리는 진단 로그."""

    __tablename__ = "applogs"
    __table_args__ = (
        Index("ix_applogs_created_at", "created_at"),
        Index("ix_applogs_timestamp", "timestamp"),
        Index("ix_applogs_type", "type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    type: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(String(2000))
    desc: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User | None] = relationship()
