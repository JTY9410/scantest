import enum
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

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

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
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

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
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


class MakerScanCommand(db.Model):
    """제조사·차종에서 실제로 응답한 읽기 명령. 다음 스캔 계획에 다시 넣는다.

    model·header가 비어 있으면 제조사 공통·기능 주소다. 고유 키는 NULL도 서로 같다.
    """

    __tablename__ = "maker_scan_commands"
    __table_args__ = (
        Index(
            "uq_maker_scan_commands", "maker", "model", "header", "command",
            unique=True, postgresql_nulls_not_distinct=True,
        ),
        Index("ix_maker_scan_commands_maker", "maker"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
    maker: Mapped[str] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
    header: Mapped[str | None] = mapped_column(String(8))
    command: Mapped[str] = mapped_column(String(32))

    @validates("maker")
    def _normalize_maker(self, _key, value):
        from app.core.makers import normalize_maker
        return normalize_maker(value) or value

    hits: Mapped[int] = mapped_column(Integer, default=1)
    last_scan_id: Mapped[int | None] = mapped_column(BigInteger)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DtcClearLog(db.Model):
    """고장코드 지우기 기록(감사). 계획을 발급할 때 'issued'로 만들고, 결과를 받으면 상태를 바꾼다.

    token_hash: 1회용 계획 토큰의 SHA-256. 결과 저장은 같은 사용자·같은 스캔·유효시간 안에 한 번만.
    status: issued → ok | partial | failed | aborted, 또는 시간이 지나면 expired.
    """

    __tablename__ = "dtc_clear_logs"
    __table_args__ = (
        CheckConstraint("status IN ('issued', 'ok', 'partial', 'failed', 'aborted', 'expired')",
                        name="status_valid"),
        Index("ix_dtc_clear_logs_scan_id", "scan_id"),
        Index("ix_dtc_clear_logs_user_id", "user_id"),
        Index("ix_dtc_clear_logs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    ip: Mapped[str] = mapped_column(String(45), default="")
    source: Mapped[str] = mapped_column(String(10))  # web | app
    car_no: Mapped[str | None] = mapped_column(String(20))
    vin: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(10), default="issued")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    targets: Mapped[list] = mapped_column(JSON, default=list)
    dtcs_before: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict | None] = mapped_column(JSON)
    steps: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    scan: Mapped[Scan] = relationship()
    user: Mapped["User"] = relationship()


class ScanCode(TimestampMixin, SoftDeleteMixin, db.Model):
    __tablename__ = "scan_codes"
    __table_args__ = (CheckConstraint("type IN ('ev', 'ice')", name="type_valid"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
    type: Mapped[str] = mapped_column(String(10))
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    code_id: Mapped[int] = mapped_column(ForeignKey("codes.id", ondelete="RESTRICT"), index=True)

    scan: Mapped[Scan] = relationship()
    code: Mapped[Code] = relationship()


DEFAULT_CAR_INFO_URL = "https://diag.wecarmobility.co.kr/api/get_car_info"


class CarInfoSetting(TimestampMixin, db.Model):
    """위카 차량정보 조회 API 연결. 한 행만 쓴다. 인증키 평문은 저장하지 않는다."""

    __tablename__ = "car_info_settings"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
    url: Mapped[str] = mapped_column(String(500), default=DEFAULT_CAR_INFO_URL)
    key_enc: Mapped[str | None] = mapped_column(Text)
    key_last4: Mapped[str | None] = mapped_column(String(4))
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_message: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}

    @property
    def has_key(self) -> bool:
        return bool(self.key_enc)


class CarInfoCache(TimestampMixin, db.Model):
    """차량번호별 조회 결과. 원천 데이터에 일일 조회 한도가 있어 성공한 조회는 재사용한다."""

    __tablename__ = "car_info_cache"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
    car_no: Mapped[str] = mapped_column(String(20), unique=True)
    dto: Mapped[dict[str, Any]] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ScanDocument(TimestampMixin, db.Model):
    """스캔 결과 PDF. 스캔을 저장할 때 함께 만든다."""

    __tablename__ = "scan_documents"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), unique=True)
    filename: Mapped[str] = mapped_column(String(200))
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))

    scan: Mapped[Scan] = relationship()
