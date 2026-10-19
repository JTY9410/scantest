"""지식베이스 조회·검증·스캔 연결."""
import json
import re
from sqlalchemy import func, or_, select

from app.core.errors import ServiceError
from app.core.time import utcnow
from app.extensions import db
from app.modules.knowledge.models import (
    KnowledgeCommand,
    KnowledgeDTC,
    KnowledgeFormula,
    KnowledgeTerm,
)


def list_commands(*, status: str | None = "verified", maker: str | None = None, limit: int = 100):
    """명령 목록. 상태를 비우면 검증과 초안을 함께 보여 준다."""
    stmt = select(KnowledgeCommand).order_by(KnowledgeCommand.command)
    if status:
        stmt = stmt.where(KnowledgeCommand.status == status)
    if maker:
        stmt = stmt.where(or_(KnowledgeCommand.maker == maker, KnowledgeCommand.maker.is_(None)))
    stmt = stmt.limit(limit)
    return db.session.scalars(stmt).all()


def command_views(*, status: str | None = None, maker: str | None = None, limit: int = 500):
    """명령과, 그 명령이 읽는 데이터(수식)를 명령 다음에 붙인다."""
    formulas = db.session.scalars(select(KnowledgeFormula)).all()
    views = []
    for row in list_commands(status=status, maker=maker, limit=limit):
        command = (row.command or "").upper()
        pid = command[2:] if command.startswith("01") and len(command) == 4 else ""
        data = [item for item in formulas if _formula_for(item, row, command, pid)]
        views.append({"row": row, "data": data})
    return views


def _formula_for(item: KnowledgeFormula, row: KnowledgeCommand, command: str, pid: str) -> bool:
    same_command = (item.command or "").upper() == command or (pid and (item.pid or "").upper() == pid)
    if not same_command:
        return False
    if item.maker and row.maker and item.maker != row.maker:
        return False
    if item.model and row.model and item.model != row.model:
        return False
    return True


def list_formulas(*, status: str = "verified", maker: str | None = None, limit: int = 100):
    """해석에 쓸 수식. 기본은 검증된 항목만."""
    stmt = select(KnowledgeFormula).where(KnowledgeFormula.status == status).order_by(KnowledgeFormula.pid)
    if maker:
        stmt = stmt.where(or_(KnowledgeFormula.maker == maker, KnowledgeFormula.maker.is_(None)))
    stmt = stmt.limit(limit)
    return db.session.scalars(stmt).all()


def list_dtcs(*, status: str | None = "verified", maker: str | None = None, limit: int = 1000):
    """고장코드 뜻. 상태를 비우면 검증과 초안을 함께 보여 준다."""
    stmt = select(KnowledgeDTC).order_by(KnowledgeDTC.code)
    if status:
        stmt = stmt.where(KnowledgeDTC.status == status)
    if maker:
        stmt = stmt.where(or_(KnowledgeDTC.maker == maker, KnowledgeDTC.maker.is_(None)))
    stmt = stmt.limit(limit)
    return db.session.scalars(stmt).all()


def list_terms(*, status: str = "verified", limit: int = 500):
    """용어 목록."""
    stmt = select(KnowledgeTerm).where(KnowledgeTerm.status == status).order_by(KnowledgeTerm.term).limit(limit)
    return db.session.scalars(stmt).all()


def verify_command(command_id: int, user_id: int):
    """명령을 검증됨으로 표시한다. 세션·쓰기·지우기 명령은 검증하지 않는다."""
    cmd = db.session.get(KnowledgeCommand, command_id)
    if cmd is None:
        return
    if _blocked_command(cmd.command):
        raise ServiceError("세션 변경·보안·쓰기·지우기 명령은 검증할 수 없습니다.")
    cmd.status = "verified"
    cmd.verified_by = user_id
    cmd.verified_at = utcnow()
    db.session.commit()


