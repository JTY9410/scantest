import enum
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.modules.accounts.models import Company, SoftDeleteMixin, TimestampMixin, User


class ScanType(enum.StrEnum):
    EV = "ev"
    ICE = "ice"

    @property
    def label(self) -> str:
        return {"ev": "전기차", "ice": "내연기관"}[self.value]


class Code(TimestampMixin, SoftDeleteMixin, db.Model):
    """진단(고장) 코드 마스터."""

    __tablename__ = "codes"
    __table_args__ = (
        CheckConstraint("type IN ('ev', 'ice')", name="type_valid"),
        Index("ix_codes_type_code", "type", "code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(String(10))
    code: Mapped[str] = mapped_column(String(255))
    unit_name: Mapped[str] = mapped_column(String(255))
    unit_type: Mapped[str | None] = mapped_column(String(255))
    desc: Mapped[str | None] = mapped_column(Text)
    detail_desc: Mapped[str | None] = mapped_column(Text)
    root_cause: Mapped[str | None] = mapped_column(Text)
    howto_fix1: Mapped[str | None] = mapped_column(Text)
    howto_fix2: Mapped[str | None] = mapped_column(Text)
    howto_fix3: Mapped[str | None] = mapped_column(Text)


class Scan(TimestampMixin, SoftDeleteMixin, db.Model):
    __tablename__ = "scans"
    __table_args__ = (
        CheckConstraint("type IN ('ev', 'ice')", name="type_valid"),
        Index("ix_scans_created_at", "created_at"),
        Index("ix_scans_car_no", "car_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(String(10))
    device_type: Mapped[str] = mapped_column(String(255))
    device_uid: Mapped[str] = mapped_column(String(255))
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    tester_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    scan_vin: Mapped[str | None] = mapped_column(String(255))
    car_no: Mapped[str] = mapped_column(String(255))
    car_vin: Mapped[str] = mapped_column(String(255))
    car_maker: Mapped[str | None] = mapped_column(String(255))
    car_model: Mapped[str] = mapped_column(String(255))
    car_submodel: Mapped[str | None] = mapped_column(String(255))
    car_cc: Mapped[int | None] = mapped_column(Integer)
    car_year: Mapped[int | None] = mapped_column(Integer)
    car_fuel: Mapped[str | None] = mapped_column(String(255))
    car_distance: Mapped[int | None] = mapped_column(Integer)
    car_battery_capacity: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    car_discharge_energy: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    car_charge_energy: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    raw: Mapped[Any | None] = mapped_column(JSON)
    bms_data: Mapped[Any | None] = mapped_column(JSON)

    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id])
    tester: Mapped[User] = relationship(foreign_keys=[tester_id])
    company: Mapped[Company | None] = relationship()
    scan_codes: Mapped[list["ScanCode"]] = relationship(
        primaryjoin="and_(Scan.id == ScanCode.scan_id, ScanCode.deleted_at.is_(None))",
        order_by="ScanCode.id",
        viewonly=True,
    )

    @property
    def type_label(self) -> str:
        try:
            return ScanType(self.type).label
        except ValueError:
            return self.type


class ScanCode(TimestampMixin, SoftDeleteMixin, db.Model):
    __tablename__ = "scan_codes"
    __table_args__ = (CheckConstraint("type IN ('ev', 'ice')", name="type_valid"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(String(10))
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    code_id: Mapped[int] = mapped_column(ForeignKey("codes.id", ondelete="RESTRICT"), index=True)

    scan: Mapped[Scan] = relationship()
    code: Mapped[Code] = relationship()
