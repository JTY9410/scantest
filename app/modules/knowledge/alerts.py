"""검증 명령의 실제 동작 확인과 삭제 여부 알림.

스캔 결과의 단계 상태로 명령마다 성공·실패를 센다.
- 성공: ok
- 실패: no_data(응답 없음), negative(거부 응답), timeout, unsupported(차량·ECU 미지원)
- 세지 않음: device_error·disconnected(단말기 문제), skipped·pending
기준(설정 COMMAND_ALERT_*)을 넘으면 대기(pending) 알림을 하나 만든다. 같은 명령에 대기 알림이 있으면
새로 만들지 않는다. 관리자가 "삭제"를 누르면 명령을 지우고, "유지"를 누르면 누적을 0으로 돌려
새 실패가 다시 기준을 넘을 때까지 알리지 않는다. 자동 삭제는 하지 않는다.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from flask import current_app
from sqlalchemy import or_, select

from app.core.errors import ServiceError
from app.core.makers import maker_aliases, normalize_maker
from app.extensions import db
from app.modules.knowledge.models import (
    CommandDeletionAlert,
    CommandHealth,
    KnowledgeCommand,
    PromotionLog,
)

SUCCESS = {"ok"}
FAILURE = {"no_data", "negative", "timeout", "unsupported"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _thresholds() -> tuple[int, int, float]:
    cfg = current_app.config
    return (int(cfg.get("COMMAND_ALERT_CONSECUTIVE", 5)), int(cfg.get("COMMAND_ALERT_MIN_ATTEMPTS", 20)),
            float(cfg.get("COMMAND_ALERT_FAILURE_RATE", 0.8)))


def _match(maker: str | None, header: str | None, command: str) -> list[KnowledgeCommand]:
    scope = KnowledgeCommand.maker.is_(None)
    if normalize_maker(maker):
        scope = or_(KnowledgeCommand.maker.in_(maker_aliases(maker)), scope)
    stmt = select(KnowledgeCommand).where(KnowledgeCommand.status == "verified",
                                          KnowledgeCommand.command == command, scope)
    rows = db.session.scalars(stmt).all()
    exact = [r for r in rows if (r.header or "").upper() == (header or "")]
    return exact or [r for r in rows if not r.header]


def should_alert(health: CommandHealth) -> str | None:
    consecutive, min_attempts, rate = _thresholds()
    if health.consecutive_failures >= consecutive:
        return f"실제 스캔에서 {health.consecutive_failures}회 연속 동작하지 않았습니다(기준 {consecutive}회)."
    if health.attempts >= min_attempts and health.failures / health.attempts >= rate:
        return (f"최근 {health.attempts}회 중 {health.failures}회 동작하지 않았습니다"
                f"(기준 {min_attempts}회 이상·실패율 {rate:.0%}).")
    return None


def record_command_outcomes(maker: str | None, steps: list[dict], scan_id: int | None = None) -> int:
    """스캔 한 번의 단계 결과를 검증 명령별로 누적하고, 기준을 넘으면 알림을 만든다. 만든 알림 수를 돌려준다."""
    created = 0
    seen: set[int] = set()
    now = _now()
    for step in steps or []:
        status = step.get("status")
        if status not in SUCCESS and status not in FAILURE:
            continue
        command = re.sub(r"\s+", "", str(step.get("command") or "")).upper()
        if not command or command.startswith("AT"):
            continue
        header = (str(step.get("header")).strip().upper() if step.get("header") else None)
        for row in _match(maker, header, command):
            if row.id in seen:
                continue
            seen.add(row.id)
            health = db.session.scalar(select(CommandHealth).where(CommandHealth.command_id == row.id))
            if health is None:
                health = CommandHealth(command_id=row.id, attempts=0, failures=0, consecutive_failures=0)
                db.session.add(health)
            health.attempts += 1
            health.last_status = status
            health.last_scan_id = scan_id
            if status in SUCCESS:
                health.consecutive_failures = 0
                health.last_ok_at = now
                continue
            health.failures += 1
            health.consecutive_failures += 1
            health.last_failed_at = now
            reason = should_alert(health)
            if reason and not _pending(row.id):
                db.session.add(CommandDeletionAlert(
                    command_id=row.id, maker=row.maker, header=row.header, command=row.command,
                    label=row.label, status="pending", reason=reason, attempts=health.attempts,
                    failures=health.failures, consecutive_failures=health.consecutive_failures,
                    last_status=status, created_at=now))
                created += 1
                current_app.logger.warning("검증 명령 삭제 여부 알림: %s %s (%s)", row.header, row.command, reason)
    if seen:
        db.session.flush()
    return created


def _pending(command_id: int) -> CommandDeletionAlert | None:
    return db.session.scalar(select(CommandDeletionAlert).where(
        CommandDeletionAlert.command_id == command_id, CommandDeletionAlert.status == "pending"))


def pending_alerts(limit: int = 100) -> list[CommandDeletionAlert]:
    return list(db.session.scalars(select(CommandDeletionAlert).where(CommandDeletionAlert.status == "pending")
                                   .order_by(CommandDeletionAlert.created_at.desc()).limit(limit)))


def pending_count() -> int:
    from sqlalchemy import func
    return db.session.scalar(select(func.count()).select_from(CommandDeletionAlert)
                             .where(CommandDeletionAlert.status == "pending")) or 0


def _get_pending(alert_id: int) -> CommandDeletionAlert:
    alert = db.session.get(CommandDeletionAlert, alert_id)
    if alert is None or alert.status != "pending":
        raise ServiceError("처리할 알림을 찾지 못했습니다.")
    return alert


def resolve_delete(alert_id: int, user_id: int | None) -> None:
    """관리자가 "삭제"를 눌렀을 때만 명령을 지운다. 감사 기록을 promotion_log에 남긴다."""
    alert = _get_pending(alert_id)
    now = _now()
    cmd = db.session.get(KnowledgeCommand, alert.command_id)
    if cmd is not None:
        db.session.add(PromotionLog(entity_type="command", entity_id=cmd.id, old_status=cmd.status,
                                    new_status="deleted", promoted_by=user_id, promoted_at=now,
                                    evidence=alert.reason,
                                    notes=f"삭제 알림 #{alert.id}에서 관리자가 삭제: {cmd.header or '-'} {cmd.command}"))
        db.session.delete(cmd)
    health = db.session.scalar(select(CommandHealth).where(CommandHealth.command_id == alert.command_id))
    if health is not None:
        db.session.delete(health)
    alert.status, alert.resolved_at, alert.resolved_by = "deleted", now, user_id
    db.session.commit()


def resolve_keep(alert_id: int, user_id: int | None) -> None:
    """"유지": 명령을 그대로 두고 누적을 0으로 돌린다. 새 실패가 기준을 다시 넘을 때만 다시 알린다."""
    alert = _get_pending(alert_id)
    now = _now()
    health = db.session.scalar(select(CommandHealth).where(CommandHealth.command_id == alert.command_id))
    if health is not None:
        health.attempts = health.failures = health.consecutive_failures = 0
    db.session.add(PromotionLog(entity_type="command", entity_id=alert.command_id, old_status="verified",
                                new_status="verified", promoted_by=user_id, promoted_at=now,
                                evidence=alert.reason, notes=f"삭제 알림 #{alert.id}에서 관리자가 유지"))
    alert.status, alert.resolved_at, alert.resolved_by = "kept", now, user_id
    db.session.commit()
