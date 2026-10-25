"""제조사별 DTC 설명 엑셀은 초안으로 한 번만 저장한다."""

import io
import zipfile
from xml.sax.saxutils import escape

from sqlalchemy import func, select

from app.extensions import db
from app.modules.knowledge.dtc_catalog import import_dtc_catalog
from app.modules.knowledge.models import KnowledgeDTC
from app.modules.scans.models import Code

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _xlsx(sheets: dict[str, list[list[str]]]) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as book:
        sheet_entries = []
        for index, (name, rows) in enumerate(sheets.items(), start=1):
            body = []
            for row_index, row in enumerate(rows, start=1):
                cells = "".join(
                    f'<c t="inlineStr"><is><t>{escape(value)}</t></is></c>' for value in row)
                body.append(f"<row>{cells}</row>")
            sheet = (
                f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<worksheet xmlns="{_NS}"><sheetData>{"".join(body)}</sheetData></worksheet>'
            )
            path = f"xl/worksheets/sheet{index}.xml"
            book.writestr(path, sheet)
            sheet_entries.append((name, index, f"rId{index}", path))
        workbook = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<workbook xmlns="{_NS}" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            "<sheets>"
            + "".join(
                f'<sheet name="{escape(name)}" sheetId="{index}" r:id="{rid}"/>'
                for name, index, rid, _ in sheet_entries
            )
            + "</sheets></workbook>"
        )
        rels = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="{rid}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet{index}.xml"/>'
                for _, index, rid, _ in sheet_entries
            )
            + "</Relationships>"
        )
        book.writestr("xl/workbook.xml", workbook)
        book.writestr("xl/_rels/workbook.xml.rels", rels)
    return payload.getvalue()


def test_dtc_catalog_import_uses_pbcu_and_stays_draft(app, tmp_path):
    content = _xlsx({
        "nissan_ecm": [
            ["id", "code", "detail", "pbcu", "memo"],
            ["2", "0102", "MAF 센서/회로", "P0102", "17,FF,00"],
        ],
        "audi_vw_abs": [
            ["id", "code", "detail", "pbcu", "memo"],
            ["3", "000080", "DATA BUS (U1122 잘못된 메시지)", "128", ""],
        ],
        "benz_abs": [
            ["id", "code", "detail", "pbcu", "memo"],
            ["1", "C204FA", "통신 이상", "U0204FA", ""],
        ],
    })
    path = tmp_path / "dtc_description_20261019.xlsx"
    path.write_bytes(content)
    with app.app_context():
        first = import_dtc_catalog(path)
        nissan = db.session.scalar(select(KnowledgeDTC).where(
            KnowledgeDTC.code == "P0102", KnowledgeDTC.maker == "닛산"))
        audi = db.session.scalar(select(KnowledgeDTC).where(
            KnowledgeDTC.code == "U1122", KnowledgeDTC.maker == "Audi/VW"))
        benz = db.session.scalar(select(KnowledgeDTC).where(
            KnowledgeDTC.code == "U0204FA", KnowledgeDTC.maker == "Mercedes-Benz"))
        catalog = db.session.scalar(select(Code).where(Code.code == "P0102", Code.deleted_at.is_(None)))
        saved = (
            (nissan.status, nissan.detail_name),
            (audi.status, audi.ecu_name),
            benz.code,
            catalog.desc if catalog else None,
        )
        again = import_dtc_catalog(path)
        copies = db.session.scalar(select(func.count()).select_from(KnowledgeDTC).where(
            KnowledgeDTC.code == "P0102", KnowledgeDTC.maker == "닛산"))
    assert first["sheet"] == 3 and first["dtcs"] == 3
    assert saved[0][0] == "draft" and saved[0][1].startswith("MAF")
    assert saved[1] == ("draft", "abs")
    assert saved[2] == "U0204FA"
    assert saved[3] and saved[3].startswith("MAF")
    assert again["dtcs"] == 0 and again["kept"] == 3 and copies == 1
