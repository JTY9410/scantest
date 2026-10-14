"""LTE OBD2 단말기: 등록, 토큰 인증, 스캔 계획 제공, 스캔 결과 수신.

단말기는 'Authorization: Device <토큰>'으로 인증한다. 토큰 평문은 등록·재발급 때 한 번만 보여 주고
SHA-256 해시만 저장한다.
"""

import hashlib
import re
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core import audit
from app.core.errors import ServiceError
from app.extensions import db
from app.modules.accounts.models import Company, User
from app.modules.canlab.models import DatasetSource
from app.modules.obd.models import TelematicsDevice
from app.modules.scanner import service as scanner
from app.modules.scanner.plan import build_plan
from app.modules.scans import car_info
from app.modules.scans.models import Scan

SERIAL_PATTERN = re.compile(r"[A-Za-z0-9._:-]{4,64}")
UNAUTHORIZED = "단말기 인증에 실패했습니다."


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def list_devices() -> list[TelematicsDevice]:
    return list(db.session.scalars(select(TelematicsDevice).order_by(TelematicsDevice.id.desc())))


def get_device(device_id: int) -> TelematicsDevice:
    device = db.session.get(TelematicsDevice, device_id)
    if device is None:
        raise ServiceError("단말기를 찾을 수 없습니다.", 404)
    return device


def register(actor: User, *, serial: str, name: str, company_id: int | None = None) -> tuple[TelematicsDevice, str]:
    serial = (serial or "").strip()
    if not SERIAL_PATTERN.fullmatch(serial):
        raise ServiceError("단말기 일련번호는 영문·숫자·.-_: 4~64자입니다.")
    if db.session.scalar(select(TelematicsDevice.id).where(TelematicsDevice.serial == serial)):
        raise ServiceError("이미 등록된 일련번호입니다.", 409)
    if company_id and db.session.get(Company, company_id) is None:
        raise ServiceError("회사를 찾을 수 없습니다.")
    token = _new_token()
    device = TelematicsDevice(serial=serial, name=(name or serial).strip()[:100], token_hash=_hash(token),
                              token_last4=token[-4:], company_id=company_id or None, registered_by=actor.id)
    db.session.add(device)
    db.session.flush()
    audit.record("LTE 단말기 등록", "TelematicsDevice", device.id, user_id=actor.id,
                 changes={"serial": serial, "name": device.name})
    db.session.commit()
    return device, token


def rotate_token(actor: User, device: TelematicsDevice) -> str:
    token = _new_token()
    device.token_hash, device.token_last4 = _hash(token), token[-4:]
    audit.record("LTE 단말기 토큰 재발급", "TelematicsDevice", device.id, user_id=actor.id,
                 changes={"serial": device.serial})
    db.session.commit()
    return token


def set_enabled(actor: User, device: TelematicsDevice, enabled: bool) -> None:
    device.enabled = enabled
    audit.record("LTE 단말기 " + ("사용" if enabled else "중지"), "TelematicsDevice", device.id,
                 user_id=actor.id, changes={"serial": device.serial})
    db.session.commit()


def authenticate(authorization: str | None) -> TelematicsDevice:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme != "Device" or not token.strip():
        raise ServiceError(UNAUTHORIZED, 401)
    device = db.session.scalar(select(TelematicsDevice).where(TelematicsDevice.token_hash == _hash(token.strip())))
    if device is None or not device.enabled:
        raise ServiceError(UNAUTHORIZED, 401)
    device.last_seen_at = datetime.now(UTC)
    db.session.commit()
    return device


def _car(device: TelematicsDevice, car_no: str | None) -> tuple[dict | None, str | None]:
    """조회 결과와 실패 안내. 같은 차량은 저장된 결과를 써서 일일 한도를 아낀다."""
    try:
        dto, _ = car_info.lookup(device.registrar, car_no)
    except car_info.CarInfoError as error:
        return None, error.guide
    return dto, None


def plan_for(device: TelematicsDevice, car_no: str | None) -> dict[str, Any]:
    car, error = _car(device, car_no) if car_no else (None, None)
    plan = build_plan(car_info.normalize_dto(car) if car else None)
    return {"car_no": car_info.normalize_car_no(car_no), "car": car, "lookup_error": error, **plan}


def receive(device: TelematicsDevice, data: dict[str, Any]) -> Scan:
    car_no = data.get("car_no")
    car, error = _car(device, car_no) if car_no else (None, None)
    scan = scanner.run_scan(
        device.registrar, car_no=car_no, car=car, steps=data.get("steps"), transport="lte",
        device=f"{device.name} ({device.serial})", lookup_error=error, source=DatasetSource.LTE,
    )
    if device.company_id:
        scan.company_id = device.company_id
        db.session.commit()
    return scan