def verify_formula(formula_id: int, user_id: int):
    """수식을 검증됨으로 표시한다."""
    formula = db.session.get(KnowledgeFormula, formula_id)
    if formula:
        formula.status = "verified"
        formula.verified_by = user_id
        formula.verified_at = utcnow()
        db.session.commit()


def verify_dtc(dtc_id: int, user_id: int):
    """고장코드 뜻을 검증됨으로 표시한다."""
    dtc = db.session.get(KnowledgeDTC, dtc_id)
    if dtc:
        dtc.status = "verified"
        dtc.verified_by = user_id
        dtc.verified_at = utcnow()
        db.session.commit()


def import_from_commands_json(commands_data: list[dict]) -> int:
    """위스캔 분석 commands.json의 명령을 검증된 지식으로 넣는다."""
    count = 0
    for cmd_data in commands_data:
        # Check if already exists
        existing = db.session.scalar(
            select(KnowledgeCommand).where(
                KnowledgeCommand.command == cmd_data.get("command"),
                KnowledgeCommand.source == "wescan",
            ).limit(1)
        )
        if existing:
            continue
        
        cmd = KnowledgeCommand(
            maker=cmd_data.get("maker"),
            model=cmd_data.get("model"),
            ecu_name=cmd_data.get("ecu"),
            header=cmd_data.get("header"),
            command=cmd_data.get("command"),
            label=cmd_data.get("label"),
            description=cmd_data.get("description"),
            source="wescan",
            source_detail=cmd_data.get("source_detail", "위스캔 앱 분석에서 가져옴"),
            confidence=1.0,
            status="verified",
        )
        db.session.add(cmd)
        count += 1
    
    db.session.commit()
    return count


_READ = re.compile(r"^([0-9A-F]{2}){1,8}$")
_BLOCKED = {"10", "27", "2E", "31", "04", "14"}


def _scope(maker: str | None):
    if maker:
        return or_(KnowledgeCommand.maker == maker, KnowledgeCommand.maker.is_(None))
    return KnowledgeCommand.maker.is_(None)


def scan_commands(maker: str | None = None, limit: int = 40) -> list[dict]:
    """스캔 계획에 넣을 검증된 읽기 명령. 세션·보안·쓰기·루틴은 빼니다."""
    stmt = select(KnowledgeCommand).where(KnowledgeCommand.status == "verified", _scope(maker))
    rows = []
    for row in db.session.scalars(stmt.order_by(KnowledgeCommand.id.desc()).limit(limit * 2)):
        command = re.sub(r"\s+", "", row.command or "").upper()
        if not _READ.fullmatch(command) or command[:2] in _BLOCKED:
            continue
        header = (row.header or "").strip().upper() or None
        rows.append({"header": header, "command": command, "label": row.label or command})
        if len(rows) >= limit:
            break
    return rows


def verified_layouts(maker: str | None = None, limit: int = 40) -> list[dict]:
    """적용 규칙이 없는 신호를 읽을 검증 수식. source_detail에 layout·signal_key가 있을 때만."""
    stmt = select(KnowledgeFormula).where(KnowledgeFormula.status == "verified")
    if maker:
        stmt = stmt.where(or_(KnowledgeFormula.maker == maker, KnowledgeFormula.maker.is_(None)))
    else:
        stmt = stmt.where(KnowledgeFormula.maker.is_(None))
    found = []
    for row in db.session.scalars(stmt.order_by(KnowledgeFormula.id.desc()).limit(limit * 2)):
        try:
            detail = json.loads(row.source_detail or "")
            layout = detail["layout"]
            signal_key = detail["signal_key"]
        except (TypeError, ValueError, KeyError):
            continue
        found.append({"signal_key": signal_key, "layout": layout, "label": row.label, "unit": row.unit,
                      "formula": row.formula})
        if len(found) >= limit:
            break
    return found


def formula_names() -> dict[str, str]:
    """검증된 공개 수식의 세부 명칭. 키는 PID 16진수(0C)."""
    rows = db.session.scalars(select(KnowledgeFormula).where(
        KnowledgeFormula.status == "verified",
        KnowledgeFormula.detail_name.is_not(None),
    ))
    return {row.pid.upper(): row.detail_name for row in rows if row.pid and row.detail_name}


