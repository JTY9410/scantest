"""지식베이스 조회·검증·스캔 연결."""
import json
import re
from sqlalchemy import or_, select

from app.core.time import utcnow
from app.extensions import db
from app.modules.knowledge.models import (
    KnowledgeCommand,
    KnowledgeDTC,
    KnowledgeFormula,
    KnowledgeTerm,
)


def list_commands(*, status: str = "verified", maker: str | None = None, limit: int = 100):
    """스캔 계획에 쓸 명령. 기본은 검증된 항목만."""
    stmt = select(KnowledgeCommand).where(KnowledgeCommand.status == status).order_by(KnowledgeCommand.command)
    if maker:
        stmt = stmt.where(or_(KnowledgeCommand.maker == maker, KnowledgeCommand.maker.is_(None)))
    stmt = stmt.limit(limit)
    return db.session.scalars(stmt).all()


def list_formulas(*, status: str = "verified", maker: str | None = None, limit: int = 100):
    """해석에 쓸 수식. 기본은 검증된 항목만."""
    stmt = select(KnowledgeFormula).where(KnowledgeFormula.status == status).order_by(KnowledgeFormula.pid)
    if maker:
        stmt = stmt.where(or_(KnowledgeFormula.maker == maker, KnowledgeFormula.maker.is_(None)))
    stmt = stmt.limit(limit)
    return db.session.scalars(stmt).all()


def list_dtcs(*, status: str = "verified", maker: str | None = None, limit: int = 1000):
    """고장코드 뜻. 기본은 검증된 항목만."""
    stmt = select(KnowledgeDTC).where(KnowledgeDTC.status == status).order_by(KnowledgeDTC.code)
    if maker:
        stmt = stmt.where(or_(KnowledgeDTC.maker == maker, KnowledgeDTC.maker.is_(None)))
    stmt = stmt.limit(limit)
    return db.session.scalars(stmt).all()


def list_terms(*, status: str = "verified", limit: int = 500):
    """용어 목록."""
    stmt = select(KnowledgeTerm).where(KnowledgeTerm.status == status).order_by(KnowledgeTerm.term).limit(limit)
    return db.session.scalars(stmt).all()


def verify_command(command_id: int, user_id: int):
    """명령을 검증됨으로 표시한다."""
    cmd = db.session.get(KnowledgeCommand, command_id)
    if cmd:
        cmd.status = "verified"
        cmd.verified_by = user_id
        cmd.verified_at = utcnow()
        db.session.commit()


def verify_formula(formula_id: int, user_id: int):
    """수식을 검증됨으로 표시한다."""
    formula = db.session.get(KnowledgeFormula, formula_id)
    if formula:
        formula.status = "verified"
        formula.verified_by = user_id
        formula.verified_at = utcnow()
        db.session.commit()


def verify_dtc(dtc_id: int, user_id: int):
    """고장코드 뜻을 검증됨으로 표시한다."""
    dtc = db.session.get(KnowledgeDTC, dtc_id)
    if dtc:
        dtc.status = "verified"
        dtc.verified_by = user_id
        dtc.verified_at = utcnow()
        db.session.commit()


def import_from_commands_json(commands_data: list[dict]) -> int:
    """위스캔 분석 commands.json의 명령을 검증된 지식으로 넣는다."""
    count = 0
    for cmd_data in commands_data:
        # Check if already exists
        existing = db.session.scalar(
            select(KnowledgeCommand).where(
                KnowledgeCommand.command == cmd_data.get("command"),
                KnowledgeCommand.source == "wescan",
            ).limit(1)
        )
        if existing:
            continue
        
        cmd = KnowledgeCommand(
            maker=cmd_data.get("maker"),
            model=cmd_data.get("model"),
            ecu_name=cmd_data.get("ecu"),
            header=cmd_data.get("header"),
            command=cmd_data.get("command"),
            label=cmd_data.get("label"),
            description=cmd_data.get("description"),
            source="wescan",
            source_detail=cmd_data.get("source_detail", "위스캔 앱 분석에서 가져옴"),
            confidence=1.0,
            status="verified",
        )
        db.session.add(cmd)
        count += 1
    
    db.session.commit()
    return count


_READ = re.compile(r"^([0-9A-F]{2}){1,8}$")
_BLOCKED = {"10", "27", "2E", "31"}


def _scope(maker: str | None):
    if maker:
        return or_(KnowledgeCommand.maker == maker, KnowledgeCommand.maker.is_(None))
    return KnowledgeCommand.maker.is_(None)


def scan_commands(maker: str | None = None, limit: int = 40) -> list[dict]:
    """스캔 계획에 넣을 검증된 읽기 명령. 세션·보안·쓰기·루틴은 빼니다."""
    stmt = select(KnowledgeCommand).where(KnowledgeCommand.status == "verified", _scope(maker))
    rows = []
    for row in db.session.scalars(stmt.order_by(KnowledgeCommand.id.desc()).limit(limit * 2)):
        command = re.sub(r"\s+", "", row.command or "").upper()
        if not _READ.fullmatch(command) or command[:2] in _BLOCKED:
            continue
        header = (row.header or "").strip().upper() or None
        rows.append({"header": header, "command": command, "label": row.label or command})
        if len(rows) >= limit:
            break
    return rows


