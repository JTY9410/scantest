"""제조사별 고장코드 문서는 공통만 스캔 설명에 쓰고, 제조사 코드는 참고로 남긴다."""

from sqlalchemy import func, select

from app.extensions import db
from app.modules.knowledge.dtc_workbook import import_workbook
from app.modules.knowledge.models import KnowledgeDTC, KnowledgeTerm
from app.modules.scanner.service import _describe


def test_workbook_import_is_idempotent_and_splits_generic_from_maker(app):
    with app.app_context():
        first = import_workbook()
        common = db.session.scalar(select(KnowledgeDTC).where(
            KnowledgeDTC.code == "P0010", KnowledgeDTC.source == "workbook"))
        maker = db.session.scalar(select(KnowledgeDTC).where(
            KnowledgeDTC.code == "P1106", KnowledgeDTC.source == "workbook"))
        saved = (common.status, common.detail_name, common.english_name, common.description,
                 maker.maker, maker.status, maker.detail_name)
        makers = db.session.scalar(select(func.count()).select_from(KnowledgeTerm).where(
            KnowledgeTerm.category == "제조사"))
        again = import_workbook()
        copies = db.session.scalar(select(func.count()).select_from(KnowledgeDTC).where(
            KnowledgeDTC.code == "P0010", KnowledgeDTC.source == "workbook"))
        described = [{"code": "P0010"}, {"code": "P1106"}]
        _describe(described, "현대")
    assert first["dtcs"] >= 30 and first["terms"] >= 1
    assert saved[0] == "verified" and saved[1] and saved[2]
    assert saved[4] == "Hyundai" and saved[5] == "draft"
    assert makers >= 1
    assert again == {"dtcs": 0, "terms": 0} and copies == 1
    assert described[0]["desc"] == saved[3]
    assert described[1]["desc"] is None
    assert described[1]["workbook_ref"] == saved[6]
