"""EV·ICE 표준 DTC 엑셀은 없는 코드만 넣고 기존 설명은 덮지 않는다."""

import io
import zipfile
from xml.sax.saxutils import escape

from sqlalchemy import func, select

from app.extensions import db
from app.modules.knowledge.dtc_global import import_dtc_global
from app.modules.knowledge.models import KnowledgeDTC
from app.modules.scans.models import Code

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _xlsx(name: str, rows: list[list[str]]) -> bytes:
    body = []
    for row in rows:
        cells = "".join(f'<c t="inlineStr"><is><t>{escape(value)}</t></is></c>' for value in row)
        body.append(f"<row>{cells}</row>")
    sheet = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<worksheet xmlns="{_NS}"><sheetData>{"".join(body)}</sheetData></worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<workbook xmlns="{_NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(name)}" sheetId="1" r:id="rId1"/></sheets></workbook>'
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


def test_global_import_skips_existing_and_adds_missing(app, tmp_path):
    ev = tmp_path / "EV_DTC_전체코드.xlsx"
    ice = tmp_path / "ICE_DTC_Global_Complete_no_grade.xlsx"
    ev.write_bytes(_xlsx("EV_DTC_전체코드", [
        ["표준DTC코드", "코드명칭(한글)", "상세내용", "분류중분류(시스템)", "권장조치"],
        ["P0A02", "HV 배터리 팩 전압 이상", "배터리 팩 총전압 측정 오류", "배터리(BMS)", "BMS 점검"],
        ["P0A80", "이미 있는 전기차 코드", "덮이면 안 됨", "고전압 배터리", "무시"],
    ]))
    ice.write_bytes(_xlsx("전체코드", [
        ["표준DTC코드", "코드명칭(한글)", "상세내용", "중분류(시스템)", "권장조치"],
        ["P0010", "VVT 오일제어밸브A 회로 이상", "흡기 VVT 오류", "VVT/캠타이밍", "오일 점검"],
    ]))
    with app.app_context():
        db.session.add(KnowledgeDTC(
            code="P0A80", source="public_docs", description="기존 설명",
            detail_name="기존 명칭", status="verified", confidence=1.0,
        ))
        db.session.add(Code(type="ev", code="P0A80", unit_name="고전압 배터리", desc="기존 마스터"))
        db.session.commit()
        first = import_dtc_global([ev, ice])
        kept = db.session.scalar(select(KnowledgeDTC).where(KnowledgeDTC.code == "P0A80"))
        added = db.session.scalar(select(KnowledgeDTC).where(KnowledgeDTC.code == "P0A02"))
        master = db.session.scalar(select(Code).where(Code.code == "P0010", Code.deleted_at.is_(None)))
        saved = (
            kept.detail_name, kept.description,
            added.status if added else None, added.detail_name if added else None,
            master.desc if master else None, master.type if master else None,
        )
        again = import_dtc_global([ev, ice])
        copies = db.session.scalar(select(func.count()).select_from(KnowledgeDTC).where(
            KnowledgeDTC.code == "P0A02"))
    assert first["dtcs"] >= 2 and first["codes"] >= 2
    assert saved[0] == "기존 명칭" and saved[1] == "기존 설명"
    assert saved[2] == "verified" and saved[3] == "HV 배터리 팩 전압 이상"
    assert saved[4] == "VVT 오일제어밸브A 회로 이상" and saved[5] == "ice"
    assert again["dtcs"] == 0 and again["codes"] == 0 and copies == 1
