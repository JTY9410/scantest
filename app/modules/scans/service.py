"""스캔 데이터 권한 규칙.

- admin: 전체 조회·수정·삭제
- owner: owner_id가 본인인 스캔만 조회·수정, 생성·삭제 불가
- tester: tester_id가 본인인 스캔만 조회·수정·삭제, 생성 시 tester_id는 본인으로 고정
"""

import json
from typing import Any

from sqlalchemy import Select, false, select

from app.core.errors import ServiceError
from app.core.time import utcnow
from app.extensions import db
from app.modules.accounts.models import User, UserType
from app.modules.scans.models import Scan

NOT_FOUND = "해당 항목을 찾을 수 없습니다."
FORBIDDEN = "권한이 없습니다."


def visible_scans(user: User) -> Select:
    stmt = select(Scan).where(Scan.deleted_at.is_(None))
    if user.type == UserType.ADMIN:
        return stmt
    if user.type == UserType.OWNER:
        return stmt.where(Scan.owner_id == user.id)
    if user.type == UserType.TESTER:
        return stmt.where(Scan.tester_id == user.id)
    return stmt.where(false())


def get_visible_scan(user: User, scan_id: int, options: list | None = None) -> Scan:
    stmt = visible_scans(user).where(Scan.id == scan_id)
    if options:
        stmt = stmt.options(*options)
    scan = db.session.scalar(stmt)
    if scan is None:
        raise ServiceError(NOT_FOUND, 404)
    return scan


def _prepare(data: dict[str, Any]) -> dict[str, Any]:
    data = dict(data)
    if isinstance(data.get("bms_data"), str):
        data["bms_data"] = json.loads(data["bms_data"])
    for key in ("owner_id", "tester_id", "company_id", "car_cc", "car_year", "car_distance"):
        if data.get(key) is not None:
            data[key] = int(data[key])
    return data


def create_scan(user: User, data: dict[str, Any]) -> Scan:
    if user.type == UserType.OWNER:
        raise ServiceError("오너는 생성할 수 없습니다.", 403)
    values = _prepare(data)
    if user.type == UserType.TESTER:
        values["tester_id"] = user.id
        values["owner_id"] = None
    scan = Scan(**values)
    db.session.add(scan)
    db.session.commit()
    return scan


def update_scan(user: User, scan_id: int, data: dict[str, Any]) -> Scan:
    scan = get_visible_scan(user, scan_id)
    for key, value in _prepare(data).items():
        setattr(scan, key, value)
    db.session.commit()
    return scan


def delete_scan(user: User, scan_id: int) -> None:
    scan = get_visible_scan(user, scan_id)
    allowed = user.type == UserType.ADMIN or (
        user.type == UserType.TESTER and scan.tester_id == user.id
    )
    if not allowed:
        raise ServiceError(FORBIDDEN, 403)
    scan.deleted_at = utcnow()
    db.session.commit()
