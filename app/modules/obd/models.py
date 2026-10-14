import enum
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.modules.accounts.models import Company, TimestampMixin, User


class ObdTransport(enum.StrEnum):
    BLE = "ble"
    CLASSIC = "classic"

    @property
    def label(self) -> str:
        return {"ble": "BLE (저전력)", "classic": "클래식 (SPP)"}[self.value]


class ObdProfile(TimestampMixin, db.Model):
    """모바일 앱이 블루투스 OBD2 진단기(ELM327 계열)에 연결할 때 받아 쓰는 설정."""

    __tablename__ = "obd_profiles"
    __table_args__ = (
        CheckConstraint("transport IN ('ble', 'classic')", name="transport_valid"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    transport: Mapped[str] = mapped_column(String(10))
    device_name_prefix: Mapped[str] = mapped_column(String(50))
    service_uuid: Mapped[str | None] = mapped_column(String(36))
    write_uuid: Mapped[str | None] = mapped_column(String(36))
    notify_uuid: Mapped[str | None] = mapped_column(String(36))
    init_commands: Mapped[list[str]] = mapped_column(JSON, default=list)
    request_header: Mapped[str | None] = mapped_column(String(8))
    response_header: Mapped[str | None] = mapped_column(String(8))
    read_commands: Mapped[list[str]] = mapped_column(JSON, default=list)
    response_timeout_ms: Mapped[int] = mapped_column(Integer, default=2000)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}

    @property
    def transport_label(self) -> str:
        return ObdTransport(self.transport).label


class TelematicsDevice(TimestampMixin, db.Model):
    """차량에 꽂아 두는 LTE OBD2 단말기. 토큰은 해시만 저장하고 등록할 때 한 번만 보여 준다."""

    __tablename__ = "telematics_devices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    serial: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_last4: Mapped[str] = mapped_column(String(4))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    # 단말기가 올린 스캔의 검사자(Scan.tester_id). 등록한 관리자다.
    registered_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped[Company | None] = relationship()
    registrar: Mapped[User] = relationship()
