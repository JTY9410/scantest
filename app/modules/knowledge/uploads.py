"""관리자가 올린 엑셀·PDF에서 고장코드와 읽기 명령을 초안으로 넣는다.

세션 변경·보안·쓰기·지우기 명령은 저장하지 않는다. 올린 내용은 확인 전 초안이다.
"""

import io
import re
import zipfile
from xml.etree import ElementTree as ET

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import ServiceError
from app.extensions import db
from app.modules.knowledge.models import KnowledgeCommand, KnowledgeDTC, KnowledgeFormula

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_SOURCE = "upload"
_MAX_BYTES = 4 * 1024 * 1024
_MAX_ROWS = 2000
_DTC = re.compile(r"\b([PCBU][0-9A-F]{4})\b", re.I)
_HEADER = re.compile(r"^7[0-9A-F]{2}$")
_BYTE = re.compile(r"^[0-9A-F]{2}$")
_PACKED = re.compile(r"^([0-9A-F]{2}){2,8}$")
_BLOCKED = {"10", "27", "2E", "31", "04", "14"}
_CODE_HEADERS = {"코드", "code", "dtc", "고장코드"}
_NAME_HEADERS = {"명칭", "이름", "세부명칭", "detail", "name"}
_DESC_HEADERS = {"설명", "description", "내용"}
_COMMAND_HEADERS = {"명령", "command", "커맨드"}
_ADDRESS_HEADERS = {"주소", "header", "헤더", "ecu"}
_FORMULA_HEADERS = {"수식", "formula"}
_UNIT_HEADERS = {"단위", "unit"}


def import_dtc_file(filename: str, content: bytes, maker: str | None = None) -> dict[str, int]:
    """고장코드 문서를 읽고 초안으로 저장한다."""
    counts = {"found": 0, "saved": 0, "kept": 0}
    maker_name = (maker or "").strip()[:50] or None
    detail = _filename(filename)
    for line in _lines(filename, content):
        code = _column(line, _CODE_HEADERS)
        named = " ".join(part for part in (
            _column(line, _NAME_HEADERS), _column(line, _DESC_HEADERS)) if part)
        text = named or line.get("_text", "")
        codes = [code.upper()] if code and _DTC.fullmatch(code.strip()) else _DTC.findall(text)
        for item in codes:
            if counts["found"] >= _MAX_ROWS:
                break
            counts["found"] += 1
            description = _DTC.sub("", text).strip(" :-·\t")[:500] or "문서에 설명 없이 적힌 코드"
            if _save_dtc(item.upper(), description, maker_name, detail):
                counts["saved"] += 1
            else:
                counts["kept"] += 1
    _commit()
    return counts


def import_command_file(filename: str, content: bytes, maker: str | None = None) -> dict[str, int]:
    """CAN 명령 문서를 읽고 읽기 명령만 초안으로 저장한다."""
    counts = {"found": 0, "saved": 0, "kept": 0, "skipped": 0}
    maker_name = (maker or "").strip()[:50] or None
    detail = _filename(filename)
    for line in _lines(filename, content):
        parsed = _command_line(line)
        if parsed is None:
            continue
        command, header, label, formula, unit = parsed
        if counts["found"] >= _MAX_ROWS:
            break
        counts["found"] += 1
        if command[:2] in _BLOCKED or command in {"04", "14FFFFFF"}:
            counts["skipped"] += 1
            continue
        if _save_command(command, header, label, formula, unit, maker_name, detail):
            counts["saved"] += 1
        else:
            counts["kept"] += 1
    _commit()
    return counts


def _lines(filename: str, content: bytes) -> list[dict]:
    name = (filename or "").rsplit("/", 1)[-1]
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in {"xlsx", "pdf"}:
        raise ServiceError("xlsx 또는 pdf 파일만 올릴 수 있습니다.")
    if not content:
        raise ServiceError("빈 파일입니다.")
    if len(content) > _MAX_BYTES:
        raise ServiceError("파일이 너무 큽니다. 4MB 이하만 올릴 수 있습니다.", 413)
    if suffix == "pdf":
        return [{"_text": line} for line in _pdf_lines(content)]
    return _sheet_lines(content)


