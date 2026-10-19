"""EV·ICE 표준 DTC 엑셀에서 없는 코드만 보강한다.

이미 지식베이스나 진단코드 마스터에 있는 코드는 설명을 덮어쓰지 않는다.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import ServiceError
from app.extensions import db
from app.modules.knowledge.models import KnowledgeDTC
from app.modules.scans.models import Code

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_SOURCE = "workbook"
_STD = re.compile(r"^[PCBU][0-9A-F]{4}$", re.I)
_FILES = (
    ("EV_DTC_전체코드.xlsx", "EV_DTC_전체코드", "ev"),
    ("ICE_DTC_Global_Complete_no_grade.xlsx", "전체코드", "ice"),
)
_CODE_HEADERS = {"표준dtc코드", "표준코드"}
_NAME_HEADERS = {"코드명칭한글", "코드명"}
_DESC_HEADERS = {"상세내용"}
_CATEGORY_HEADERS = {"분류중분류시스템", "중분류시스템", "대분류"}
_ACTION_HEADERS = {"권장조치"}
_SEVERITY_HEADERS = {"심각도명칭"}
_DRIVE_HEADERS = {"주행상태", "주행가능여부"}


def import_dtc_global(paths: list[Path] | None = None) -> dict[str, int]:
    """없는 표준 고장코드만 추가한다. 같은 코드가 있으면 건너뛴다."""
    counts = {"sheet": 0, "dtcs": 0, "codes": 0, "skipped": 0, "filled": 0}
    targets = paths or [_root() / name for name, _, _ in _FILES]
    for path in targets:
        if not path.is_file():
            raise ServiceError(f"고장코드 문서를 찾지 못했습니다: {path.name}")
        kind = "ev" if "EV" in path.name.upper() else "ice"
        sheet_name = next((sheet for name, sheet, _ in _FILES if name == path.name), None)
        sheets = _sheets(path)
        if sheet_name and sheet_name in sheets:
            rows = sheets[sheet_name]
        else:
            rows = next(iter(sheets.values()), [])
        headers = [_key(cell) for cell in (rows[0] if rows else [])]
        if not _CODE_HEADERS.intersection(headers):
            continue
        for row in rows[1:]:
            line = dict(zip(headers, row, strict=False))
            code = _column(line, _CODE_HEADERS).upper()
            name = _column(line, _NAME_HEADERS)
            detail = _column(line, _DESC_HEADERS) or name
            if not _STD.fullmatch(code) or not name:
                continue
            counts["sheet"] += 1
            notes = " · ".join(part for part in (
                _column(line, _SEVERITY_HEADERS),
                _column(line, _DRIVE_HEADERS),
                _column(line, _ACTION_HEADERS),
            ) if part) or None
            category = _column(line, _CATEGORY_HEADERS)[:50] or None
            dtc_outcome = _add_dtc(code, name, detail, category, notes, path.name, kind)
            code_outcome = _add_code(code, name, detail, category, notes, kind)
            if dtc_outcome == "created":
                counts["dtcs"] += 1
            elif dtc_outcome == "skipped":
                counts["skipped"] += 1
            if code_outcome == "created":
                counts["codes"] += 1
            elif code_outcome == "filled":
                counts["filled"] += 1
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ServiceError("같은 고장코드가 이미 다른 형식으로 저장되어 있습니다.") from exc
    return counts


def _add_dtc(code, name, detail, category, notes, filename, kind) -> str:
    existing = db.session.scalar(select(KnowledgeDTC).where(
        KnowledgeDTC.code == code, KnowledgeDTC.maker.is_(None)))
    if existing is not None:
        return "skipped"
    db.session.add(KnowledgeDTC(
        code=code, source=_SOURCE, description=detail,
        detail_name=name[:200], category=category, notes=notes,
        source_detail=f"{filename} ({kind})", status="verified", confidence=0.9,
    ))
    return "created"


def _add_code(code, name, detail, category, notes, kind) -> str:
    row = db.session.scalar(select(Code).where(Code.code == code, Code.deleted_at.is_(None)))
    text = detail if not notes else f"{detail} · {notes}"
    if row is None:
        db.session.add(Code(
            type=kind, code=code, unit_name=(category or "OBD")[:255],
            desc=name[:2000], detail_desc=text[:4000], root_cause=(notes or "")[:2000] or None,
        ))
        return "created"
    changed = False
    if not row.desc:
        row.desc = name[:2000]
        changed = True
    if not row.detail_desc:
        row.detail_desc = text[:4000]
        changed = True
    if not row.unit_name:
        row.unit_name = (category or "OBD")[:255]
        changed = True
    if not row.root_cause and notes:
        row.root_cause = notes[:2000]
        changed = True
    if row.type != kind and kind == "ev":
        row.type = "ev"
        changed = True
    return "filled" if changed else "skipped"


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _column(line: dict, names: set[str]) -> str:
    for key, value in line.items():
        if key in names and value:
            return str(value).strip()
    return ""


def _key(cell: str) -> str:
    return re.sub(r"[\s_()/·\-]+", "", cell).casefold()


def _sheets(path: Path) -> dict[str, list[list[str]]]:
    try:
        book = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ServiceError("엑셀 파일을 읽지 못했습니다.") from exc
    with book:
        shared = _shared_strings(book)
        rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        targets = {rel.attrib["Id"]: "xl/" + rel.attrib["Target"].lstrip("/") for rel in rels}
        workbook = ET.fromstring(book.read("xl/workbook.xml"))
        found = {}
        for sheet in workbook.findall("m:sheets/m:sheet", _NS):
            rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            target = targets[rid].replace("xl/xl/", "xl/")
            found[sheet.attrib["name"]] = _rows(book.read(target), shared)
    return found


def _shared_strings(book: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    root = ET.fromstring(book.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.iter(
        "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")) for item in root]


def _rows(payload: bytes, shared: list[str]) -> list[list[str]]:
    root = ET.fromstring(payload)
    rows = []
    for row in root.findall("m:sheetData/m:row", _NS):
        values = []
        for cell in row.findall("m:c", _NS):
            kind = cell.attrib.get("t")
            if kind == "inlineStr":
                values.append("".join(node.text or "" for node in cell.iter(
                    "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))
            else:
                node = cell.find("m:v", _NS)
                text = node.text if node is not None and node.text else ""
                if kind == "s" and text.isdigit() and int(text) < len(shared):
                    text = shared[int(text)]
                values.append(text.strip())
        rows.append(values)
    return rows
