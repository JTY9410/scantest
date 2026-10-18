"""고장코드 지우기 저장·권한(2026-10-18 대표 결정). 계획·판정은 scanner/clear.py."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from flask import has_request_context, request
from sqlalchemy import select

from app.core import audit
from app.core.errors import ServiceError
from app.extensions import db
from app.modules.accounts.models import User, UserType
from app.modules.scanner import clear
from app.modules.scanner.service import clean_steps
from app.modules.scans import car_info
from app.modules.scans.models import DtcClearLog, Scan

TOKEN_MINUTES = 20  # 응답한 모든 제어기를 지우면(NRC 78 대기 포함) 10분을 넘길 수 있다
SNAPSHOT_MINUTES = 30


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def check_permission(user: User, *, source: str) -> None:
    """웹: 관리자 + MFA + can_clear_dtc. 앱: 관리자·테스터 + can_clear_dtc. 소유자는 언제나 불가."""
    if not getattr(user, "can_clear_dtc", False):
        raise ServiceError("고장코드 지우기 권한이 없습니다. 회원 관리에서 권한을 받으세요.", 403)
    if source == "web" and not (user.is_admin and user.mfa_enabled):
        raise ServiceError("고장코드 지우기는 2단계 인증(MFA)을 켠 관리자만 할 수 있습니다.", 403)
    if source == "app" and user.type not in (UserType.ADMIN, UserType.TESTER):
        raise ServiceError("고장코드 지우기 권한이 없습니다.", 403)


def _result_of(scan: Scan) -> dict:
    data = scan.bms_data or {}
    return {"dtcs": data.get("dtcs") or [], "protocol": data.get("protocol") or {},
            "ecus": data.get("ecus") or [], "steps": data.get("steps") or []}


def issue(actor: User, scan: Scan, *, car_no: Any, conditions: Any, source: str) -> dict:
    """확인 창 입력을 검사하고 1회용 지우기 계획을 발급한다. 발급도 감사기록에 남긴다."""
    check_permission(actor, source=source)
    if scan.car_no and car_info.normalize_car_no(car_no) != car_info.normalize_car_no(scan.car_no):
        raise ServiceError("확인용 차량번호가 스캔한 차량과 다릅니다.", 400)
    if conditions is not True:
        raise ServiceError("정차·시동 OFF(IG ON) 상태를 확인해야 지울 수 있습니다.", 400)
    created = _aware(scan.created_at)
    if created is None or _now() - created > timedelta(minutes=SNAPSHOT_MINUTES):
        raise ServiceError(f"지우기 전 스캔이 {SNAPSHOT_MINUTES}분보다 오래되었습니다. 다시 스캔한 뒤 지우세요.", 409)
    if (scan.bms_data or {}).get("source") != "scanner":
        raise ServiceError("스캔하기로 저장한 스캔에서만 지울 수 있습니다.", 409)

    before = _result_of(scan)
    built = clear.build_clear_plan(before)
    token = secrets.token_urlsafe(32)
    log = DtcClearLog(
        scan_id=scan.id, user_id=actor.id, ip=(request.remote_addr or "") if has_request_context() else "cli",
        source=source, car_no=scan.car_no, vin=scan.scan_vin or scan.car_vin, status="issued",
        token_hash=_hash(token), expires_at=_now() + timedelta(minutes=TOKEN_MINUTES),
        targets=built["targets"], dtcs_before=[d.get("code") for d in before["dtcs"] if d.get("code")],
        created_at=_now(),
    )
    db.session.add(log)
    db.session.flush()
    audit.record("dtc_clear_issued", "Scan", scan.id, user_id=actor.id,
                 changes={"log_id": log.id, "vin": log.vin, "car_no": log.car_no, "targets": log.targets,
                          "dtc_count": len(log.dtcs_before), "source": source})
    db.session.commit()
    return {"log_id": log.id, "token": token, "expires_at": log.expires_at.isoformat(),
            "targets": built["targets"], "steps": built["steps"]}


def save(actor: User, scan: Scan, *, token: Any, steps: Any) -> DtcClearLog:
    """지우기 결과를 판정해 저장한다. 토큰은 한 번만 쓴다."""
    if not isinstance(token, str) or not token:
        raise ServiceError("지우기 계획 토큰이 없습니다.", 400)
    log = db.session.scalar(select(DtcClearLog).where(DtcClearLog.token_hash == _hash(token)))
    if log is None or log.scan_id != scan.id or log.user_id != actor.id:
        raise ServiceError("발급한 지우기 계획이 아닙니다.", 403)
    if log.status != "issued":
        raise ServiceError("이미 결과를 저장한 지우기 계획입니다.", 409)
    if _now() > _aware(log.expires_at):
        log.status, log.finished_at = "expired", _now()
        db.session.commit()
        raise ServiceError("지우기 계획 유효시간이 지났습니다. 다시 확인한 뒤 지우세요.", 409)
    cleaned = clean_steps(steps)
    if problem := clear.validate_results(cleaned, log.targets):
        raise ServiceError(problem, 400)
    bus = ((scan.bms_data or {}).get("protocol") or {}).get("bus")
    outcome = clear.evaluate_clear(cleaned, bus, log.dtcs_before)
    log.status, log.result, log.steps, log.finished_at = outcome["status"], outcome, cleaned, _now()
    audit.record("dtc_clear", "Scan", scan.id, user_id=actor.id,
                 changes={"log_id": log.id, "vin": log.vin, "car_no": log.car_no, "status": outcome["status"],
                          "ecus": {e["header"]: e["status"] for e in outcome["ecus"]},
                          "obd04": (outcome["obd04"] or {}).get("status"), "cleared": outcome["cleared"],
                          "remaining": outcome["remaining"], "session_used": outcome["session_used"]})
    db.session.commit()
    return log