def lookup_dtcs(codes: set[str]) -> dict[str, KnowledgeDTC]:
    """검증된 고장코드 명칭. 초안은 스캔 설명에 쓰지 않는다."""
    if not codes:
        return {}
    rows = db.session.scalars(select(KnowledgeDTC).where(
        KnowledgeDTC.code.in_(codes), KnowledgeDTC.status == "verified").order_by(KnowledgeDTC.id))
    chosen: dict[str, KnowledgeDTC] = {}
    for row in rows:
        current = chosen.get(row.code)
        if current is None or (current.source != "public_docs" and row.source == "public_docs"):
            chosen[row.code] = row
    return chosen


_UNKNOWN_DTC = "공개된 설명이 없습니다. 역분석 또는 관리자 확인 전입니다."
_DTC = re.compile(r"^[PCBU][0-9A-F]{4}$")
_STATUSES = {"draft", "verified", "deprecated"}
_LAN_TERMS = (
    {
        "term": "DoIP",
        "abbreviation": "ISO 13400",
        "category": "연결",
        "definition": (
            "ISO 13400 차량 이더넷 진단입니다. OBD 단자의 이더넷 핀과 전용 장비가 필요합니다. "
            "ELM327 계열 진단기는 이 프레임을 보내지 못하므로 이 프로그램은 스캔 단계로 넣지 않고 안내만 남깁니다."
        ),
    },
    {
        "term": "OBD 이더넷 핀",
        "abbreviation": None,
        "category": "연결",
        "definition": (
            "OBD 커넥터의 이더넷 핀은 DoIP 전용 장비로 연결합니다. "
            "이 스캔은 그 핀으로 진단 프레임을 보내지 않습니다."
        ),
    },
)


def inventory() -> dict[str, list[dict] | int]:
    """명령·수식·고장코드·용어를 출처와 상태별 건수로 모은다."""
    def grouped(model) -> list[dict]:
        rows = db.session.execute(
            select(model.source, model.status, func.count()).group_by(model.source, model.status)
            .order_by(model.source, model.status))
        return [{"source": source, "status": status, "count": count} for source, status, count in rows]

    maker_dtcs = db.session.scalar(select(func.count()).select_from(KnowledgeDTC).where(
        KnowledgeDTC.maker.is_not(None))) or 0
    return {"commands": grouped(KnowledgeCommand), "formulas": grouped(KnowledgeFormula),
            "dtcs": grouped(KnowledgeDTC), "terms": grouped(KnowledgeTerm), "maker_dtcs": maker_dtcs}


def status_totals(kind: str, maker: str | None = None) -> dict[str, int]:
    """화면 필터와 상관없이 상태별 전체 건수를 센다."""
    model = KnowledgeCommand if kind == "command" else KnowledgeDTC
    stmt = select(model.status, func.count()).group_by(model.status)
    if maker:
        stmt = stmt.where(model.maker == maker)
    counts = {status: count for status, count in db.session.execute(stmt)}
    return {
        "all": sum(counts.values()),
        "verified": counts.get("verified", 0),
        "draft": counts.get("draft", 0),
        "deprecated": counts.get("deprecated", 0),
    }


def _blocked_command(command: str) -> bool:
    compact = re.sub(r"\s+", "", command or "").upper()
    return compact[:2] in _BLOCKED or compact in {"04", "14FFFFFF"}


def _status(value: str | None) -> str:
    status = (value or "draft").strip()
    if status not in _STATUSES:
        raise ServiceError("상태를 고르세요.")
    return status


def _text(value: str | None, limit: int) -> str | None:
    text = (value or "").strip()
    return text[:limit] or None


