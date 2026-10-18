"""공개 표준 명령·수식·고장코드만 모으고, 지우기 명령은 스캔에 넣지 않는다."""

from sqlalchemy import func, select

from app.extensions import db
from app.modules.knowledge.collect import collect_public
from app.modules.knowledge.models import KnowledgeCommand, KnowledgeDTC, KnowledgeFormula
from app.modules.knowledge.service import scan_commands
from app.modules.scanner.plan import build_plan
from app.modules.scanner.service import _describe
from app.modules.scans.models import Code


def test_collect_saves_public_names_and_skips_invented_codes(app, monkeypatch):
    def fake_ask(system, prompt, image=None):
        return (
            '[{"code":"P0300","detail_name":"여러 실린더 실화","description":"여러 실린더에서 실화가 감지되었습니다.","known":true},'
            '{"code":"P9999","detail_name":"만든 코드","description":"없음","known":true}]',
            "openai",
        )

    monkeypatch.setattr("app.modules.canlab.ai.ask", fake_ask)
    with app.app_context():
        stats = collect_public()
        p0300 = db.session.scalar(select(Code).where(Code.code == "P0300"))
        invented = db.session.scalar(select(Code).where(Code.code == "P9999"))
        knowledge = db.session.scalar(select(KnowledgeDTC).where(KnowledgeDTC.code == "P0300"))
        clear = db.session.scalar(select(KnowledgeCommand).where(KnowledgeCommand.command == "14FFFFFF"))
        rpm = db.session.scalar(select(KnowledgeFormula).where(KnowledgeFormula.pid == "0C"))
        again = collect_public()
        p0300 = db.session.scalar(select(Code).where(Code.code == "P0300"))
        knowledge = db.session.scalar(select(KnowledgeDTC).where(KnowledgeDTC.code == "P0300"))
        clear = db.session.scalar(select(KnowledgeCommand).where(KnowledgeCommand.command == "14FFFFFF"))
        rpm = db.session.scalar(select(KnowledgeFormula).where(KnowledgeFormula.pid == "0C"))
        copies = db.session.scalar(select(func.count()).select_from(Code).where(Code.code == "P0300"))
        saved = (p0300.desc, p0300.detail_desc, knowledge.detail_name, knowledge.status,
                 clear.status, rpm.detail_name, rpm.status)
    assert stats["dtcs"] >= 1 and saved[0] == "여러 실린더 실화"
    assert saved[1] and invented is None
    assert saved[2] == "여러 실린더 실화" and saved[3] == "verified"
    assert saved[4] == "draft"
    assert saved[5] and saved[6] == "verified"
    assert again["dtcs"] == 0 and copies == 1


def test_clear_command_stays_out_of_scan_and_dtc_text_is_used(app, monkeypatch):
    monkeypatch.setattr("app.modules.canlab.ai.ask", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("skip")))
    with app.app_context():
        collect_public()
        commands = {item["command"] for item in scan_commands(None)}
        map_pid = db.session.scalar(select(KnowledgeCommand).where(KnowledgeCommand.command == "010B"))
        map_formula = db.session.scalar(select(KnowledgeFormula).where(KnowledgeFormula.pid == "0B"))
        from app.modules.knowledge.models import KnowledgeTerm
        doip = db.session.scalar(select(KnowledgeTerm).where(KnowledgeTerm.term == "DoIP"))
        steps = build_plan({"diag_company": "현대", "diag_model": "아반떼", "diag_fuel": "휘발유"})["steps"]
        rows = [{"code": "P0420"}]
        _describe(rows)
    assert map_pid is not None and map_pid.status == "verified" and map_formula.status == "verified"
    assert doip is not None and doip.status == "draft" and "ELM327" in doip.definition
    assert any(command.startswith("01") for command in commands)
    assert "14FFFFFF" not in commands and "1003" not in commands
    assert not any(step["command"] in {"14FFFFFF", "1003", "04"} for step in steps)
    assert rows[0]["desc"] and rows[0]["detail_name"]
