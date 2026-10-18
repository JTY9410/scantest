"""관리자 회원관리 업무 규칙: 조회·검색·정보 수정."""

from dataclasses import dataclass
from typing import Any

from flask import current_app
from sqlalchemy import func, or_, select
from sqlalchemy.orm.exc import StaleDataError

from app.core import audit
from app.core.audit import Activity
from app.core.errors import ServiceError
from app.core.pagination import Page, clamp_page, paginate
from app.extensions import db
from app.modules.accounts.models import Company, User, UserType, digits_only
from app.modules.reports.models import Applog, CarMismatchReport
from app.modules.scans.models import Scan

CONFLICT = "다른 관리자가 먼저 이 회원 정보를 수정했습니다. 최신 내용을 확인한 뒤 다시 저장하세요."
SORTS = {
    "-created_at": (User.created_at.desc(), User.id.desc()),
    "created_at": (User.created_at.asc(), User.id.asc()),
    "name": (User.name.asc(), User.id.asc()),
    "tid": (User.tid.asc(),),
    "-last_login_at": (User.last_login_at.desc().nulls_last(), User.id.desc()),
}
STATUSES = {"active": "이용 중", "withdrawn": "탈퇴", "all": "전체"}


@dataclass
class MemberFilters:
    q: str = ""
    type: str = ""
    company_id: int | None = None
    status: str = "active"
    sort: str = "-created_at"
    page: int = 1

    @classmethod
    def from_args(cls, args: Any) -> "MemberFilters":
        try:
            company_id = int(args.get("company_id")) if args.get("company_id") else None
        except ValueError:
            company_id = None
        member_type = args.get("type", "")
        status = args.get("status", "active")
        sort = args.get("sort", "-created_at")
        return cls(
            q=(args.get("q") or "").strip()[:100],
            type=member_type if member_type in UserType.__members__.values() else "",
            company_id=company_id,
            status=status if status in STATUSES else "active",
            sort=sort if sort in SORTS else "-created_at",
            page=clamp_page(args.get("page")),
        )

    def query_args(self, **override: Any) -> dict[str, Any]:
        args = {
            "q": self.q or None,
            "type": self.type or None,
            "company_id": self.company_id,
            "status": self.status if self.status != "active" else None,
            "sort": self.sort if self.sort != "-created_at" else None,
            "page": self.page if self.page != 1 else None,
        }
        args.update(override)
        return {k: v for k, v in args.items() if v not in (None, "")}

    @property
    def active_count(self) -> int:
        return sum(bool(x) for x in (self.q, self.type, self.company_id, self.status != "active"))


def search_members(filters: MemberFilters) -> Page:
    stmt = select(User)
    if filters.status == "active":
        stmt = stmt.where(User.deleted_at.is_(None))
    elif filters.status == "withdrawn":
        stmt = stmt.where(User.deleted_at.is_not(None))
    if filters.type:
        stmt = stmt.where(User.type == filters.type)
    if filters.company_id:
        stmt = stmt.where(User.company_id == filters.company_id)
    if filters.q:
        pattern = f"%{filters.q}%"
        conditions = [User.tid.ilike(pattern), User.name.ilike(pattern), User.email.ilike(pattern)]
        digits = digits_only(filters.q)
        if digits and len(digits) >= 3:
            conditions.append(User.mobile.like(f"%{digits}%"))
        stmt = stmt.where(or_(*conditions))
    stmt = stmt.order_by(*SORTS[filters.sort])
    return paginate(stmt, filters.page, current_app.config["ADMIN_PAGE_SIZE"])


def companies() -> list[Company]:
    return list(
        db.session.scalars(
            select(Company).where(Company.deleted_at.is_(None)).order_by(Company.name)
        ).all()
    )


def get_member(user_id: int) -> User:
    user = db.session.get(User, user_id)
    if user is None:
        raise ServiceError("회원을 찾을 수 없습니다.", 404)
    return user


def member_summary(user: User) -> dict[str, Any]:
    def count(stmt) -> int:
        return db.session.scalar(stmt) or 0

    return {
        "scans_tested": count(
            select(func.count()).select_from(Scan).where(
                Scan.tester_id == user.id, Scan.deleted_at.is_(None)
            )
        ),
        "scans_owned": count(
            select(func.count()).select_from(Scan).where(
                Scan.owner_id == user.id, Scan.deleted_at.is_(None)
            )
        ),
        "applogs": count(select(func.count()).select_from(Applog).where(Applog.user_id == user.id)),
        "reports": count(
            select(func.count()).select_from(CarMismatchReport).where(
                CarMismatchReport.user_id == user.id, CarMismatchReport.deleted_at.is_(None)
            )
        ),
        "activities": list(
            db.session.scalars(
                select(Activity)
                .where(Activity.relation == "User", Activity.relation_id == user.id)
                .order_by(Activity.created_at.desc(), Activity.id.desc())
                .limit(10)
            ).all()
        ),
    }


def update_member(actor: User, user_id: int, data: dict[str, Any], version: int) -> User:
    user = get_member(user_id)
    if user.version != version:
        raise ServiceError(CONFLICT, 409)
    if user.id == actor.id and data.get("type") != UserType.ADMIN:
        raise ServiceError("본인의 관리자 유형은 바꿀 수 없습니다.")
    
    # 소유자에게는 고장코드 지우기 권한을 줄 수 없음 (2026-10-18 대표 결정)
    can_clear = bool(data.get("can_clear_dtc", False))
    if can_clear and data.get("type") == UserType.OWNER:
        raise ServiceError("소유자에게는 고장코드 지우기 권한을 줄 수 없습니다.")

    values = {
        "name": data["name"].strip(),
        "type": data["type"],
        "company_id": data.get("company_id") or None,
        "mobile": digits_only(data.get("mobile")) or None,
        "email": (data.get("email") or "").strip() or None,
        "biz_no": digits_only(data.get("biz_no")) or None,
        "can_clear_dtc": can_clear,
    }
    if values["email"]:
        taken = db.session.scalar(
            select(User.id).where(User.email == values["email"], User.id != user.id)
        )
        if taken:
            raise ServiceError("이미 다른 회원이 사용 중인 이메일입니다.")
    if values["company_id"] and db.session.get(Company, values["company_id"]) is None:
        raise ServiceError("존재하지 않는 회사입니다.")

    changes = {
        key: {"before": getattr(user, key), "after": value}
        for key, value in values.items()
        if getattr(user, key) != value
    }
    if not changes:
        return user
    for key, value in values.items():
        setattr(user, key, value)
    audit.record("회원 정보 수정", "User", user.id, user_id=actor.id, changes=changes)
    try:
        db.session.commit()
    except StaleDataError as exc:
        db.session.rollback()
        raise ServiceError(CONFLICT, 409) from exc
    return user
