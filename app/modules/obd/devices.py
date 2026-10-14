"""사용자가 한 번 연결한 진단기 기억. 웹(브라우저)과 앱이 각자 기억하고 서버 계정에도 남긴다."""

from typing import Any

from sqlalchemy import select

from app.core.errors import ServiceError
from app.core.time import utcnow
from app.core.validation import validate
from app.extensions import db
from app.modules.accounts.models import User
from app.modules.obd.models import ObdDevice, ObdDialect

PLATFORMS = ("web", "app")
TRANSPORTS = ("ble", "classic", "serial", "wifi")
MAX_PER_USER = 20
_UUID = r"^([0-9a-fA-F]{4}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
_SETTINGS = ("bitrate", "baud", "host", "port")

RULES = {
    "transport": ["required", ("in", TRANSPORTS)],
    "name": ["required", "string", ("max", 100)],
    "dialect": ["nullable", ("in", tuple(ObdDialect))],
    "chip": ["nullable", "string", ("max", 100)],
    "version": ["nullable", "string", ("max", 100)],
    "service_uuid": ["nullable", "string", ("regex", _UUID)],
    "write_uuid": ["nullable", "string", ("regex", _UUID)],
    "notify_uuid": ["nullable", "string", ("regex", _UUID)],
    "protocol": ["nullable", "string", ("regex", r"^[1-9A-C]$")],
    "settings": ["nullable", "array"],
}


def _settings(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {k: v if isinstance(v, int) else str(v)[:100] for k, v in value.items()
            if k in _SETTINGS and isinstance(v, (int, str)) and not isinstance(v, bool)}


def list_for(user: User, platform: str | None = None) -> list[ObdDevice]:
    stmt = select(ObdDevice).where(ObdDevice.user_id == user.id)
    if platform:
        stmt = stmt.where(ObdDevice.platform == platform)
    return list(db.session.scalars(stmt.order_by(ObdDevice.last_connected_at.desc(), ObdDevice.id.desc())))


def list_recent(limit: int = 100) -> list[ObdDevice]:
    stmt = select(ObdDevice).order_by(ObdDevice.last_connected_at.desc(), ObdDevice.id.desc()).limit(limit)
    return list(db.session.scalars(stmt))


def remember(user: User, platform: str, data: dict[str, Any]) -> tuple[ObdDevice, bool]:
    """같은 사용자·플랫폼·연결 방식·이름이면 고쳐 쓰고, 아니면 새로 남긴다. (진단기, 새로 만들었는지)"""
    values = validate(data, RULES)
    key = {"user_id": user.id, "platform": platform, "transport": values["transport"], "name": values["name"]}
    device = db.session.scalar(select(ObdDevice).filter_by(**key))
    created = device is None
    if created:
        device = ObdDevice(**key)
        db.session.add(device)
    device.dialect = values.get("dialect") or ObdDialect.ELM327
    device.chip = values.get("chip")
    device.version = values.get("version")
    for field in ("service_uuid", "write_uuid", "notify_uuid"):
        setattr(device, field, (values.get(field) or "").lower() or None)
    device.protocol = values.get("protocol")
    device.settings = _settings(values.get("settings"))
    device.last_connected_at = utcnow()
    db.session.flush()
    if created:
        stale = list_for(user, platform)[MAX_PER_USER:]
        for old in stale:
            db.session.delete(old)
    db.session.commit()
    return device, created


def forget(user: User, device_id: int) -> None:
    device = db.session.scalar(select(ObdDevice).where(ObdDevice.id == device_id, ObdDevice.user_id == user.id))
    if device is None:
        raise ServiceError("기억한 진단기를 찾을 수 없습니다.", 404)
    db.session.delete(device)
    db.session.commit()