def analyze_unknown_dtcs() -> dict[str, int]:
    """설명 없는 초안만 AI로 본다. 공개 표준은 초안 설명에, 추정은 notes에만 남긴다."""
    from app.modules.canlab import ai

    rows = list(db.session.scalars(select(KnowledgeDTC).where(
        KnowledgeDTC.status == "draft", KnowledgeDTC.description == _UNKNOWN_DTC).limit(20)))
    if not rows:
        raise ServiceError("분석할 설명 없는 고장코드가 없습니다.")
    by_code = {row.code: row for row in rows}
    prompt = (
        "다음 고장코드마다 JSON 배열로 답하세요. 항목은 code, known, detail_name, desc, guess 입니다. "
        "SAE J2012·ISO 15031-6에 공개된 코드만 known을 true로 두고 desc에 한글 설명을 적으세요. "
        "공개 표준이 아니면 known은 false, desc는 빈 문자열, guess에만 추정 한 줄을 적으세요.\n"
        + ", ".join(by_code)
    )
    answer, _provider = ai.ask(
        "당신은 공개된 OBD 고장코드만 확정해서 적습니다. 제조사 코드는 추정으로만 적고 JSON 배열만 답합니다.",
        prompt)
    described = guessed = skipped = 0
    match = re.search(r"\[.*\]", answer or "", re.S)
    try:
        parsed = json.loads(match.group(0)) if match else []
    except json.JSONDecodeError as exc:
        raise ServiceError("AI 응답을 읽지 못했습니다.") from exc
    if not isinstance(parsed, list):
        parsed = []
    for item in parsed:
        code = str(item.get("code") or "").upper()
        row = by_code.get(code)
        if row is None:
            skipped += 1
            continue
        if item.get("known") is True:
            desc = str(item.get("desc") or "").strip()
            name = str(item.get("detail_name") or "").strip()
            if not desc:
                skipped += 1
                continue
            row.description = desc[:2000]
            row.detail_name = name[:200] or row.detail_name
            row.source_detail = "공개 표준을 AI로 확인"
            row.confidence = 0.5
            described += 1
            continue
        guess = str(item.get("guess") or "").strip()
        if not guess:
            skipped += 1
            continue
        row.notes = f"추정: {guess}"[:4000]
        row.source_detail = "공개 표준이 아닌 추정"
        row.confidence = 0.2
        guessed += 1
    db.session.commit()
    return {"described": described, "guessed": guessed, "skipped": skipped}


def ensure_lan_terms() -> int:
    """DoIP를 보낼 수 없다는 공개된 사실을 용어 초안으로 남긴다."""
    added = 0
    for item in _LAN_TERMS:
        existing = db.session.scalar(select(KnowledgeTerm.id).where(KnowledgeTerm.term == item["term"]))
        if existing is not None:
            continue
        db.session.add(KnowledgeTerm(
            term=item["term"], abbreviation=item["abbreviation"], definition=item["definition"],
            category=item["category"], source="public_docs", source_detail="ISO 13400 공개 설명",
            status="draft"))
        added += 1
    if added:
        db.session.flush()
    return added


def save_command(form) -> KnowledgeCommand:
    """관리자가 명령을 추가하거나 고친다."""
    command = re.sub(r"\s+", "", form.get("command") or "").upper()
    if not command:
        raise ServiceError("명령을 입력하세요.")
    status = _status(form.get("status"))
    if status == "verified" and _blocked_command(command):
        raise ServiceError("세션 변경·보안·쓰기·지우기 명령은 검증할 수 없습니다.")
    row = db.session.get(KnowledgeCommand, int(form["id"])) if form.get("id") else None
    if form.get("id") and row is None:
        raise ServiceError("명령을 찾지 못했습니다.")
    if row is None:
        row = KnowledgeCommand(command=command, source=(form.get("source") or "manual")[:50] or "manual")
        db.session.add(row)
    row.command = command[:200]
    row.header = _text(form.get("header"), 10)
    row.maker = _text(form.get("maker"), 50)
    row.model = _text(form.get("model"), 100)
    row.ecu_name = _text(form.get("ecu_name"), 100)
    row.detail_name = _text(form.get("detail_name"), 200)
    row.label = row.detail_name or command[:200]
    row.description = _text(form.get("description"), 5000)
    row.status = status
    _save_collected(row, form.get("formula"), form.get("unit"))
    db.session.commit()
    return row


