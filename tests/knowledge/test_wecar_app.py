"""위카 앱의 전기차 읽기는 초안으로 한 번만 쌓이고, 지우기 명령은 넣지 않는다."""

from sqlalchemy import func, select

from app.extensions import db
from app.modules.knowledge.models import KnowledgeCommand, KnowledgeDTC, KnowledgeFormula
from app.modules.knowledge.wecar_app import import_wecar_app
from app.modules.scans.models import Code


def test_wecar_app_reads_are_drafts_and_idempotent(app):
    with app.app_context():
        first = import_wecar_app()
        bms = db.session.scalar(select(KnowledgeCommand).where(
            KnowledgeCommand.command == "220101", KnowledgeCommand.header == "7E4"))
        saved = (bms.status, bms.ecu_name, bms.detail_name)
        formula = db.session.scalar(select(KnowledgeFormula).where(
            KnowledgeFormula.command == "220101", KnowledgeFormula.label == "배터리 충전 상태(BMS)"))
        formula_text = formula.formula if formula else None
        blocked = db.session.scalar(select(func.count()).select_from(KnowledgeCommand).where(
            KnowledgeCommand.command.in_(("1003", "14FFFFFF", "04"))))
        ev = db.session.scalar(select(KnowledgeDTC).where(KnowledgeDTC.code == "P0A80"))
        ev_saved = (ev.status, ev.detail_name) if ev else None
        catalog = db.session.scalar(select(Code).where(Code.code == "P0AA6", Code.deleted_at.is_(None)))
        catalog_desc = catalog.desc if catalog else None
        again = import_wecar_app()
        copies = db.session.scalar(select(func.count()).select_from(KnowledgeCommand).where(
            KnowledgeCommand.command == "220101", KnowledgeCommand.header == "7E4",
            KnowledgeCommand.source == "reverse_analysis"))
    assert first["commands"] >= 15 and first["formulas"] >= 8 and first["dtcs"] == 33
    assert saved == ("draft", "BMS", "BMS 배터리 데이터(22 0101)")
    assert formula_text == "A / 2"
    assert blocked == 0
    assert ev_saved[0] == "verified" and ev_saved[1]
    assert catalog_desc
    assert again == {"commands": 0, "formulas": 0, "dtcs": 0} and copies == 1
