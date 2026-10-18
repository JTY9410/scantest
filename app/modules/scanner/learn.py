"""제조사·차종별로 실제로 응답한 읽기 명령을 기억하고 다음 스캔 계획에 넣는다."""

import re
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.extensions import db
from app.modules.scans.models import MakerScanCommand, Scan

_READ = re.compile(r"^([0-9A-F]{2}){1,8}$")
_SKIP = {"04", "14FFFFFF"}
_BLOCKED = {"10", "27", "2E", "31"}
_LIMIT = 40


def _now() -> datetime:
    return datetime.now(UTC)


def _upsert(maker: str, model: str | None, header: str | None, command: str, scan_id: int) -> None:
    existing = db.session.scalar(select(MakerScanCommand).where(
        MakerScanCommand.maker == maker,
        MakerScanCommand.model.is_(None) if model is None else MakerScanCommand.model == model,
        MakerScanCommand.header.is_(None) if header is None else MakerScanCommand.header == header,
        MakerScanCommand.command == command))
    if existing is None:
        count = db.session.scalar(select(func.count()).select_from(MakerScanCommand).where(
            MakerScanCommand.maker == maker,
            MakerScanCommand.model.is_(None) if model is None else MakerScanCommand.model == model))
        if (count or 0) >= _LIMIT:
            return
        db.session.add(MakerScanCommand(
            maker=maker, model=model, header=header, command=command, hits=1,
            last_scan_id=scan_id, last_seen=_now()))
        return
    existing.hits += 1
    existing.last_scan_id = scan_id
    existing.last_seen = _now()


def remember(scan: Scan, steps: list[dict]) -> None:
    """성공한 읽기 명령만 건수를 올린다. AT·지우기·ELM 오류·NO DATA·7F·세션·쓰기 명령은 남기지 않는다."""
    maker = (scan.car_maker or "").strip()
    if not maker:
        return
    model = (scan.car_model or "").strip() if scan.car_model and scan.car_model != "미확인" else None
    seen: set[tuple[str | None, str]] = set()
    for step in steps:
        if step.get("status") != "ok":
            continue
        command = re.sub(r"\s+", "", str(step.get("command") or "")).upper()
        if (command in _SKIP or command.startswith("AT") or not _READ.fullmatch(command)
                or command[:2] in _BLOCKED):
            continue
        header = (str(step.get("header")).strip().upper() if step.get("header") else None) or None
        if (header, command) in seen:
            continue
        seen.add((header, command))
        _upsert(maker, model, header, command, scan.id)
        if model:
            _upsert(maker, None, header, command, scan.id)
    db.session.flush()


def learned_requests(car: dict | None) -> list[dict]:
    """차종 기록이 있으면 그것만, 없으면 제조사 공통(model 없음)을 돌려준다."""
    maker = str((car or {}).get("diag_company") or "").strip()
    if not maker:
        return []
    model = str((car or {}).get("diag_model") or "").strip() or None
    rows = []
    if model:
        rows = list(db.session.scalars(select(MakerScanCommand).where(
            MakerScanCommand.maker == maker, MakerScanCommand.model == model)
            .order_by(MakerScanCommand.hits.desc(), MakerScanCommand.id.desc()).limit(_LIMIT)))
    if not rows:
        rows = list(db.session.scalars(select(MakerScanCommand).where(
            MakerScanCommand.maker == maker, MakerScanCommand.model.is_(None))
            .order_by(MakerScanCommand.hits.desc(), MakerScanCommand.id.desc()).limit(_LIMIT)))
    return [{"header": row.header, "command": row.command, "hits": row.hits} for row in rows]


def list_commands(maker: str = "") -> list[MakerScanCommand]:
    stmt = select(MakerScanCommand).order_by(
        MakerScanCommand.maker, MakerScanCommand.hits.desc(), MakerScanCommand.id.desc())
    if maker:
        stmt = stmt.where(MakerScanCommand.maker.ilike(f"%{maker[:50]}%"))
    return list(db.session.scalars(stmt.limit(200)))


def answered_commands(steps: list[dict] | None) -> list[dict]:
    """이 스캔에서 응답한 읽기 명령. AT 명령은 빼 둔다."""
    found, seen = [], set()
    for step in steps or []:
        if step.get("status") != "ok":
            continue
        command = re.sub(r"\s+", "", str(step.get("command") or "")).upper()
        if not command or command.startswith("AT"):
            continue
        header = step.get("header") or None
        if (header, command) in seen:
            continue
        seen.add((header, command))
        found.append({"header": header, "command": command, "label": step.get("label")})
    return found
