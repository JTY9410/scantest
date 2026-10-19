"""명령은 수집 데이터 다음에 보이고, 역분석 명령은 같은 범위에 한 번만 쌓인다."""

from sqlalchemy import func, select

from app.extensions import db
from app.modules.knowledge.models import KnowledgeCommand, KnowledgeFormula
from app.modules.knowledge.service import command_views, remember_observed_commands, save_command


def test_command_view_lists_formula_after_the_command(app):
    with app.app_context():
        db.session.add(KnowledgeCommand(
            command="010C", detail_name="엔진 회전수", label="엔진 회전수",
            source="public_docs", status="verified"))
        db.session.add(KnowledgeFormula(
            command="010C", pid="0C", label="엔진 회전수", detail_name="엔진 회전수",
            formula="((A * 256) + B) / 4", unit="rpm", source="public_docs", status="verified"))
        db.session.commit()
        views = command_views(status=None)
        match = next(view for view in views if view["row"].command == "010C")
        assert match["data"][0].formula == "((A * 256) + B) / 4"
        assert match["data"][0].unit == "rpm"


def test_commands_page_shows_collected_data(admin_client, app):
    with app.app_context():
        db.session.add(KnowledgeCommand(
            command="010C", detail_name="엔진 회전수", label="엔진 회전수",
            source="public_docs", status="verified"))
        db.session.add(KnowledgeFormula(
            command="010C", pid="0C", label="엔진 회전수", formula="((A * 256) + B) / 4",
            unit="rpm", source="public_docs", status="verified"))
        db.session.commit()
    response = admin_client.get("/admin/knowledge/commands")
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "010C" in page and "수집:" in page and "((A * 256) + B) / 4" in page
    assert "진단 명령" in page and "지식 고장코드" in page
    assert "전체 현황" in page and "table-scroll" in page


def test_save_command_updates_collected_formula(app):
    with app.app_context():
        row = save_command({
            "command": "010D", "detail_name": "차속", "description": "차량 속도",
            "formula": "A", "unit": "km/h", "status": "verified",
        })
        formula = db.session.scalar(select(KnowledgeFormula).where(KnowledgeFormula.command == "010D"))
        assert row.command == "010D"
        assert formula.formula == "A" and formula.unit == "km/h"
        save_command({"id": str(row.id), "command": "010D", "detail_name": "차속",
                      "formula": "A", "unit": "km/h", "status": "verified"})
        copies = db.session.scalar(select(func.count()).select_from(KnowledgeFormula).where(
            KnowledgeFormula.command == "010D"))
        assert copies == 1


def test_observed_command_is_saved_once_and_leaves_public_name(app):
    with app.app_context():
        public = KnowledgeCommand(
            command="010C", detail_name="엔진 회전수", label="엔진 회전수",
            source="public_docs", maker=None, status="verified")
        db.session.add(public)
        db.session.commit()
        found = [{"header": "7E0", "command": "010C", "sendable": True, "example": "41 0C 1A F8"}]
        assert remember_observed_commands("현대", "아반떼", found) == 1
        assert remember_observed_commands("현대", "아반떼", found) == 0
        assert public.detail_name == "엔진 회전수"
        draft = db.session.scalar(select(KnowledgeCommand).where(
            KnowledgeCommand.source == "reverse_analysis", KnowledgeCommand.command == "010C"))
        assert draft.status == "draft" and draft.maker == "현대" and "41 0C" in draft.source_detail
        blocked = [{"header": "7E0", "command": "14FFFFFF", "sendable": True},
                   {"header": "7E0", "command": "22" + "00" * 9, "sendable": False}]
        assert remember_observed_commands("현대", "아반떼", blocked) == 0