def _save_collected(row: KnowledgeCommand, formula: str | None, unit: str | None) -> None:
    """명령이 읽는 데이터의 수식과 단위를 같은 범위에 저장한다."""
    text = (formula or "").strip()
    if not text:
        return
    command = (row.command or "").upper()
    pid = command[2:] if command.startswith("01") and len(command) == 4 else None
    existing = db.session.scalar(select(KnowledgeFormula).where(
        KnowledgeFormula.command == command,
        KnowledgeFormula.maker == row.maker if row.maker else KnowledgeFormula.maker.is_(None),
        KnowledgeFormula.model == row.model if row.model else KnowledgeFormula.model.is_(None),
    ))
    if existing is None:
        existing = KnowledgeFormula(
            command=command, pid=pid, maker=row.maker, model=row.model, label=(row.detail_name or command)[:200],
            formula=text[:5000], source=row.source or "manual", status=row.status)
        db.session.add(existing)
    existing.formula = text[:5000]
    existing.unit = _text(unit, 20) or existing.unit
    existing.label = (row.detail_name or existing.label or command)[:200]
    existing.detail_name = row.detail_name or existing.detail_name


def delete_command(command_id: int) -> None:
    row = db.session.get(KnowledgeCommand, command_id)
    if row is None:
        raise ServiceError("명령을 찾지 못했습니다.")
    db.session.delete(row)
    db.session.commit()


def save_dtc(form) -> KnowledgeDTC:
    """관리자가 고장코드 뜻을 추가하거나 고친다."""
    code = (form.get("code") or "").strip().upper()
    if not _DTC.fullmatch(code):
        raise ServiceError("고장코드 형식이 아닙니다.")
    description = (form.get("description") or "").strip()
    if not description:
        raise ServiceError("설명을 입력하세요.")
    row = db.session.get(KnowledgeDTC, int(form["id"])) if form.get("id") else None
    if form.get("id") and row is None:
        raise ServiceError("고장코드를 찾지 못했습니다.")
    if row is None:
        row = KnowledgeDTC(code=code, description=description[:2000], source="manual")
        db.session.add(row)
    row.code = code
    row.maker = _text(form.get("maker"), 50)
    row.detail_name = _text(form.get("detail_name"), 200)
    row.description = description[:2000]
    row.notes = _text(form.get("notes"), 4000)
    row.status = _status(form.get("status"))
    db.session.commit()
    return row


def delete_dtc(dtc_id: int) -> None:
    row = db.session.get(KnowledgeDTC, dtc_id)
    if row is None:
        raise ServiceError("고장코드를 찾지 못했습니다.")
    db.session.delete(row)
    db.session.commit()


def save_term(form) -> KnowledgeTerm:
    """관리자가 용어를 추가하거나 고친다."""
    term = (form.get("term") or "").strip()
    definition = (form.get("definition") or "").strip()
    if not term or not definition:
        raise ServiceError("용어와 설명을 입력하세요.")
    row = db.session.get(KnowledgeTerm, int(form["id"])) if form.get("id") else None
    if form.get("id") and row is None:
        raise ServiceError("용어를 찾지 못했습니다.")
    taken = db.session.scalar(select(KnowledgeTerm).where(KnowledgeTerm.term == term[:100]))
    if taken is not None and taken is not row:
        raise ServiceError("같은 용어가 이미 있습니다.")
    if row is None:
        row = KnowledgeTerm(term=term[:100], definition=definition, source="manual")
        db.session.add(row)
    row.term = term[:100]
    row.definition = definition
    row.category = _text(form.get("category"), 50)
    row.status = _status(form.get("status"))
    db.session.commit()
    return row


