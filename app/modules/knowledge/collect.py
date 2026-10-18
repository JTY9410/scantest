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


def collect_public() -> dict[str, int]:
    """공개 표준을 저장한 뒤, AI가 있으면 그 목록의 한글 명칭만 고친다."""
    counts = {"commands": 0, "formulas": 0, "dtcs": 0, "ai": 0}
    for item in COMMANDS:
        if _command(item) is not None:
            counts["commands"] += 1
    for item in FORMULAS:
        if _formula(item):
            counts["formulas"] += 1
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
