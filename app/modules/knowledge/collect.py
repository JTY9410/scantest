"""공개 OBD 명령·수식·고장코드 명칭을 지식베이스와 진단코드 마스터에 넣는다.

AI는 이 목록 안의 한글 명칭만 다듬는다. 목록에 없는 코드는 저장하지 않는다.
"""

import json
import re

from sqlalchemy import select

from app.core.errors import ServiceError
from app.extensions import db
from app.modules.knowledge.models import KnowledgeCommand, KnowledgeDTC, KnowledgeFormula
from app.modules.knowledge.public_data import COMMANDS, DTCS, FORMULAS
from app.modules.scans.models import Code

_SYSTEM = (
    "당신은 SAE J2012·ISO 15031-6에 공개된 고장코드만 한글로 부릅니다. "
    "목록에 없는 제조사 코드는 known을 false로 두고 지어내지 마세요. JSON 배열만 답합니다."
)
_SOURCE = "public_docs"


def _loads(text: str) -> list[dict]:
    match = re.search(r"\[.*\]", text or "", re.S)
    if not match:
        return []
    try:
        rows = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return rows if isinstance(rows, list) else []


def _command(item: dict) -> KnowledgeCommand | None:
    command = re.sub(r"\s+", "", item["command"]).upper()
    row = db.session.scalar(select(KnowledgeCommand).where(
        KnowledgeCommand.command == command,
        KnowledgeCommand.source == _SOURCE,
        KnowledgeCommand.maker.is_(None),
    ))
    if row is None:
        row = KnowledgeCommand(command=command, source=_SOURCE, maker=None)
        db.session.add(row)
        created = True
    else:
        created = False
    row.label = item["detail_name"][:200]
    row.detail_name = item["detail_name"][:200]
    row.description = item["description"]
    row.source_detail = "공개 OBD 표준"
    row.status = item["status"]
    row.confidence = 1.0
    return row if created else None


def _formula(item: dict) -> bool:
    row = db.session.scalar(select(KnowledgeFormula).where(
        KnowledgeFormula.pid == item["pid"],
        KnowledgeFormula.source == _SOURCE,
        KnowledgeFormula.maker.is_(None),
    ))
    created = row is None
    if created:
        row = KnowledgeFormula(pid=item["pid"], source=_SOURCE, maker=None, formula=item["formula"])
        db.session.add(row)
    row.command = f"01{item['pid']}"
    row.label = item["detail_name"][:200]
    row.detail_name = item["detail_name"][:200]
    row.formula = item["formula"]
    row.unit = item["unit"]
    row.source_detail = "SAE J1979 공개 수식"
    row.status = "verified"
    row.confidence = 1.0
    return created


def _dtc(item: dict, *, detail_name: str | None = None, description: str | None = None) -> bool:
    name = (detail_name or item["detail_name"])[:200]
    text = description or item["description"]
    code = item["code"].upper()
    row = db.session.scalar(select(KnowledgeDTC).where(
        KnowledgeDTC.code == code, KnowledgeDTC.source == _SOURCE, KnowledgeDTC.maker.is_(None)))
    created = row is None
    if created:
        row = KnowledgeDTC(code=code, source=_SOURCE, description=text)
        db.session.add(row)
    row.detail_name = name
    row.description = text
    row.category = item["unit_name"][:50]
    row.source_detail = "SAE J2012 공개 코드"
    row.status = "verified"
    row.confidence = 1.0
    master = db.session.scalar(select(Code).where(Code.code == code, Code.deleted_at.is_(None)))
    if master is None:
        db.session.add(Code(
            type=item["type"], code=code, unit_name=item["unit_name"][:255],
            desc=name, detail_desc=text, root_cause=item["root_cause"]))
    else:
        master.desc = name
        master.detail_desc = text
        master.unit_name = master.unit_name or item["unit_name"][:255]
        master.root_cause = master.root_cause or item["root_cause"]
        created = False
    return created


def _enrich(catalog: dict[str, dict]) -> int:
    from app.modules.canlab import ai

    updated = 0
    codes = list(catalog)
    for start in range(0, len(codes), 20):
        chunk = codes[start:start + 20]
        prompt = (
            "다음 공개 고장코드의 한글 세부 명칭만 JSON 배열로 답하세요. "
            "항목은 code, detail_name, description, known 입니다. "
            "공개 표준이 아니면 known은 false이고 detail_name은 빈 문자열입니다.\n"
            + ", ".join(chunk)
        )
        answer, _provider = ai.ask(_SYSTEM, prompt)
        for row in _loads(answer):
            code = str(row.get("code") or "").upper()
            if code not in catalog or row.get("known") is not True:
                continue
            name = str(row.get("detail_name") or "").strip()
            text = str(row.get("description") or "").strip()
            if not name or not text:
                continue
            if _dtc(catalog[code], detail_name=name, description=text):
                pass
            updated += 1
    return updated