def delete_term(term_id: int) -> None:
    row = db.session.get(KnowledgeTerm, term_id)
    if row is None:
        raise ServiceError("용어를 찾지 못했습니다.")
    db.session.delete(row)
    db.session.commit()


def remember_seen_commands(maker: str | None, model: str | None, steps: list[dict]) -> int:
    """응답한 읽기 명령을 초안으로 남긴다. 있는 행과 막힌 명령은 건드리지 않는다."""
    maker_name = (maker or "").strip() or None
    model_name = (model or "").strip() or None
    if model_name == "미확인":
        model_name = None
    added = 0
    seen = set()
    for step in steps or []:
        if step.get("status") != "ok":
            continue
        command = re.sub(r"\s+", "", str(step.get("command") or "")).upper()
        if (not _READ.fullmatch(command) or _blocked_command(command) or command.startswith("AT")):
            continue
        header = (str(step.get("header")).strip().upper() if step.get("header") else "") or None
        key = (maker_name, header, command)
        if key in seen:
            continue
        seen.add(key)
        existing = db.session.scalar(select(KnowledgeCommand.id).where(
            KnowledgeCommand.command == command,
            KnowledgeCommand.maker == maker_name if maker_name else KnowledgeCommand.maker.is_(None),
            KnowledgeCommand.header == header if header else KnowledgeCommand.header.is_(None),
        ))
        if existing is not None:
            continue
        label = str(step.get("label") or command).strip()[:200]
        db.session.add(KnowledgeCommand(
            maker=maker_name, model=model_name, header=header, command=command, label=label,
            detail_name=label, description=label, source="scan_log", source_detail="스캔에서 응답한 읽기",
            status="draft", confidence=0.5))
        added += 1
    if added:
        db.session.flush()
    return added


def remember_unknown_dtcs(maker: str | None, codes: list[str]) -> int:
    """설명 없는 고장코드를 제조사 초안으로만 남긴다. 뜻을 만들지 않는다."""
    maker_name = (maker or "").strip() or None
    added = 0
    seen = set()
    for raw in codes:
        code = str(raw or "").upper()[:5]
        if len(code) != 5 or code in seen:
            continue
        seen.add(code)
        verified = db.session.scalar(select(KnowledgeDTC.id).where(
            KnowledgeDTC.code == code, KnowledgeDTC.status == "verified"))
        if verified is not None:
            continue
        existing = db.session.scalar(select(KnowledgeDTC.id).where(
            KnowledgeDTC.code == code,
            KnowledgeDTC.maker == maker_name if maker_name else KnowledgeDTC.maker.is_(None),
            KnowledgeDTC.status == "draft"))
        if existing is not None:
            continue
        db.session.add(KnowledgeDTC(
            code=code, maker=maker_name, description=_UNKNOWN_DTC, source="manual",
            source_detail="스캔에서 설명 없이 발견", status="draft", confidence=0))
        added += 1
    if added:
        db.session.flush()
    return added


def _command_row(maker, model, header, command) -> KnowledgeCommand | None:
    return db.session.scalar(select(KnowledgeCommand).where(
        KnowledgeCommand.maker == maker if maker else KnowledgeCommand.maker.is_(None),
        KnowledgeCommand.model == model if model else KnowledgeCommand.model.is_(None),
        KnowledgeCommand.header == header if header else KnowledgeCommand.header.is_(None),
        KnowledgeCommand.command == command,
        KnowledgeCommand.source == "reverse_analysis",
    ))


