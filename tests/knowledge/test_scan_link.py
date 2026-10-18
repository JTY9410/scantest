"""검증된 지식이 스캔 계획에 들어가고, AI 진단코드는 공개 설명만 저장한다."""

from sqlalchemy import select

from app.extensions import db
from app.modules.catalog import service as catalog
from app.modules.knowledge.models import KnowledgeCommand, KnowledgeDTC
from app.modules.scanner.plan import build_plan
from app.modules.scans.models import Code


def test_verified_command_enters_plan_and_writes_stay_out(app):
    with app.app_context():
        db.session.add(KnowledgeCommand(
            maker="현대", header="7E5", command="22 AABB", label="시험 읽기", source="manual", status="verified"))
        db.session.add(KnowledgeCommand(
            maker="현대", header="7E0", command="2EF190", label="쓰기", source="manual", status="verified"))
        db.session.commit()
        steps = build_plan({"diag_company": "현대", "diag_model": "아반떼", "diag_fuel": "휘발유"})["steps"]
    assert ("7E5", "22AABB", "knowledge") in {(s["header"], s["command"], s["group"]) for s in steps}
    assert not any(s["command"] == "2EF190" for s in steps)


def test_ai_fill_saves_public_dtc_only(app, make_user, monkeypatch):
    def fake_ask(system, prompt, image=None):
        return ('[{"code":"P0300","type":"ice","unit_name":"엔진","desc":"임의 실화","known":true},'
                '{"code":"P0A80","type":"ev","unit_name":"배터리","desc":"전용","known":false}]', "openai")

    monkeypatch.setattr("app.modules.canlab.ai.ask", fake_ask)
    user_id = make_user("ai-codes", "admin")
    with app.app_context():
        from app.modules.accounts.models import User
        user = db.session.get(User, user_id)
        result = catalog.fill_codes_with_ai(user, "P0300 P0A80")
        row = db.session.scalar(select(Code).where(Code.code == "P0300"))
        hidden = db.session.scalar(select(Code).where(Code.code == "P0A80"))
        draft = db.session.scalar(select(KnowledgeDTC).where(KnowledgeDTC.code == "P0300"))
    assert result["saved"] == 1 and result["skipped"] == 1
    assert row.desc == "임의 실화" and hidden is None
    assert draft is not None and draft.status == "draft"


def test_unknown_maker_dtc_stays_draft_and_off_the_scan(app):
    from app.modules.knowledge.service import remember_unknown_dtcs
    from app.modules.scanner.service import _describe

    with app.app_context():
        assert remember_unknown_dtcs("기아", ["P1A00"]) == 1
        assert remember_unknown_dtcs("기아", ["P1A00"]) == 0
        row = db.session.scalar(select(KnowledgeDTC).where(KnowledgeDTC.code == "P1A00"))
        described = [{"code": "P1A00"}]
        _describe(described)
    assert row.maker == "기아" and row.status == "draft"
    assert described[0]["desc"] is None


def test_ai_guess_stays_in_notes_until_verified(app, monkeypatch):
    from app.modules.knowledge.service import _UNKNOWN_DTC, analyze_unknown_dtcs, remember_unknown_dtcs
    from app.modules.scanner.service import _describe

    def fake_ask(system, prompt, image=None):
        return ('[{"code":"P0300","known":true,"detail_name":"실화","desc":"여러 실린더 실화","guess":""},'
                '{"code":"P1A00","known":false,"detail_name":"","desc":"","guess":"제조사 추정"}]', "openai")

    monkeypatch.setattr("app.modules.canlab.ai.ask", fake_ask)
    with app.app_context():
        remember_unknown_dtcs(None, ["P0300", "P1A00"])
        stats = analyze_unknown_dtcs()
        public = db.session.scalar(select(KnowledgeDTC).where(KnowledgeDTC.code == "P0300"))
        maker = db.session.scalar(select(KnowledgeDTC).where(KnowledgeDTC.code == "P1A00"))
        master = db.session.scalar(select(Code).where(Code.code == "P1A00"))
        described = [{"code": "P1A00"}, {"code": "P0300"}]
        _describe(described)
    assert stats["described"] == 1 and stats["guessed"] == 1
    assert public.status == "draft" and public.description == "여러 실린더 실화"
    assert maker.description == _UNKNOWN_DTC and maker.notes == "추정: 제조사 추정"
    assert master is None
    assert described[0]["desc"] is None and described[1]["desc"] is None


def test_seen_read_is_saved_once_and_writes_are_skipped(app):
    from app.modules.knowledge.service import remember_seen_commands

    steps = [
        {"status": "ok", "header": "7E1", "command": "0105", "label": "덮어쓰면 안 됨"},
        {"status": "ok", "header": "7E0", "command": "010C", "label": "엔진 회전수"},
        {"status": "ok", "header": "7E0", "command": "010C", "label": "엔진 회전수"},
        {"status": "no_data", "header": "7E4", "command": "220101", "label": "배터리"},
        {"status": "ok", "header": "7E0", "command": "2EF190", "label": "쓰기"},
        {"status": "negative", "header": "7E0", "command": "010D", "label": "차속"},
    ]
    with app.app_context():
        db.session.add(KnowledgeCommand(
            maker="현대", header="7E1", command="0105", label="이미 검증", source="manual", status="verified"))
        db.session.commit()
        assert remember_seen_commands("현대", "아반떼", steps) == 1
        assert remember_seen_commands("현대", "아반떼", steps) == 0
        saved = db.session.scalar(select(KnowledgeCommand).where(KnowledgeCommand.command == "010C"))
        kept = db.session.scalar(select(KnowledgeCommand).where(KnowledgeCommand.command == "0105"))
        blocked = db.session.scalar(select(KnowledgeCommand).where(KnowledgeCommand.command == "2EF190"))
    assert saved.status == "draft" and saved.source == "scan_log" and saved.detail_name == "엔진 회전수"
    assert saved.header == "7E0" and saved.maker == "현대"
    assert kept.status == "verified" and kept.label == "이미 검증"
    assert blocked is None
