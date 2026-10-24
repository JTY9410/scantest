import enum
from datetime import datetime

from sqlalchemy import (JSON, BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.modules.accounts.models import Company, TimestampMixin, User


class ObdTransport(enum.StrEnum):
    BLE = "ble"
    CLASSIC = "classic"

    @property
    def label(self) -> str:
        return {"ble": "BLE (저전력)", "classic": "클래식 (SPP)"}[self.value]


class ObdDialect(enum.StrEnum):
    """진단기 명령 체계. 연결 방식(BLE·시리얼)과 따로 고른다."""

    ELM327 = "elm327"
    STN = "stn"
    SLCAN = "slcan"

    @property
    def label(self) -> str:
        return {"elm327": "ELM327 (AT 명령)", "stn": "STN (OBDLink, ST 명령)",
                "slcan": "slcan (원시 CAN, CANable·WiCAN)"}[self.value]


CAN_BITRATES = (125000, 250000, 500000, 1000000)


class ObdProfile(TimestampMixin, db.Model):
    """모바일 앱이 블루투스 OBD2 진단기(ELM327·STN·slcan)에 연결할 때 받아 쓰는 설정."""

    __tablename__ = "obd_profiles"
    __table_args__ = (
        CheckConstraint("transport IN ('ble', 'classic')", name="transport_valid"),
        CheckConstraint("dialect IN ('elm327', 'stn', 'slcan')", name="dialect_valid"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
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
    dialect: Mapped[str] = mapped_column(String(10), default=ObdDialect.ELM327, server_default="elm327")
    # slcan만 쓴다. 비우면 차량 버스를 500k→250k 순서로 찾는다.
    can_bitrate: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}

    @property
    def transport_label(self) -> str:
        return ObdTransport(self.transport).label

    @property
    def dialect_label(self) -> str:
        return ObdDialect(self.dialect).label


class ObdDevice(TimestampMixin, db.Model):
    """사용자가 웹·앱에서 한 번 연결한 진단기. 다른 기기에서 처음 연결할 때 명령 체계·UUID를 미리 채운다."""

    __tablename__ = "obd_devices"
    __table_args__ = (
        UniqueConstraint("user_id", "platform", "transport", "name", name="uq_obd_devices_user_device"),
        CheckConstraint("platform IN ('web', 'app')", name="platform_valid"),
        CheckConstraint("transport IN ('ble', 'classic', 'serial', 'wifi')", name="transport_valid"),
        CheckConstraint("dialect IN ('elm327', 'stn', 'slcan')", name="dialect_valid"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(10))
    transport: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(100))
    dialect: Mapped[str] = mapped_column(String(10), default=ObdDialect.ELM327)
    chip: Mapped[str | None] = mapped_column(String(100))
    version: Mapped[str | None] = mapped_column(String(100))
    service_uuid: Mapped[str | None] = mapped_column(String(36))
    write_uuid: Mapped[str | None] = mapped_column(String(36))
    notify_uuid: Mapped[str | None] = mapped_column(String(36))
    # ATDPN 숫자(예: 6). 다음 연결에서 ATSPA<번호>로 자동 감지를 줄인다.
    protocol: Mapped[str | None] = mapped_column(String(2))
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    last_connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()

    @property
    def dialect_label(self) -> str:
        return ObdDialect(self.dialect).label


class TelematicsDevice(TimestampMixin, db.Model):
    """차량에 꽂아 두는 LTE OBD2 단말기. 토큰은 해시만 저장하고 등록할 때 한 번만 보여 준다."""

    __tablename__ = "telematics_devices"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
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