def remember_observed_commands(maker: str | None, model: str | None, commands: list[dict]) -> int:
    """역분석 기록의 읽기 명령을 제조사·차종 초안으로 남긴다. 다시 저장하면 응답 예시만 고친다."""
    maker_name = (maker or "").strip() or None
    model_name = (model or "").strip() or None
    added = 0
    seen = set()
    for item in commands or []:
        if not item.get("sendable"):
            continue
        command = re.sub(r"\s+", "", str(item.get("command") or "")).upper()
        if not _READ.fullmatch(command) or _blocked_command(command) or len(command) > 16:
            continue
        header = (str(item.get("header")).strip().upper() if item.get("header") else "") or None
        key = (maker_name, model_name, header, command)
        if key in seen:
            continue
        seen.add(key)
        example = str(item.get("example") or "").strip()
        detail = f"역분석 응답 예시: {example}"[:500] if example else "역분석에서 읽은 명령"
        existing = _command_row(maker_name, model_name, header, command)
        if existing is None:
            db.session.add(KnowledgeCommand(
                maker=maker_name, model=model_name, header=header, command=command,
                label=command, detail_name=command, description=detail, source="reverse_analysis",
                source_detail=detail, status="draft", confidence=0.4))
            added += 1
            continue
        existing.source_detail = detail
    if added:
        db.session.flush()
    return added


def remember_command(*, maker: str | None, model: str | None, header: str | None, command: str,
                     label: str | None, user_id: int | None) -> None:
    """역분석에서 적용한 읽기 명령을 검증된 지식으로 남긴다."""
    command = re.sub(r"\s+", "", command or "").upper()
    if not _READ.fullmatch(command) or command[:2] in _BLOCKED:
        return
    header = (header or "").strip().upper() or None
    existing = _command_row(maker, model, header, command)
    now = utcnow()
    if existing is None:
        db.session.add(KnowledgeCommand(
            maker=maker, model=model, header=header, command=command, label=(label or command)[:200],
            source="reverse_analysis", source_detail="적용된 스캔 로직", confidence=1.0, status="verified",
            verified_by=user_id, verified_at=now))
        return
    existing.status = "verified"
    existing.label = (label or existing.label or command)[:200]
    existing.verified_by = user_id
    existing.verified_at = now


def remember_formula(*, maker: str | None, model: str | None, signal_key: str, layout: dict,
                     formula: str, label: str, user_id: int | None) -> None:
    """적용된 디코딩 규칙을 검증 수식으로 남긴다. 배치는 source_detail에 둔다."""
    formula = (formula or "")[:5000]
    did = str(layout.get("did") or "")
    header = str(layout.get("request_id") or "")
    command = f"22{did}" if did else None
    detail = json.dumps({"signal_key": signal_key, "layout": layout}, ensure_ascii=False)
    existing = db.session.scalar(select(KnowledgeFormula).where(
        KnowledgeFormula.maker == maker if maker else KnowledgeFormula.maker.is_(None),
        KnowledgeFormula.model == model if model else KnowledgeFormula.model.is_(None),
        KnowledgeFormula.command == command,
        KnowledgeFormula.label == label[:200],
        KnowledgeFormula.source == "reverse_analysis",
    ))
    now = utcnow()
    if existing is None:
        db.session.add(KnowledgeFormula(
            maker=maker, model=model, command=command, pid=did[:20] or None,
            label=label[:200], formula=formula, source="reverse_analysis", source_detail=detail,
            confidence=1.0, status="verified", verified_by=user_id, verified_at=now))
        return
    existing.formula = formula
    existing.source_detail = detail
    existing.status = "verified"
    existing.verified_by = user_id
    existing.verified_at = now


def remember_rule(rule, user_id: int | None) -> None:
    """적용 중인 디코딩 규칙 한 건을 지식베이스에 넣는다."""
    from app.modules.canlab.engine import signals

    signal = signals.BY_KEY.get(rule.signal_key)
    layout = {"request_id": rule.request_id, "did": rule.did, "start": rule.start, "width": rule.width,
              "endian": rule.endian, "signed": rule.signed, "scale": rule.scale, "offset": rule.offset}
    remember_formula(maker=rule.maker, model=rule.model, signal_key=rule.signal_key, layout=layout,
                     formula=rule.formula, label=signal.label if signal else rule.signal_key, user_id=user_id)
    remember_command(maker=rule.maker, model=rule.model, header=rule.request_id, command=f"22{rule.did}",
                     label=signal.label if signal else rule.signal_key, user_id=user_id)