# obd.PIDS 람다와 같은 SAE J1979 수식. 코드표로만 읽는 PID는 수식을 만들지 않는다.
_PID_FORMULA = {
    0x04: "A * 100 / 255", 0x05: "A - 40", 0x06: "(A - 128) * 100 / 128", 0x07: "(A - 128) * 100 / 128",
    0x08: "(A - 128) * 100 / 128", 0x09: "(A - 128) * 100 / 128", 0x0A: "A * 3", 0x0B: "A",
    0x0C: "((A * 256) + B) / 4", 0x0D: "A", 0x0E: "A / 2 - 64", 0x0F: "A - 40",
    0x10: "((A * 256) + B) / 100", 0x11: "A * 100 / 255",
    0x14: "A / 200", 0x15: "A / 200", 0x16: "A / 200", 0x17: "A / 200",
    0x18: "A / 200", 0x19: "A / 200", 0x1A: "A / 200", 0x1B: "A / 200",
    0x1F: "(A * 256) + B", 0x21: "(A * 256) + B", 0x22: "((A * 256) + B) * 0.079",
    0x23: "((A * 256) + B) * 10", 0x2C: "A * 100 / 255", 0x2D: "(A - 128) * 100 / 128",
    0x2E: "A * 100 / 255", 0x2F: "A * 100 / 255", 0x30: "A", 0x31: "(A * 256) + B", 0x33: "A",
    0x3C: "((A * 256) + B) / 10 - 40", 0x3D: "((A * 256) + B) / 10 - 40",
    0x3E: "((A * 256) + B) / 10 - 40", 0x3F: "((A * 256) + B) / 10 - 40",
    0x42: "((A * 256) + B) / 1000", 0x43: "((A * 256) + B) * 100 / 255",
    0x44: "((A * 256) + B) * 2 / 65536", 0x45: "A * 100 / 255", 0x46: "A - 40",
    0x47: "A * 100 / 255", 0x49: "A * 100 / 255", 0x4A: "A * 100 / 255", 0x4C: "A * 100 / 255",
    0x4D: "(A * 256) + B", 0x4E: "(A * 256) + B", 0x52: "A * 100 / 255",
    0x59: "((A * 256) + B) * 10", 0x5B: "A * 100 / 255", 0x5C: "A - 40",
    0x5D: "((A * 256) + B) / 128 - 210", 0x5E: "((A * 256) + B) / 20",
    0x61: "A - 125", 0x62: "A - 125", 0x63: "(A * 256) + B", 0x8E: "A - 125",
    0xA6: "((A * 16777216) + (B * 65536) + (C * 256) + D) / 10",
}


def _mode01() -> tuple[int, int]:
    """obd.py에 있는 모드 01 PID를 공개 명령·수식으로 넣는다."""
    from app.modules.scanner.obd import PIDS

    commands = formulas = 0
    for number, pid in PIDS.items():
        command = f"01{number:02X}"
        item = {
            "command": command,
            "detail_name": pid.label,
            "description": f"SAE J1979 모드 01 PID {number:02X}. {pid.label}.",
            "status": "verified",
        }
        if _command(item) is not None:
            commands += 1
        formula = _PID_FORMULA.get(number)
        if formula and _formula({
            "pid": f"{number:02X}", "detail_name": pid.label, "formula": formula, "unit": pid.unit or None,
        }):
            formulas += 1
    return commands, formulas


def collect_public() -> dict[str, int]:
    """공개 표준을 저장한 뒤, AI가 있으면 그 목록의 한글 명칭만 고친다."""
    from app.modules.knowledge.service import ensure_lan_terms

    counts = {"commands": 0, "formulas": 0, "dtcs": 0, "ai": 0, "terms": 0}
    for item in COMMANDS:
        if _command(item) is not None:
            counts["commands"] += 1
    for item in FORMULAS:
        if _formula(item):
            counts["formulas"] += 1
    extra_commands, extra_formulas = _mode01()
    counts["commands"] += extra_commands
    counts["formulas"] += extra_formulas
    counts["terms"] = ensure_lan_terms()
    catalog = {item["code"]: item for item in DTCS}
    for item in DTCS:
        if _dtc(item):
            counts["dtcs"] += 1
    try:
        counts["ai"] = _enrich(catalog)
    except (ServiceError, RuntimeError, TimeoutError, OSError):
        counts["ai"] = 0
    db.session.commit()
    return counts
