"""불일치 신고·앱 로그 권한 규칙: 관리자는 전체, 그 외 회원은 본인 기록만."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, or_, select

from app.core.errors import ServiceError
from app.extensions import db
from app.modules.accounts.models import User, UserType
from app.modules.reports.models import Applog, CarMismatchReport

NOT_FOUND = "해당 항목을 찾을 수 없습니다."


def visible_reports(user: User) -> Select:
    stmt = select(CarMismatchReport).where(CarMismatchReport.deleted_at.is_(None))
    if user.type != UserType.ADMIN:
        stmt = stmt.where(CarMismatchReport.user_id == user.id)
    return stmt


def get_report(user: User, report_id: int, options: list | None = None) -> CarMismatchReport:
    stmt = visible_reports(user).where(CarMismatchReport.id == report_id)
    if options:
        stmt = stmt.options(*options)
    report = db.session.scalar(stmt)
    if report is None:
        raise ServiceError(NOT_FOUND, 404)
    return report


def create_report(user: User, data: dict[str, Any]) -> CarMismatchReport:
    report = CarMismatchReport(user_id=user.id, **data)
    db.session.add(report)
    db.session.commit()
    return report


def visible_applogs(user: User, filters: dict[str, Any]) -> Select:
    stmt = select(Applog)
    if user.type != UserType.ADMIN:
        stmt = stmt.where(Applog.user_id == user.id)
    elif filters.get("user_id") is not None:
        try:
            stmt = stmt.where(Applog.user_id == int(filters["user_id"]))
        except (TypeError, ValueError) as exc:
            raise ServiceError("user_id 형식이 올바르지 않습니다.") from exc
    if filters.get("type") is not None:
        stmt = stmt.where(Applog.type == str(filters["type"]))
    search = filters.get("search")
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(Applog.type.ilike(pattern), Applog.message.ilike(pattern), Applog.desc.ilike(pattern))
        )
    return stmt.order_by(Applog.created_at.desc(), Applog.id.desc())


def get_applog(user: User, log_id: int) -> Applog:
    stmt = select(Applog).where(Applog.id == log_id)
    if user.type != UserType.ADMIN:
        stmt = stmt.where(Applog.user_id == user.id)
    log = db.session.scalar(stmt)
    if log is None:
        raise ServiceError(NOT_FOUND, 404)
    return log


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def create_applog(user: User, data: dict[str, Any]) -> Applog:
    user_id = data.get("user_id")
    if user.type != UserType.ADMIN or user_id is None:
        user_id = user.id
    log = Applog(
        timestamp=parse_timestamp(data["timestamp"]),
        user_id=int(user_id),
        type=data["type"],
        message=data["message"],
        desc=data.get("desc"),
    )
    db.session.add(log)
    db.session.commit()
    return log
