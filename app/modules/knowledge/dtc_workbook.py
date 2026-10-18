"""제조사별 DTC 통합 문서를 지식베이스에 넣는다.

공통 코드는 검증된 설명으로 쓰고, 제조사 전용 코드는 확인 전 참고로만 남긴다.
"""

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import ServiceError
from app.extensions import db
from app.modules.knowledge.models import KnowledgeDTC, KnowledgeTerm
from app.modules.scans.models import Code

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_SOURCE = "workbook"
_FILE = "자동차_제조사별_DTC_고장코드_데이터베이스.xlsx"
_MAKER_ALIASES = {
    "현대": "hyundai",
    "기아": "kia",
    "미쓰비시": "mitsubishi",
    "미츠비시": "mitsubishi",
}


def workbook_path() -> Path:
    root = Path(__file__).resolve().parents[3]
    path = root / _FILE
    if not path.is_file():
        raise ServiceError("제조사별 고장코드 문서를 찾지 못했습니다.")
    return path


def import_workbook(path: Path | None = None) -> dict[str, int]:
    """문서를 고장코드와 용어로 넣는다. 같은 출처의 행은 다시 실행해도 한 건이다."""
    sheets = _sheets(path or workbook_path())
    counts = {"dtcs": 0, "terms": 0}
    for row in sheets.get("공통_DTC", [])[1:]:
        if _upsert_dtc(row, maker=None, generic=True):
            counts["dtcs"] += 1
    for row in sheets.get("제조사별_DTC", [])[1:]:
        if _upsert_dtc(row, maker=row[0] if row else None, generic=False):
            counts["dtcs"] += 1
    counts["terms"] += _terms(sheets)
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ServiceError("같은 고장코드가 이미 다른 형식으로 저장되어 있습니다.") from exc
    return counts


def workbook_hints(codes: set[str], maker: str | None) -> dict[str, KnowledgeDTC]:
    """확인 전인 제조사 코드. 스캔 설명 대신 참고로만 붙인다."""
    wanted = {code.upper()[:5] for code in codes if code}
    if not wanted:
        return {}
    names = _maker_names(maker)
    if not names:
        return {}
    rows = db.session.scalars(select(KnowledgeDTC).where(
        KnowledgeDTC.code.in_(wanted),
        KnowledgeDTC.source == _SOURCE,
        KnowledgeDTC.status == "draft",
        KnowledgeDTC.maker.is_not(None),
    ))
    return {row.code: row for row in rows if (row.maker or "").casefold() in names}


def _maker_names(maker: str | None) -> set[str]:
    text = (maker or "").strip()
    if not text:
        return set()
    names = {text.casefold()}
    alias = _MAKER_ALIASES.get(text)
    if alias:
        names.add(alias)
    return names


def _upsert_dtc(row: list[str], *, maker: str | None, generic: bool) -> bool:
    if generic:
        code, korean, english, major, minor, kind, ecu, parts, caution = _pad(row, 9)
    else:
        _maker, code, korean, english, major, minor, kind, ecu, parts, caution = _pad(row, 10)
    code = code.upper()
    if not re.fullmatch(r"[PCBU][0-9A-F]{4}", code) or not korean:
        return False
    maker_name = (maker or "").strip()[:50] or None
    existing = db.session.scalar(select(KnowledgeDTC).where(
        KnowledgeDTC.code == code,
        KnowledgeDTC.source == _SOURCE,
        KnowledgeDTC.maker == maker_name if maker_name else KnowledgeDTC.maker.is_(None),
    ))
    created = existing is None
    if created:
        existing = KnowledgeDTC(code=code, maker=maker_name, source=_SOURCE, description=korean)
        db.session.add(existing)
    existing.detail_name = korean[:200]
    existing.english_name = english[:200] or None
    existing.description = korean if not english else f"{korean} ({english})"
    existing.category = major[:50] or None
    existing.subsystem = minor[:50] or None
    existing.ecu_name = ecu[:100] or None
    existing.parts = parts[:200] or None
    existing.notes = " · ".join(part for part in (kind, caution) if part) or None
    existing.source_detail = "공통_DTC" if generic else "제조사별_DTC"
    existing.status = "verified" if generic else "draft"
    existing.confidence = 1.0 if generic else 0.4
    _upsert_code(code, korean, english, major, ecu, parts, caution, generic)
    return created


def _upsert_code(code, korean, english, major, ecu, parts, caution, generic) -> None:
    """스캔과 진단코드 화면이 읽는 마스터에도 같은 설명을 둔다."""
    kind = "ev" if any(word in f"{major} {korean}" for word in ("전기", "하이브리드", "배터리", "EV")) else "ice"
    detail = " · ".join(part for part in (english, parts, caution) if part)
    if not generic:
        detail = "제조사 자료(확인 전). " + detail
    row = db.session.scalar(select(Code).where(Code.code == code, Code.deleted_at.is_(None)))
    if row is None:
        db.session.add(Code(
            type=kind, code=code, unit_name=(ecu or major or "OBD")[:255],
            desc=korean[:2000], detail_desc=detail[:4000] or None))
        return
    row.desc = korean[:2000]
    row.detail_desc = detail[:4000] or row.detail_desc
    row.unit_name = row.unit_name or (ecu or major or "OBD")[:255]


def _terms(sheets: dict[str, list[list[str]]]) -> int:
    added = 0
    for row in sheets.get("제조사_목록", [])[1:]:
        region, name, source = _pad(row, 3)
        if name and _upsert_term(name, f"{region} · {source}".strip(" ·"), "제조사"):
            added += 1
    for row in sheets.get("코드체계", [])[1:]:
        span, kind, text = _pad(row, 3)
        if span and _upsert_term(span, f"{kind}: {text}".strip(), "코드체계"):
            added += 1
    for row in sheets.get("출처", [])[1:]:
        org, title, url, kind, caution = _pad(row, 5)
        label = f"{org} {title}".strip()
        if label and _upsert_term(label[:100], "\n".join(part for part in (url, kind, caution) if part), "출처"):
            added += 1
    return added


def _upsert_term(term: str, definition: str, category: str) -> bool:
    term = term.strip()[:100]
    existing = db.session.scalar(select(KnowledgeTerm).where(KnowledgeTerm.term == term))
    if existing is not None:
        return False
    db.session.add(KnowledgeTerm(
        term=term, definition=definition or term, category=category[:50], source=_SOURCE,
        source_detail=_FILE, status="draft"))
    return True


def _pad(row: list[str], size: int) -> list[str]:
    values = [(cell or "").strip() for cell in row]
    return values[:size] + [""] * (size - len(values))


def _sheets(path: Path) -> dict[str, list[list[str]]]:
    with zipfile.ZipFile(path) as book:
        rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        targets = {rel.attrib["Id"]: rel.attrib["Target"].lstrip("/") for rel in rels}
        workbook = ET.fromstring(book.read("xl/workbook.xml"))
        found = {}
        for sheet in workbook.findall("m:sheets/m:sheet", _NS):
            rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            found[sheet.attrib["name"]] = _rows(book.read(targets[rid]))
    return found


def _rows(payload: bytes) -> list[list[str]]:
    root = ET.fromstring(payload)
    rows = []
    for row in root.findall("m:sheetData/m:row", _NS):
        values = []
        for cell in row.findall("m:c", _NS):
            if cell.attrib.get("t") == "inlineStr":
                values.append("".join(node.text or "" for node in cell.iter(
                    "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))
            else:
                node = cell.find("m:v", _NS)
                values.append(node.text if node is not None and node.text else "")
        rows.append(values)
    return rows
