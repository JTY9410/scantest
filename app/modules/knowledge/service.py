"""Knowledge base service."""
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.modules.knowledge.models import (
    KnowledgeCommand,
    KnowledgeDTC,
    KnowledgeFormula,
    KnowledgeTerm,
)


def list_commands(*, status: str = "verified", maker: str | None = None, limit: int = 100):
    """Get commands for scan planning (only verified unless explicitly asking for drafts)."""
    stmt = select(KnowledgeCommand).where(KnowledgeCommand.status == status).order_by(KnowledgeCommand.command)
    if maker:
        stmt = stmt.where(or_(KnowledgeCommand.maker == maker, KnowledgeCommand.maker.is_(None)))
    stmt = stmt.limit(limit)
    return db.session.scalars(stmt).all()


def list_formulas(*, status: str = "verified", maker: str | None = None, limit: int = 100):
    """Get formulas for interpretation (only verified unless explicitly asking for drafts)."""
    stmt = select(KnowledgeFormula).where(KnowledgeFormula.status == status).order_by(KnowledgeFormula.pid)
    if maker:
        stmt = stmt.where(or_(KnowledgeFormula.maker == maker, KnowledgeFormula.maker.is_(None)))
    stmt = stmt.limit(limit)
    return db.session.scalars(stmt).all()


def list_dtcs(*, status: str = "verified", maker: str | None = None, limit: int = 1000):
    """Get DTC meanings (only verified unless explicitly asking for drafts)."""
    stmt = select(KnowledgeDTC).where(KnowledgeDTC.status == status).order_by(KnowledgeDTC.code)
    if maker:
        stmt = stmt.where(or_(KnowledgeDTC.maker == maker, KnowledgeDTC.maker.is_(None)))
    stmt = stmt.limit(limit)
    return db.session.scalars(stmt).all()


def list_terms(*, status: str = "verified", limit: int = 500):
    """Get glossary terms."""
    stmt = select(KnowledgeTerm).where(KnowledgeTerm.status == status).order_by(KnowledgeTerm.term).limit(limit)
    return db.session.scalars(stmt).all()


def verify_command(command_id: int, user_id: int):
    """Mark a command as verified."""
    cmd = db.session.get(KnowledgeCommand, command_id)
    if cmd:
        cmd.status = "verified"
        cmd.verified_by = user_id
        cmd.verified_at = datetime.utcnow()
        db.session.commit()


def verify_formula(formula_id: int, user_id: int):
    """Mark a formula as verified."""
    formula = db.session.get(KnowledgeFormula, formula_id)
    if formula:
        formula.status = "verified"
        formula.verified_by = user_id
        formula.verified_at = datetime.utcnow()
        db.session.commit()


def verify_dtc(dtc_id: int, user_id: int):
    """Mark a DTC as verified."""
    dtc = db.session.get(KnowledgeDTC, dtc_id)
    if dtc:
        dtc.status = "verified"
        dtc.verified_by = user_id
        dtc.verified_at = datetime.utcnow()
        db.session.commit()


def import_from_commands_json(commands_data: list[dict]) -> int:
    """Import commands from commands.json (from wecar_scan_analysis.zip)."""
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
            source_detail=cmd_data.get("source_detail", "Imported from WESCAN Flutter app analysis"),
            confidence=1.0,
            status="verified",
        )
        db.session.add(cmd)
        count += 1
    
    db.session.commit()
    return count
