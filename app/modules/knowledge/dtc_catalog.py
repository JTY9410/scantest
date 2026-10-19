"""제조사별 DTC 설명 엑셀(dtc_description_*.xlsx)을 지식베이스에 넣는다.

시트 이름 maker제조사_제어기`, 열은 id·code·detail·pbcu·memo 이다. 확인 전 초안으로만 저장한다.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.errors import ServiceError
from app.extensions import db
from app.modules.knowledge.models import KnowledgeDTC
from app.modules.scans.models import Code

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_SOURCE = "upload"
_FILE = "dtc_description_20261019.xlsx"
_STD = re.compile(r"^([PCBU][0-9A-F]{4,8})$", re.I)
_IN_TEXT = re.compile(r"\(([PCBU][0-9A-F]{4,8})(?:\s|/|-|,|\))", re.I)
_HEX = re.compile(r"^[0-9A-F]{3,8}$")
_MAKER_PREFIXES = (
    ("toyota_lexus", "Toyota/Lexus"),
    ("audi_vw", "Audi/VW"),
    ("renault_korea", "르노코리아"),
    ("landrover", "Land Rover"),
    ("polestar", "Polestar"),
    ("lincoln", "Lincoln"),
    ("nissan", "Nissan"),
    ("honda", "Honda"),
    ("hyundai", "Hyundai"),
    ("kia", "Kia"),
    ("benz", "Mercedes-Benz"),
    ("bmw", "BMW"),
    ("ford", "Ford"),
    ("gm", "GM"),
    ("volvo", "Volvo"),
    ("mazda", "Mazda"),
    ("subaru", "Subaru"),
    ("mitsubishi", "Mitsubishi"),
    ("ssangyong", "SsangYong"),
    ("chrysler", "Chrysler"),
    ("jeep", "Jeep"),
    ("tesla", "Tesla"),
)


def catalog_path() -> Path:
    path = Path(__file__).resolve().parents[3] / _FILE
    if not path.is_file():
        raise ServiceError(f"고장코드 설명 문서({_FILE})를 찾지 못했습니다.")
    return path


def import_dtc_catalog(path: Path | None = None) -> dict[str, int]:
    """제조사별 고장코드 설명을 초안으로 넣는다. 다시 실행해도 같은 출처는 한 건이다."""
    counts = {"sheet": 0, "saved": 0, "dtcs": 0, "kept": 0}
    for sheet_name, rows in _sheets(path or catalog_path()).items():
        maker, ecu = _scope(sheet_name)
        headers = [_key(cell) for cell in (rows[0] if rows else [])]
        if not {"code", "detail"}.issubset(set(headers)):
            continue
        for row in rows[1:]:
            line = dict(zip(headers, row, strict=False))
            code = _normalize(line.get("code", ""), line.get("pbcu", ""), line.get("detail", ""))
            detail = (line.get("detail") or "").strip()
            if not code or not detail:
                continue
            counts["sheet"] += 1
            memo = " · ".join(part for part in (line.get("memo", "").strip(), line.get("code", "").strip()) if part)
            outcome = _upsert_dtc(
                code=code, maker=maker, ecu=ecu, detail=detail, memo=memo or None,
                source_detail=f"{_FILE}:{sheet_name}",
            )
            if outcome == "created":
                counts["dtcs"] += 1
            elif outcome == "kept":
                counts["kept"] += 1
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ServiceError("같은 고장코드가 이미 다른 형식으로 저장되어 있습니다.") from exc
    counts["saved"] = db.session.scalar(select(func.count()).select_from(KnowledgeDTC).where(
        KnowledgeDTC.source == _SOURCE,
        KnowledgeDTC.source_detail.like(f"{_FILE}:%"),
    )) or 0
    return counts


def _upsert_dtc(*, code: str, maker: str, ecu: str | None, detail: str, memo: str | None,
                source_detail: str) -> str:
    existing = db.session.scalar(select(KnowledgeDTC).where(
        KnowledgeDTC.code == code,
        KnowledgeDTC.source == _SOURCE,
        KnowledgeDTC.maker == maker,
    ))
    created = existing is None
    if existing is not None and existing.status != "draft":
        return "kept"
    if created:
        existing = KnowledgeDTC(code=code, maker=maker, source=_SOURCE, description=detail)
        db.session.add(existing)
    existing.detail_name = detail[:200]
    existing.description = detail
    existing.ecu_name = (ecu or "")[:100] or None
    existing.notes = (memo or "")[:2000] or None
    existing.source_detail = source_detail[:500]
    existing.status = "draft"
    existing.confidence = 0.5
    _upsert_code(code, detail, ecu)
    return "created" if created else "kept"


def _upsert_code(code: str, detail: str, ecu: str | None) -> None:
    """스캔 화면이 읽는 마스터에는 표준 5자리 코드만 참고로 넣는다."""
    master_code = code[:5] if _STD.fullmatch(code) and len(code) >= 5 else None
    if master_code is None or not re.fullmatch(r"[PCBU][0-9A-F]{4}", master_code):
        return
    kind = "ev" if any(word in detail for word in ("전기", "하이브리드", "배터리", "EV", "HV", "고전압")) else "ice"
    row = db.session.scalar(select(Code).where(Code.code == master_code, Code.deleted_at.is_(None)))
    note = f"제조사 자료(확인 전). {detail}"[:4000]
    if row is None:
        db.session.add(Code(
            type=kind, code=master_code, unit_name=(ecu or "OBD")[:255],
            desc=detail[:2000], detail_desc=note))
        return
    if not row.desc:
        row.desc = detail[:2000]
    if not row.detail_desc:
        row.detail_desc = note
    row.unit_name = row.unit_name or (ecu or "OBD")[:255]


def _normalize(code: str, pbcu: str, detail: str) -> str:
    for candidate in (pbcu.strip(),):
        compact = candidate.upper().replace("-", "").replace(" ", "")
        if _STD.fullmatch(compact):
            return compact[:20]
    match = _IN_TEXT.search(detail or "")
    if match:
        return match.group(1).upper()[:20]
    compact = (code or "").strip().upper().replace("-", "").replace(" ", "")
    if _STD.fullmatch(compact):
        return compact[:20]
    if _HEX.fullmatch(compact):
        return compact[:20]
    return ""


def _scope(sheet_name: str) -> tuple[str, str | None]:
    name = sheet_name.strip()
    for prefix, label in _MAKER_PREFIXES:
        if name == prefix or name.startswith(prefix + "_"):
            ecu = name[len(prefix) + 1:] if name.startswith(prefix + "_") else None
            return label, (ecu or None)
    if "_" in name:
        maker, ecu = name.split("_", 1)
        return maker[:50], ecu[:100]
    return name[:50], None


def _key(cell: str) -> str:
    return re.sub(r"[\s_]+", "", cell).casefold()


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
