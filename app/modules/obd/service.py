"""블루투스 OBD2 연결 프로필 업무 규칙."""

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm.exc import StaleDataError

from app.core import audit
from app.core.errors import ServiceError
from app.extensions import db
from app.modules.accounts.models import User
from app.modules.obd.models import ObdDialect, ObdProfile, ObdTransport

CONFLICT = "다른 관리자가 먼저 이 프로필을 수정했습니다. 새로고침한 뒤 다시 저장하세요."
BWSI_PROFILE_NAME = "위스캔 BLE(BWSI)"

UUID_PATTERN = re.compile(
    r"[0-9a-f]{4}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
HEADER_PATTERN = re.compile(r"[0-9A-F]{3}|[0-9A-F]{8}")
ADAPTER_COMMAND_PATTERN = re.compile(r"(AT|ST)[A-Z0-9@#.,]{1,20}")
READ_COMMAND_PATTERN = re.compile(r"([0-9A-F]{2}){1,7}")
MAX_COMMANDS = 50


def command_lines(text: str | None) -> list[str]:
    """한 줄에 하나씩 적은 명령을 공백 없는 대문자로 바꾼다. 빈 줄은 버린다."""
    return [re.sub(r"\s+", "", line).upper() for line in (text or "").splitlines() if line.strip()]


def _optional(value: str | None, transform=str.strip) -> str | None:
    value = (value or "").strip()
    return transform(value) if value else None


def ensure_bwsi_profile() -> ObdProfile:
    """위스캔 전용 BLE(광고 이름 bwsi…) 프로필이 없으면 만든다.
    UUID는 흔한 BLE UART 힌트(fff0/fff2/fff1)만 두고, 연결 시 ATI로 실제 채널을 찾는다."""
    existing = db.session.scalar(select(ObdProfile).where(ObdProfile.name == BWSI_PROFILE_NAME))
    if existing is not None:
        return existing
    profile = ObdProfile(
        name=BWSI_PROFILE_NAME, transport=ObdTransport.BLE, device_name_prefix="bwsi",
        service_uuid="fff0", write_uuid="fff2", notify_uuid="fff1",
        init_commands=[], read_commands=[], response_timeout_ms=2000, enabled=True,
        dialect=ObdDialect.ELM327,
    )
    db.session.add(profile)
    db.session.commit()
    return profile


def list_profiles() -> list[ObdProfile]:
    return list(db.session.scalars(select(ObdProfile).order_by(ObdProfile.name, ObdProfile.id)))


def enabled_profiles() -> list[ObdProfile]:
    stmt = select(ObdProfile).where(ObdProfile.enabled.is_(True))
    return list(db.session.scalars(stmt.order_by(ObdProfile.name, ObdProfile.id)))


def get_profile(profile_id: int) -> ObdProfile:
    profile = db.session.get(ObdProfile, profile_id)
    if profile is None:
        raise ServiceError("OBD2 프로필을 찾을 수 없습니다.", 404)
    return profile


def _values(data: dict[str, Any]) -> dict[str, Any]:
    ble = data["transport"] == ObdTransport.BLE
    return {
        "name": data["name"].strip(),
        "transport": data["transport"],
        "device_name_prefix": data["device_name_prefix"].strip(),
        "service_uuid": _optional(data.get("service_uuid"), str.lower) if ble else None,
        "write_uuid": _optional(data.get("write_uuid"), str.lower) if ble else None,
        "notify_uuid": _optional(data.get("notify_uuid"), str.lower) if ble else None,
        "init_commands": command_lines(data.get("init_commands")),
        "request_header": _optional(data.get("request_header"), str.upper),
        "response_header": _optional(data.get("response_header"), str.upper),
        "read_commands": command_lines(data.get("read_commands")),
        "response_timeout_ms": int(data["response_timeout_ms"]),
        "enabled": bool(data.get("enabled")),
        "dialect": data.get("dialect") or ObdDialect.ELM327,
        "can_bitrate": (data.get("can_bitrate") or None) if data.get("dialect") == ObdDialect.SLCAN else None,
    }


def save_profile(actor: User, data: dict[str, Any], profile: ObdProfile | None = None,
                 version: int | None = None) -> ObdProfile:
    values = _values(data)
    taken = db.session.scalar(
        select(ObdProfile.id).where(ObdProfile.name == values["name"],
                                    ObdProfile.id != (profile.id if profile else 0))
    )
    if taken:
        raise ServiceError("이미 사용 중인 프로필 이름입니다.")

    if profile is None:
        profile = ObdProfile(**values)
        db.session.add(profile)
        db.session.flush()
        audit.record("OBD2 프로필 등록", "ObdProfile", profile.id, user_id=actor.id,
                     changes={"name": profile.name, "transport": profile.transport})
        db.session.commit()
        return profile

    if profile.version != version:
        raise ServiceError(CONFLICT, 409)
    changes = {
        key: {"before": getattr(profile, key), "after": value}
        for key, value in values.items()
        if getattr(profile, key) != value
    }
    if not changes:
        return profile
    for key, value in values.items():
        setattr(profile, key, value)
    audit.record("OBD2 프로필 수정", "ObdProfile", profile.id, user_id=actor.id, changes=changes)
    try:
        db.session.commit()
    except StaleDataError as exc:
        db.session.rollback()
        raise ServiceError(CONFLICT, 409) from exc
    return profile
