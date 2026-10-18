"""조회 전용 관리 화면(스캔·활동 기록·앱 로그·불일치 신고) 질의."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.core.audit import Activity
from app.core.errors import ServiceError
from app.core.pagination import Page, paginate
from app.extensions import db
from app.modules.accounts.models import User
from app.modules.reports.models import Applog, CarMismatchReport
from app.modules.scans.models import DtcClearLog, Scan, ScanCode

SEOUL = ZoneInfo("Asia/Seoul")


def parse_day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _day_range(column, start: date | None, end: date | None) -> list:
    conditions = []
    if start:
        conditions.append(column >= datetime.combine(start, time.min, SEOUL))
    if end:
        conditions.append(column < datetime.combine(end + timedelta(days=1), time.min, SEOUL))
    return conditions


def _size() -> int:
    return current_app.config["ADMIN_PAGE_SIZE"]


def search_scans(*, q: str, scan_type: str, user_id: int | None, start: date | None,
                 end: date | None, page: int, device: str = "", maker: str = "", model: str = "") -> Page:
    stmt = (
        select(Scan)
        .options(joinedload(Scan.tester), joinedload(Scan.owner), joinedload(Scan.company),
                 selectinload(Scan.scan_codes))
        .where(Scan.deleted_at.is_(None), *_day_range(Scan.created_at, start, end))
    )
    if scan_type in ("ev", "ice"):
        stmt = stmt.where(Scan.type == scan_type)
    if user_id:
        stmt = stmt.where(or_(Scan.tester_id == user_id, Scan.owner_id == user_id))
    if device:
        stmt = stmt.where(Scan.device_uid.ilike(f"%{device.strip()[:100]}%"))
    if maker:
        stmt = stmt.where(Scan.car_maker.ilike(f"%{maker.strip()[:50]}%"))
    if model:
        stmt = stmt.where(Scan.car_model.ilike(f"%{model.strip()[:50]}%"))
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(Scan.car_no.ilike(pattern), Scan.car_vin.ilike(pattern),
                              Scan.scan_vin.ilike(pattern), Scan.car_model.ilike(pattern)))
    return paginate(stmt.order_by(Scan.created_at.desc(), Scan.id.desc()), page, _size())


def get_scan(scan_id: int) -> Scan:
    scan = db.session.scalar(
        select(Scan)
        .options(
            joinedload(Scan.tester), joinedload(Scan.owner), joinedload(Scan.company),
            selectinload(Scan.scan_codes).joinedload(ScanCode.code),
        )
        .where(Scan.id == scan_id, Scan.deleted_at.is_(None))
    )
    if scan is None:
        raise ServiceError("스캔 기록을 찾을 수 없습니다.", 404)
    return scan


def get_scan_clear_logs(scan_id: int) -> list[DtcClearLog]:
    """스캔의 고장코드 지우기 이력을 최신순으로 반환한다."""
    return list(
        db.session.scalars(
            select(DtcClearLog)
            .options(joinedload(DtcClearLog.user))
            .where(DtcClearLog.scan_id == scan_id)
            .order_by(DtcClearLog.created_at.desc(), DtcClearLog.id.desc())
        ).all()
    )


def search_activities(*, q: str, relation: str, start: date | None, end: date | None,
                      page: int) -> Page:
    stmt = select(Activity).options(joinedload(Activity.user)).where(
        *_day_range(Activity.created_at, start, end)
    )
    if relation:
        stmt = stmt.where(Activity.relation == relation)
    if q:
        stmt = stmt.where(or_(Activity.relation_type.ilike(f"%{q}%"),
                              Activity.message.ilike(f"%{q}%")))
    return paginate(stmt.order_by(Activity.created_at.desc(), Activity.id.desc()), page, _size())


def activity_relations() -> list[str]:
    return list(db.session.scalars(
        select(Activity.relation).where(Activity.relation.is_not(None))
        .distinct().order_by(Activity.relation)
    ).all())


def search_applogs(*, q: str, log_type: str, user_id: int | None, start: date | None,
                   end: date | None, page: int) -> Page:
    stmt = select(Applog).options(joinedload(Applog.user)).where(
        *_day_range(Applog.timestamp, start, end)
    )
    if log_type:
        stmt = stmt.where(Applog.type == log_type)
    if user_id:
        stmt = stmt.where(Applog.user_id == user_id)
    if q:
        stmt = stmt.where(or_(Applog.message.ilike(f"%{q}%"), Applog.desc.ilike(f"%{q}%")))
    return paginate(stmt.order_by(Applog.timestamp.desc(), Applog.id.desc()), page, _size())


def applog_types() -> list[str]:
    return list(db.session.scalars(select(Applog.type).distinct().order_by(Applog.type)).all())


def search_reports(*, q: str, user_id: int | None, start: date | None, end: date | None,
                   page: int) -> Page:
    stmt = select(CarMismatchReport).options(joinedload(CarMismatchReport.user)).where(
        CarMismatchReport.deleted_at.is_(None),
        *_day_range(CarMismatchReport.created_at, start, end),
    )
    if user_id:
        stmt = stmt.where(CarMismatchReport.user_id == user_id)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(CarMismatchReport.car_no.ilike(pattern),
                              CarMismatchReport.api_vin.ilike(pattern),
                              CarMismatchReport.scan_vin.ilike(pattern)))
    return paginate(stmt.order_by(CarMismatchReport.created_at.desc(), CarMismatchReport.id.desc()),
                    page, _size())


def member_name(user_id: int | None) -> User | None:
    return db.session.get(User, user_id) if user_id else None