def _pdf_lines(content: bytes) -> list[str]:
    try:
        reader = PdfReader(io.BytesIO(content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except PdfReadError as exc:
        raise ServiceError("PDF를 읽지 못했습니다.") from exc
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ServiceError("PDF에서 글자를 찾지 못했습니다. 글자가 있는 PDF를 올려 주세요.")
    return lines


def _sheet_lines(content: bytes) -> list[dict]:
    try:
        book = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ServiceError("엑셀 파일을 읽지 못했습니다.") from exc
    with book:
        shared = _shared_strings(book)
        rows = []
        for payload in _sheet_payloads(book):
            rows.extend(_rows(payload, shared))
    if not rows:
        raise ServiceError("엑셀에서 내용을 찾지 못했습니다.")
    headers = [_key(cell) for cell in rows[0]]
    if _CODE_HEADERS.intersection(headers) or _COMMAND_HEADERS.intersection(headers):
        return [dict(zip(headers, row, strict=False)) | {"_text": " ".join(row)} for row in rows[1:] if any(row)]
    return [{"_text": " ".join(row)} for row in rows if any(row)]


def _shared_strings(book: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    root = ET.fromstring(book.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.iter(
        "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")) for item in root]


def _sheet_payloads(book: zipfile.ZipFile) -> list[bytes]:
    rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
    targets = {rel.attrib["Id"]: "xl/" + rel.attrib["Target"].lstrip("/") for rel in rels}
    workbook = ET.fromstring(book.read("xl/workbook.xml"))
    payloads = []
    for sheet in workbook.findall("m:sheets/m:sheet", _NS):
        rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        target = targets[rid].replace("xl/xl/", "xl/")
        payloads.append(book.read(target))
    return payloads


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
                values.append(text)
        rows.append([value.strip() for value in values])
    return rows


def _column(line: dict, names: set[str]) -> str:
    for key, value in line.items():
        if key in names and value:
            return str(value).strip()
    return ""


def _key(cell: str) -> str:
    return re.sub(r"[\s_]+", "", cell).casefold()


def _command_line(line: dict) -> tuple[str, str | None, str | None, str | None, str | None] | None:
    explicit = _column(line, _COMMAND_HEADERS)
    header = _column(line, _ADDRESS_HEADERS).upper() or None
    formula = _column(line, _FORMULA_HEADERS) or None
    unit = _column(line, _UNIT_HEADERS)[:20] or None
    label = _column(line, _NAME_HEADERS) or _column(line, _DESC_HEADERS) or None
    source = explicit or line.get("_text", "")
    if _DTC.search(source) and not explicit:
        return None
    command, found_header, words = _split_command(source)
    if not command:
        return None
    header = header if header and _HEADER.fullmatch(header) else found_header
    return command, header, (label or " ".join(words) or None), formula, unit


def _split_command(text: str) -> tuple[str, str | None, list[str]]:
    header = None
    raw = []
    words = []
    for token in text.replace(",", " ").split():
        compact = token.upper()
        if header is None and _HEADER.fullmatch(compact):
            header = compact
        elif _BYTE.fullmatch(compact):
            raw.append(compact)
        elif _PACKED.fullmatch(compact) and not _DTC.fullmatch(compact):
            raw.extend(compact[index:index + 2] for index in range(0, len(compact), 2))
        else:
            words.append(token)
    command = "".join(raw)[:16]
    if not re.fullmatch(r"([0-9A-F]{2}){1,8}", command):
        return "", header, words
    return command, header, words


def _save_dtc(code: str, description: str, maker: str | None, detail: str) -> bool:
    row = db.session.scalar(select(KnowledgeDTC).where(
        KnowledgeDTC.code == code, KnowledgeDTC.source == _SOURCE,
        KnowledgeDTC.maker == maker if maker else KnowledgeDTC.maker.is_(None)))
    created = row is None
    if row is not None and row.status != "draft":
        return False
    if created:
        row = KnowledgeDTC(code=code, maker=maker, source=_SOURCE, description=description)
        db.session.add(row)
    row.detail_name = description[:200]
    row.description = description
    row.source_detail = detail
    row.status = "draft"
    row.confidence = 0.4
    return created


def _save_command(command, header, label, formula, unit, maker, detail) -> bool:
    row = db.session.scalar(select(KnowledgeCommand).where(
        KnowledgeCommand.command == command, KnowledgeCommand.source == _SOURCE,
        KnowledgeCommand.header == header if header else KnowledgeCommand.header.is_(None),
        KnowledgeCommand.maker == maker if maker else KnowledgeCommand.maker.is_(None)))
    created = row is None
    if row is not None and row.status != "draft":
        return False
    if created:
        row = KnowledgeCommand(command=command, header=header, maker=maker, source=_SOURCE)
        db.session.add(row)
    row.label = (label or command)[:200]
    row.detail_name = row.label
    row.description = label
    row.source_detail = detail
    row.status = "draft"
    row.confidence = 0.4
    if formula:
        _save_formula(command, row.label, formula, unit, maker, detail)
    return created


def _save_formula(command, label, formula, unit, maker, detail) -> None:
    row = db.session.scalar(select(KnowledgeFormula).where(
        KnowledgeFormula.command == command, KnowledgeFormula.source == _SOURCE,
        KnowledgeFormula.label == label[:200],
        KnowledgeFormula.maker == maker if maker else KnowledgeFormula.maker.is_(None)))
    if row is not None and row.status != "draft":
        return
    if row is None:
        row = KnowledgeFormula(command=command, label=label[:200], formula=formula[:500],
                               maker=maker, source=_SOURCE)
        db.session.add(row)
    row.formula = formula[:500]
    row.unit = unit
    row.detail_name = label[:200]
    row.source_detail = detail
    row.status = "draft"
    row.confidence = 0.4


def _filename(filename: str) -> str:
    return (filename or "upload").rsplit("/", 1)[-1][:200]


def _commit() -> None:
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ServiceError("같은 항목이 이미 다른 형식으로 저장되어 있습니다.") from exc
