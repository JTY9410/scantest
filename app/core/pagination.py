import math
from dataclasses import dataclass
from typing import Any

from flask import current_app
from sqlalchemy import Select, func, select

from app.extensions import db


@dataclass
class Page:
    items: list[Any]
    page: int
    per_page: int
    total: int

    @property
    def last_page(self) -> int:
        return max(1, math.ceil(self.total / self.per_page))

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.last_page

    @property
    def first_index(self) -> int | None:
        return (self.page - 1) * self.per_page + 1 if self.items else None

    @property
    def last_index(self) -> int | None:
        return (self.page - 1) * self.per_page + len(self.items) if self.items else None


def clamp_page(value: Any, default: int = 1) -> int:
    try:
        page = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, page)


def clamp_per_page(value: Any, default: int | None = None) -> int:
    default = default or current_app.config["PAGE_SIZE_DEFAULT"]
    try:
        size = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(1, size), current_app.config["PAGE_SIZE_MAX"])


def paginate(stmt: Select, page: int, per_page: int) -> Page:
    total = db.session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    items = db.session.scalars(stmt.limit(per_page).offset((page - 1) * per_page)).unique().all()
    return Page(items=list(items), page=page, per_page=per_page, total=total or 0)
