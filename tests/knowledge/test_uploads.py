"""올린 엑셀·PDF의 고장코드와 읽기 명령은 초안으로 한 번만 저장한다."""

import io
import zipfile
from xml.sax.saxutils import escape

from reportlab.pdfgen import canvas
from sqlalchemy import func, select

from app.extensions import db
from app.modules.knowledge.models import KnowledgeCommand, KnowledgeDTC, KnowledgeFormula
from app.modules.knowledge.uploads import import_command_file, import_dtc_file
from tests.conftest import csrf_token

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _xlsx(rows: list[list[str]]) -> bytes:
    body = []
    for index, row in enumerate(rows, start=1):
        cells = "".join(
            f'<c t="inlineStr" r="A{index}"><is><t>{escape(value)}</t></is></c>' for value in row)
        body.append(f'<row r="{index}">{cells}</row>')
    sheet = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<worksheet xmlns="{_NS}"><sheetData>{"".join(body)}</sheetData></worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<workbook xmlns="{_NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="자료" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as book:
        book.writestr("xl/workbook.xml", workbook)
        book.writestr("xl/_rels/workbook.xml.rels", rels)
        book.writestr("xl/worksheets/sheet1.xml", sheet)
    return payload.getvalue()


def _pdf() -> bytes:
    payload = io.BytesIO()
    document = canvas.Canvas(payload)
    document.drawString(72, 720, "P0C01 upload sample")
    document.drawString(72, 700, "7E4 220105 배터리 건강")
    document.drawString(72, 680, "10 03 세션 변경")
    document.save()
    return payload.getvalue()


def test_xlsx_dtc_and_command_uploads_stay_drafts(app):
    codes = _xlsx([["코드", "설명"], ["P0C01", "업로드 시험 코드"], ["없음", ""]])
    commands = _xlsx([
        ["주소", "명령", "명칭", "수식", "단위"],
        ["7E4", "22 01 05", "배터리 건강", "A / 10", "%"],
        ["7E0", "10 03", "세션", "", ""],
    ])
    with app.app_context():
        first = import_dtc_file("codes.xlsx", codes, "현대")
        again = import_dtc_file("codes.xlsx", codes, "현대")
        row = db.session.scalar(select(KnowledgeDTC).where(KnowledgeDTC.code == "P0C01"))
        saved = (row.status, row.maker, row.detail_name, row.source)
        copies = db.session.scalar(select(func.count()).select_from(KnowledgeDTC).where(
            KnowledgeDTC.code == "P0C01"))
        command_stats = import_command_file("commands.xlsx", commands, "현대")
        command = db.session.scalar(select(KnowledgeCommand).where(KnowledgeCommand.command == "220105"))
        command_saved = (command.status, command.header, command.detail_name)
        formula = db.session.scalar(select(KnowledgeFormula).where(KnowledgeFormula.command == "220105"))
        formula_saved = (formula.formula, formula.unit, formula.status) if formula else None
        blocked = db.session.scalar(select(func.count()).select_from(KnowledgeCommand).where(
            KnowledgeCommand.command == "1003", KnowledgeCommand.source == "upload"))
    assert first == {"found": 1, "saved": 1, "kept": 0}
    assert again["saved"] == 0 and again["kept"] == 1 and copies == 1
    assert saved == ("draft", "현대", "업로드 시험 코드", "upload")
    assert command_stats["saved"] == 1 and command_stats["skipped"] == 1
    assert command_saved == ("draft", "7E4", "배터리 건강")
    assert formula_saved == ("A / 10", "%", "draft")
    assert blocked == 0


def test_pdf_upload_reads_text_and_skips_session_command(app, admin_client):
    token = csrf_token(admin_client, "/admin/knowledge/dtcs")
    response = admin_client.post("/admin/knowledge/dtcs/upload", content_type="multipart/form-data", data={
        "csrf_token": token, "maker": "", "file": (io.BytesIO(_pdf()), "notes.pdf"),
    })
    with app.app_context():
        row = db.session.scalar(select(KnowledgeDTC).where(
            KnowledgeDTC.code == "P0C01", KnowledgeDTC.source == "upload"))
        saved = (row.status, row.maker, row.description) if row else None
    assert response.status_code == 302
    assert saved == ("draft", None, "upload sample")