def verified_layouts(maker: str | None = None, limit: int = 40) -> list[dict]:
    """적용 규칙이 없는 신호를 읽을 검증 수식. source_detail에 layout·signal_key가 있을 때만."""
    stmt = select(KnowledgeFormula).where(KnowledgeFormula.status == "verified")
    if maker:
        stmt = stmt.where(or_(KnowledgeFormula.maker == maker, KnowledgeFormula.maker.is_(None)))
    else:
        stmt = stmt.where(KnowledgeFormula.maker.is_(None))
    found = []
    for row in db.session.scalars(stmt.order_by(KnowledgeFormula.id.desc()).limit(limit * 2)):
        try:
            detail = json.loads(row.source_detail or "")
            layout = detail["layout"]
            signal_key = detail["signal_key"]
        except (TypeError, ValueError, KeyError):
            continue
        found.append({"signal_key": signal_key, "layout": layout, "label": row.label, "unit": row.unit,
                      "formula": row.formula})
        if len(found) >= limit:
            break
    return found


def _command_row(maker, model, header, command) -> KnowledgeCommand | None:
    return db.session.scalar(select(KnowledgeCommand).where(
        KnowledgeCommand.maker == maker if maker else KnowledgeCommand.maker.is_(None),
        KnowledgeCommand.model == model if model else KnowledgeCommand.model.is_(None),
        KnowledgeCommand.header == header if header else KnowledgeCommand.header.is_(None),
        KnowledgeCommand.command == command,
        KnowledgeCommand.source == "reverse_analysis",
    ))


def remember_command(*, maker: str | None, model: str | None, header: str | None, command: str,
                     label: str | None, user_id: int | None) -> None:
    """역분석에서 적용한 읽기 명령을 검증된 지식으로 남긴다."""
    command = re.sub(r"\s+", "", command or "").upper()
    if not _READ.fullmatch(command) or command[:2] in _BLOCKED:
        return
    header = (header or "").strip().upper() or None
    existing = _command_row(maker, model, header, command)
    now = utcnow()
    if existing is None:
        db.session.add(KnowledgeCommand(
            maker=maker, model=model, header=header, command=command, label=(label or command)[:200],
            source="reverse_analysis", source_detail="적용된 스캔 로직", confidence=1.0, status="verified",
            verified_by=user_id, verified_at=now))
        return
    existing.status = "verified"
    existing.label = (label or existing.label or command)[:200]
    existing.verified_by = user_id
    existing.verified_at = now


def remember_formula(*, maker: str | None, model: str | None, signal_key: str, layout: dict,
                     formula: str, label: str, user_id: int | None) -> None:
    """적용된 디코딩 규칙을 검증 수식으로 남긴다. 배치는 source_detail에 둔다."""
    formula = (formula or "")[:5000]
    did = str(layout.get("did") or "")
    header = str(layout.get("request_id") or "")
    command = f"22{did}" if did else None
    detail = json.dumps({"signal_key": signal_key, "layout": layout}, ensure_ascii=False)
    existing = db.session.scalar(select(KnowledgeFormula).where(
        KnowledgeFormula.maker == maker if maker else KnowledgeFormula.maker.is_(None),
        KnowledgeFormula.model == model if model else KnowledgeFormula.model.is_(None),
        KnowledgeFormula.command == command,
        KnowledgeFormula.label == label[:200],
        KnowledgeFormula.source == "reverse_analysis",
    ))
    now = utcnow()
    if existing is None:
        db.session.add(KnowledgeFormula(
            maker=maker, model=model, command=command, pid=did[:20] or None,
            label=label[:200], formula=formula, source="reverse_analysis", source_detail=detail,
            confidence=1.0, status="verified", verified_by=user_id, verified_at=now))
        return
    existing.formula = formula
    existing.source_detail = detail
    existing.status = "verified"
    existing.verified_by = user_id
    existing.verified_at = now


def remember_rule(rule, user_id: int | None) -> None:
    """적용 중인 디코딩 규칙 한 건을 지식베이스에 넣는다."""
    from app.modules.canlab.engine import signals

    signal = signals.BY_KEY.get(rule.signal_key)
    layout = {"request_id": rule.request_id, "did": rule.did, "start": rule.start, "width": rule.width,
              "endian": rule.endian, "signed": rule.signed, "scale": rule.scale, "offset": rule.offset}
    remember_formula(maker=rule.maker, model=rule.model, signal_key=rule.signal_key, layout=layout,
                     formula=rule.formula, label=signal.label if signal else rule.signal_key, user_id=user_id)
    remember_command(maker=rule.maker, model=rule.model, header=rule.request_id, command=f"22{rule.did}",
                     label=signal.label if signal else rule.signal_key, user_id=user_id)
