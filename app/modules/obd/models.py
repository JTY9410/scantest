import enum

from sqlalchemy import JSON, BigInteger, Boolean, CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.modules.accounts.models import TimestampMixin


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
