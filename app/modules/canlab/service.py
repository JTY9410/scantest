"""CAN 분석 업무 규칙: 데이터 등록, 정답값, 역산 실행과 규칙 적용, 운영 결과지."""

import hashlib
import io
import re
import time
from datetime import UTC, datetime
from typing import Any

from flask import current_app, url_for
from flask_login import current_user
from sqlalchemy import delete, func, select
from sqlalchemy.orm import undefer
from sqlalchemy.orm.exc import StaleDataError

from app.core import audit
from app.core.errors import ServiceError
from app.extensions import db
from app.modules.accounts.models import User
from app.modules.canlab import ai
from app.modules.canlab.engine import signals, uds
from app.modules.canlab.engine.decode import RuleRef, Trace, decode_signals, diagnose, load_trace
from app.modules.canlab.engine.frames import decode_text, elm_from_exchanges
from app.modules.canlab.engine.search import GroundTruth, Layout, Samples, search
from app.modules.canlab.engine.validate import judge
from app.modules.canlab.models import (
    AnalysisRun, CanDataset, DatasetKind, DatasetSource, DecodeRule, DiagnosticReport,
    GroundTruthValue, LogicStatus, RuleStatus, ScanLogic, TruthSource,
)
from app.modules.obd import devices as obd_devices
from app.modules.obd.service import list_profiles

CONFLICT = "다른 관리자가 먼저 바꿨습니다. 새로고침한 뒤 다시 시도하세요."
TRACE_EXTENSIONS = (".trc", ".txt", ".log")
VALUE_EXTENSIONS = (".txt", ".csv", ".tsv")
MAX_TRUTH_LINES = 200
MAX_PDF_PAGES = 20
MAX_AI_PAGES = 3
MAX_SERIES_POINTS = 120
MAX_COMMANDS = 200
# 스캔 로직에 넣을 수 있는 읽기 서비스. 세션 변경·보안 접근·쓰기·루틴·지우기는 넣지 않는다.
READ_SERVICES = {0x01, 0x02, 0x03, 0x06, 0x07, 0x09, 0x0A, 0x19, 0x21, 0x22}


def _now() -> datetime:
    return datetime.now(UTC)


# ── 데이터 ─────────────────────────────────────────────────────────────

def list_datasets(kind: str | None = None) -> list[CanDataset]:
    query = select(CanDataset).order_by(CanDataset.id.desc())
    if kind:
        query = query.where(CanDataset.kind == kind)
    return list(db.session.scalars(query))


def get_dataset(dataset_id: int, with_content: bool = False) -> CanDataset:
    options = [undefer(CanDataset.content)] if with_content else []
    dataset = db.session.get(CanDataset, dataset_id, options=options)
    if dataset is None:
        raise ServiceError("데이터를 찾을 수 없습니다.", 404)
    return dataset


def _trace_summary(trace: Trace) -> dict:
    times = [t for rows in trace.samples.values() for t, _ in rows]
    diagnosis = diagnose(trace)
    return {
        "format": trace.format,
        "frames": trace.frame_count,
        "skipped_lines": trace.skipped_lines,
        "transactions": len(trace.transactions),
        "duration_s": round((max(times) - min(times)) / 1000, 1) if times else 0,
        "dids": sorted({f"{req:03X} {did:04X}" for req, did in trace.samples}),
        "samples": sum(len(rows) for rows in trace.samples.values()),
        "vin": diagnosis["vin"],
        "ecus": diagnosis["ecus"],
        "dtc_count": sum(len(v) for v in diagnosis["dtcs"].values()),
        "commands": extract_commands(trace),
    }


def _can_header(can_id: int | None) -> str | None:
    if can_id is None:
        return None
    return f"{can_id:03X}" if can_id <= 0x7FF else f"{can_id:08X}"


def extract_commands(trace: Trace) -> list[dict]:
    """기록의 요청(명령)과 응답(산출 결과)을 명령별로 모은다.
    sendable: 스캔 로직에 넣을 수 있는 명령(읽기 서비스, 11비트 주소, 8바이트 이하)."""
    rows: dict[tuple[str, str], dict] = {}
    for tx in trace.transactions:
        header, command = _can_header(tx.request_id), tx.request.hex().upper()
        row = rows.get((header, command))
        if row is None:
            if len(rows) >= MAX_COMMANDS:
                continue
            row = rows[(header, command)] = {
                "header": header, "command": command, "service": f"{tx.service:02X}",
                "did": f"{tx.did:04X}" if tx.did is not None else None, "response_id": None,
                "count": 0, "positive": 0, "negative": None, "example": None,
                "sendable": tx.service in READ_SERVICES and tx.request_id <= 0x7FF and len(tx.request) <= 8,
            }
        row["count"] += 1
        if tx.response is not None and row["response_id"] is None:
            row["response_id"] = _can_header(tx.response_id)
        if tx.positive:
            row["positive"] += 1
            row["example"] = row["example"] or tx.response[:24].hex(" ").upper()
        elif tx.negative_code is not None:
            row["negative"] = f"{tx.negative_code:02X} {uds.NEGATIVE_CODES.get(tx.negative_code, '기타')}"
    return list(rows.values())


def dataset_commands(dataset: CanDataset) -> list[dict]:
    """등록할 때 뽑아 둔 명령. 이전에 등록한 데이터는 지금 다시 뽑는다."""
    if "commands" in (dataset.summary or {}):
        return dataset.summary["commands"]
    return extract_commands(load_trace(decode_text(get_dataset(dataset.id, with_content=True).content)))


def _responded_trace(content: bytes) -> Trace:
    trace = load_trace(decode_text(content))
    if not any(tx.response is not None for tx in trace.transactions):
        raise ServiceError("진단 요청·응답을 찾지 못했습니다. PCAN TRC 또는 위카 ELM 기록인지 확인하세요.")
    return trace


def _pdf_reader(content: bytes):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        return PdfReader(io.BytesIO(content))
    except (PdfReadError, ValueError, OSError) as exc:
        raise ServiceError("PDF를 읽을 수 없습니다. 파일이 손상되었는지 확인하세요.") from exc


def _pdf_summary(content: bytes) -> dict:
    reader = _pdf_reader(content)
    return {"pages": len(reader.pages)}


def upload_dataset(actor: User, *, filename: str, content: bytes, kind: str, vehicle: str,
                   note: str | None = None, source: str = DatasetSource.UPLOAD) -> CanDataset:
    if kind not in {k.value for k in DatasetKind}:
        raise ServiceError("데이터 종류를 확인하세요.")
    if not content:
        raise ServiceError("빈 파일입니다.")
    limit = current_app.config["CANLAB_MAX_UPLOAD_BYTES"]
    if len(content) > limit:
        raise ServiceError(f"파일이 너무 큽니다. {limit // (1024 * 1024)}MB 이하만 올릴 수 있습니다.", 413)
    lower = filename.lower()
    if DatasetKind(kind) is DatasetKind.GSCAN_PDF:
        if not (lower.endswith(".pdf") and content.startswith(b"%PDF")):
            raise ServiceError("결과지는 PDF 파일이어야 합니다.")
        summary = _pdf_summary(content)
    else:
        if not lower.endswith(TRACE_EXTENSIONS):
            raise ServiceError("통신 기록은 .trc, .txt, .log 파일이어야 합니다.")
        summary = _trace_summary(_responded_trace(content))

    digest = hashlib.sha256(content).hexdigest()
    existing = db.session.scalar(select(CanDataset.id).where(CanDataset.sha256 == digest))
    if existing:
        raise ServiceError(f"이미 등록된 파일입니다(데이터 #{existing}).", 409, dataset_id=existing)

    dataset = CanDataset(kind=kind, source=source, vehicle=vehicle.strip()[:100], filename=filename[:255],
                         sha256=digest, size=len(content), content=content, summary=summary,
                         note=(note or "").strip()[:500] or None, uploaded_by=actor.id)
    db.session.add(dataset)
    db.session.flush()
    audit.record("CAN 데이터 등록", "CanDataset", dataset.id, user_id=actor.id,
                 changes={"kind": kind, "filename": dataset.filename, "size": dataset.size, "source": source})
    db.session.commit()
    return dataset


def delete_dataset(actor: User, dataset: CanDataset) -> None:
    audit.record("CAN 데이터 삭제", "CanDataset", dataset.id, user_id=actor.id,
                 changes={"filename": dataset.filename, "kind": dataset.kind})
    db.session.delete(dataset)
    db.session.commit()


# ── 결과지 PDF 페이지와 정답값 ───────────────────────────────────────────

def page_image(dataset: CanDataset, page: int) -> tuple[str, bytes]:
    """페이지에서 가장 큰 그림을 JPEG로 돌려준다. 그림이 없는 페이지는 404."""
    if dataset.kind != DatasetKind.GSCAN_PDF:
        raise ServiceError("PDF 결과지가 아닙니다.", 404)
    reader = _pdf_reader(get_dataset(dataset.id, with_content=True).content)
    if not 1 <= page <= len(reader.pages):
        raise ServiceError("페이지를 찾을 수 없습니다.", 404)
    image = _largest_image(reader.pages[page - 1])
    if image is None:
        raise ServiceError("이 페이지에는 그림이 없습니다.", 404)
    return image


def _largest_image(page) -> tuple[str, bytes] | None:
    images = list(page.images)
    if not images:
        return None
    largest = max(images, key=lambda img: img.image.width * img.image.height)
    buffer = io.BytesIO()
    largest.image.convert("RGB").save(buffer, "JPEG", quality=88)
    return "image/jpeg", buffer.getvalue()


def page_text(dataset: CanDataset, page: int) -> str:
    reader = _pdf_reader(get_dataset(dataset.id, with_content=True).content)
    if not 1 <= page <= len(reader.pages):
        raise ServiceError("페이지를 찾을 수 없습니다.", 404)
    return (reader.pages[page - 1].extract_text() or "").strip()


def _truth(dataset: CanDataset, label: str, value: str, unit: str, page: int | None,
           source: str, confirmed: bool) -> GroundTruthValue | None:
    value = value.strip().replace(",", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", value):
        return None
    return GroundTruthValue(dataset_id=dataset.id, label=label.strip()[:200], value_text=value[:50],
                            unit=(unit or "").strip()[:20] or None, page=page, source=source,
                            confirmed=confirmed, signal_key=signals.match_label(label))


def ocr_page(actor: User, dataset: CanDataset, page: int) -> int:
    """AI로 한 페이지를 판독해 미확인 정답값으로 넣는다. 같은 페이지의 미확인 AI 값은 바꾼다."""
    try:
        image = page_image(dataset, page)
    except ServiceError as error:
        if error.status != 404 or not (text := page_text(dataset, page)):
            raise
        rows, provider = ai.read_table(page_text=text)
    else:
        rows, provider = ai.read_table(image=image)
    for old in [t for t in dataset.truths if t.page == page and t.source == TruthSource.AI_OCR
                and not t.confirmed]:
        db.session.delete(old)
    added = [t for r in rows if (t := _truth(dataset, r["label"], r["value"], r["unit"], page,
                                             TruthSource.AI_OCR, False))]
    db.session.add_all(added)
    audit.record("결과지 AI 판독", "CanDataset", dataset.id, user_id=actor.id,
                 changes={"page": page, "rows": len(added), "provider": provider})
    db.session.commit()
    return len(added)


TRUTH_LINE = re.compile(r"^(?P<label>.+?)\s+(?P<value>-?[\d,]+(?:\.\d+)?)\s*(?P<unit>[^\d\s]*)\s*$")


def parse_truth_lines(text: str) -> list[tuple[str, str, str]]:
    """'항목명<탭 또는 |>값<탭 또는 |>단위' 또는 '항목명 값 단위' 줄을 읽는다."""
    rows = []
    for line in (text or "").splitlines()[:MAX_TRUTH_LINES]:
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in re.split(r"\t|\|", line)]
        if len(parts) >= 2 and parts[0]:
            rows.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
        elif match := TRUTH_LINE.match(line):
            rows.append((match["label"], match["value"], match["unit"]))
    return rows


def add_truths(actor: User, dataset: CanDataset, text: str) -> int:
    added = [t for label, value, unit in parse_truth_lines(text)
             if (t := _truth(dataset, label, value, unit, None, TruthSource.MANUAL, True))]
    if not added:
        raise ServiceError("읽을 수 있는 줄이 없습니다. '항목명 | 값 | 단위' 형식으로 입력하세요.")
    db.session.add_all(added)
    audit.record("정답값 직접 입력", "CanDataset", dataset.id, user_id=actor.id, changes={"rows": len(added)})
    db.session.commit()
    return len(added)


def values_file_text(filename: str, content: bytes) -> str:
    """최종값 파일(.txt/.tsv는 '항목 | 값 | 단위' 줄, .csv는 항목,값,단위 열)을 입력 줄로 바꾼다."""
    if not filename.lower().endswith(VALUE_EXTENSIONS):
        raise ServiceError("최종값 파일은 .pdf, .txt, .csv, .tsv 파일이어야 합니다.")
    if len(content) > current_app.config["CANLAB_MAX_UPLOAD_BYTES"]:
        raise ServiceError("최종값 파일이 너무 큽니다.", 413)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp949", errors="replace")
    if filename.lower().endswith(".csv"):
        import csv

        return "\n".join(" | ".join(cell.strip() for cell in row[:3])
                         for row in csv.reader(io.StringIO(text)) if row)
    return text


def _numeric(value: str) -> bool:
    return re.fullmatch(r"-?\d+(\.\d+)?", value.strip().replace(",", "")) is not None


def pdf_values(filename: str, content: bytes) -> list[tuple[str, str, str, int, str]]:
    """결과지 PDF의 (항목, 값, 단위, 쪽, 출처). PDF 글자를 먼저 읽고, 글자로 읽은 값이 없으면
    (그림으로 된 PDF) 앞쪽 페이지를 AI로 판독한다."""
    if not (filename.lower().endswith(".pdf") and content.startswith(b"%PDF")):
        raise ServiceError("최종값 PDF 파일이 올바르지 않습니다.")
    if len(content) > current_app.config["CANLAB_MAX_UPLOAD_BYTES"]:
        raise ServiceError("최종값 파일이 너무 큽니다.", 413)
    pages = list(_pdf_reader(content).pages)[:MAX_PDF_PAGES]
    rows = [(label, value, unit, number, TruthSource.PDF_TEXT)
            for number, page in enumerate(pages, 1)
            for label, value, unit in parse_truth_lines(page.extract_text() or "") if _numeric(value)]
    if rows:
        return rows[:MAX_TRUTH_LINES]
    problem = None
    for number, page in enumerate(pages[:MAX_AI_PAGES], 1):
        if (image := _largest_image(page)) is None:
            continue
        try:
            found, _ = ai.read_table(image=image)
        except ServiceError as error:
            if error.status not in (502, 504):
                raise ServiceError(f"PDF에 글자가 없어 AI 판독이 필요합니다. {error.message}") from error
            problem = error.message
            continue
        rows += [(r["label"], r["value"], r["unit"], number, TruthSource.AI_OCR) for r in found if _numeric(r["value"])]
    if not rows:
        reason = f" {problem}" if problem else ""
        raise ServiceError(f"PDF에서 최종값을 읽지 못했습니다.{reason} 값을 붙여 넣으세요.")
    return rows[:MAX_TRUTH_LINES]


def upload_wescan(actor: User, *, filename: str, content: bytes, vehicle: str, values_text: str,
                  values_pdf: tuple[str, bytes] | None = None, note: str | None = None) -> CanDataset:
    """위스캔 스캔 데이터: 통신 기록(명령·응답)과 위스캔이 화면에 보여 준 최종값을 함께 등록한다.
    붙여 넣은 값은 확인된 값, 결과지 PDF에서 읽은 값은 데이터 화면에서 확인할 미확인 값이 된다."""
    typed = [row for row in parse_truth_lines(values_text) if _numeric(row[1])]
    from_pdf = pdf_values(*values_pdf) if values_pdf else []
    if not typed and not from_pdf:
        raise ServiceError("위스캔 최종값을 '항목명 | 값 | 단위' 형식으로 올리거나 붙여 넣으세요(숫자 값 1개 이상).")
    dataset = upload_dataset(actor, filename=filename, content=content, kind=DatasetKind.WECAN_TRC,
                             vehicle=vehicle, note=note)
    truths = [_truth(dataset, label, value, unit, None, TruthSource.MANUAL, True) for label, value, unit in typed]
    truths += [_truth(dataset, label, value, unit, page, source, False)
               for label, value, unit, page, source in from_pdf]
    db.session.add_all(truths)
    audit.record("위스캔 최종값 등록", "CanDataset", dataset.id, user_id=actor.id,
                 changes={"typed": len(typed), "pdf": len(from_pdf),
                          "ai": sum(1 for row in from_pdf if row[4] == TruthSource.AI_OCR)})
    db.session.commit()
    return dataset


def update_truths(actor: User, dataset: CanDataset, rows: dict[int, dict[str, Any]]) -> None:
    """rows: 정답값 id → {value, signal_key, confirmed, delete}"""
    changes = {}
    for truth in list(dataset.truths):
        row = rows.get(truth.id)
        if row is None:
            continue
        if row.get("delete"):
            changes[truth.id] = "삭제"
            db.session.delete(truth)
            continue
        value = str(row.get("value", truth.value_text)).strip().replace(",", "")
        if not re.fullmatch(r"-?\d+(\.\d+)?", value):
            raise ServiceError(f"'{truth.label}' 값은 숫자로 입력하세요.")
        key = row.get("signal_key") or None
        if key and key not in signals.BY_KEY:
            raise ServiceError("알 수 없는 신호입니다.")
        confirmed = bool(row.get("confirmed"))
        if (value, key, confirmed) != (truth.value_text, truth.signal_key, truth.confirmed):
            changes[truth.id] = {"value": value, "signal_key": key, "confirmed": confirmed}
            truth.value_text, truth.signal_key, truth.confirmed = value, key, confirmed
    if changes:
        audit.record("정답값 수정", "CanDataset", dataset.id, user_id=actor.id, changes=changes)
        db.session.commit()


def wescan_datasets() -> list[CanDataset]:
    """신호가 지정된 확인 최종값이 하나 이상 있는 위스캔 데이터."""
    ids = select(GroundTruthValue.dataset_id).where(GroundTruthValue.confirmed.is_(True),
                                                    GroundTruthValue.signal_key.is_not(None)).distinct()
    return list(db.session.scalars(select(CanDataset).where(CanDataset.id.in_(ids),
                                                            CanDataset.kind == DatasetKind.WECAN_TRC)
                                   .order_by(CanDataset.id.desc())))


def ground_truths(dataset: CanDataset) -> list[GroundTruth]:
    truths, seen = [], set()
    for row in dataset.truths:
        if not (row.confirmed and row.signal_key and row.numeric is not None) or row.signal_key in seen:
            continue
        seen.add(row.signal_key)
        truths.append(GroundTruth(row.signal_key, row.numeric, signals.decimals_of(row.value_text)))
    return truths


# ── 역산 실행과 규칙 ─────────────────────────────────────────────────────

def trace_datasets() -> list[CanDataset]:
    kinds = [k.value for k in DatasetKind if k.is_trace]
    return list(db.session.scalars(select(CanDataset).where(CanDataset.kind.in_(kinds))
                                   .order_by(CanDataset.id.desc())))


def merged_samples(dataset_ids: list[int]) -> Samples:
    samples: Samples = {}
    for dataset_id in dataset_ids:
        dataset = get_dataset(dataset_id, with_content=True)
        if not dataset.is_trace:
            raise ServiceError(f"'{dataset.filename}'은 통신 기록이 아닙니다.")
        for key, rows in load_trace(decode_text(dataset.content)).samples.items():
            samples.setdefault(key, []).extend(rows)
    return samples


def _layout(rule: DecodeRule) -> Layout:
    return Layout(int(rule.request_id, 16), int(rule.did, 16), rule.start, rule.width, rule.endian,
                  rule.signed, rule.scale, rule.offset)


def _rule_fields(layout: Layout) -> dict:
    return {"request_id": f"{layout.request_id:03X}", "did": f"{layout.did:04X}", "start": layout.start,
            "width": layout.width, "endian": layout.endian, "signed": layout.signed,
            "scale": layout.scale, "offset": layout.offset, "formula": layout.formula()}


def active_rule(signal_key: str) -> DecodeRule | None:
    return db.session.scalar(select(DecodeRule).where(DecodeRule.signal_key == signal_key,
                                                      DecodeRule.status == RuleStatus.ACTIVE))


def _next_revision(signal_key: str) -> int:
    current = db.session.scalar(select(func.max(DecodeRule.revision)).where(DecodeRule.signal_key == signal_key))
    return (current or 0) + 1


def _activate_layout(signal_key: str, layout: Layout, evidence: dict, confidence: float,
                     run_id: int | None, actor: User) -> tuple[DecodeRule, bool]:
    """수식을 적용한다. 같은 수식의 규칙이 있으면 그 버전을, 없으면 새 버전을 쓴다.
    기존 적용 규칙은 '이전 버전'이 된다. (규칙, 새로 적용했는지)를 돌려준다."""
    rules = db.session.scalars(select(DecodeRule).where(DecodeRule.signal_key == signal_key)).all()
    same = next((r for r in rules if _layout(r) == layout), None)
    current = next((r for r in rules if r.status == RuleStatus.ACTIVE), None)
    if same is not None and same is current:
        current.evidence, current.confidence = evidence, confidence
        return current, False
    if current is not None:
        current.status, current.retired_at = RuleStatus.RETIRED, _now()
        db.session.flush()
    if same is None:
        same = DecodeRule(signal_key=signal_key, revision=_next_revision(signal_key), analysis_run_id=run_id,
                          created_by=actor.id, **_rule_fields(layout))
        db.session.add(same)
    same.status, same.activated_at, same.retired_at = RuleStatus.ACTIVE, _now(), None
    same.evidence, same.confidence = evidence, confidence
    db.session.flush()
    return same, True


def _overlaps(a: Layout, b: Layout) -> bool:
    return (a.request_id, a.did) == (b.request_id, b.did) and a.start < b.start + b.width and b.start < a.start + a.width


def _guard(signal_key: str, layout: Layout, active: dict[str, DecodeRule]) -> list[str]:
    """확정을 막는 이유: 다른 신호에 적용 중인 바이트와 겹치는 수식."""
    for key, rule in active.items():
        if key != signal_key and _overlaps(layout, _layout(rule)):
            label = signals.BY_KEY[key].label if key in signals.BY_KEY else key
            return [f"'{label}'에 적용 중인 바이트와 겹칩니다."]
    return []


def compare_commands(wescan: CanDataset, reverse: list[CanDataset]) -> dict[str, list[dict]]:
    """위스캔 기록과 리버스 기록의 명령(요청)을 공통 / 위스캔에만 / 리버스에만으로 나눈다."""
    ours = {(c["header"], c["command"]): c for c in dataset_commands(wescan)}
    theirs: dict[tuple[str, str], dict] = {}
    for dataset in reverse:
        for c in dataset_commands(dataset):
            row = theirs.setdefault((c["header"], c["command"]), dict(c, count=0))
            row["count"] += c["count"]
            row["example"] = row["example"] or c["example"]

    def merged(key: tuple[str, str]) -> dict:
        w, r = ours.get(key), theirs.get(key)
        base = w or r
        return {"header": base["header"], "command": base["command"], "service": base["service"],
                "did": base["did"], "sendable": base["sendable"],
                "wescan_count": w["count"] if w else 0, "reverse_count": r["count"] if r else 0,
                "wescan_example": w["example"] if w else None, "reverse_example": r["example"] if r else None}

    return {
        "common": [merged(k) for k in ours if k in theirs],
        "wescan_only": [merged(k) for k in ours if k not in theirs],
        "reverse_only": [merged(k) for k in theirs if k not in ours],
    }


def decoder_code(signal_key: str, layout: Layout) -> str:
    """수식을 그대로 옮긴 Python 디코더. 화면에서 보여 주기만 하고 서버에서 실행하지 않는다."""
    end = layout.start + layout.width
    return (
        f"# 요청: ATSH{layout.request_id:03X} → 22 {layout.did:04X}, 응답 62 {layout.did:04X} 뒤의 데이터(payload)\n"
        f"def decode_{re.sub(r'[^0-9a-zA-Z_]', '_', signal_key)}(payload: bytes) -> float | None:\n"
        f'    """{layout.formula()}"""\n'
        f"    if len(payload) < {end}:\n"
        f"        return None\n"
        f"    raw = int.from_bytes(payload[{layout.start}:{end}], \"{layout.endian}\", signed={layout.signed})\n"
        f"    return round(raw * {layout.scale!r} + {layout.offset!r}, 6)\n"
    )


def run_analysis(actor: User, wescan_id: int, reverse_ids: list[int]) -> AnalysisRun:
    """위스캔 최종값을 정답으로 삼아 위스캔·리버스 기록의 응답에서 수식을 찾고 명령을 비교한다.
    규칙은 바꾸지 않는다. 적용은 결과 화면의 '적용'(변경 전후 비교 → 확정)으로 한다."""
    if not reverse_ids:
        raise ServiceError("비교할 리버스 데이터를 하나 이상 고르세요.")
    wescan = get_dataset(wescan_id)
    if wescan.kind != DatasetKind.WECAN_TRC:
        raise ServiceError("위스캔 데이터를 고르세요.")
    reverse = [get_dataset(i) for i in reverse_ids if i != wescan.id]
    if not reverse:
        raise ServiceError("비교할 리버스 데이터를 하나 이상 고르세요.")
    truths = ground_truths(wescan)
    if not truths:
        raise ServiceError("위스캔 최종값 중 신호가 지정된 확인 값이 없습니다. 데이터 화면에서 신호를 고르세요.")
    started = time.perf_counter()
    trace_ids = [wescan.id, *[d.id for d in reverse]]
    samples = merged_samples(trace_ids)
    if not samples:
        raise ServiceError("고른 기록에 데이터 조회(0x22) 응답이 없습니다.")
    ranked = search(samples, truths)
    decisions = judge(truths, ranked, samples)

    run = AnalysisRun(trace_dataset_ids=trace_ids, reverse_dataset_ids=[d.id for d in reverse],
                      truth_dataset_id=wescan.id, commands=compare_commands(wescan, reverse),
                      created_by=actor.id, created_at=_now(), result={})
    db.session.add(run)
    db.session.flush()

    active = {r.signal_key: r for r in db.session.scalars(
        select(DecodeRule).where(DecodeRule.status == RuleStatus.ACTIVE))}
    result = {}
    for truth in truths:
        decision = decisions[truth.signal_key]
        if decision.activate and (blocked := _guard(truth.signal_key, decision.candidate.layout, active)):
            decision.activate, decision.reasons = False, blocked
        signal = signals.BY_KEY[truth.signal_key]
        entry = {
            "label": signal.label, "unit": signal.unit, "truth": truth.value, "activate": decision.activate,
            "reasons": list(decision.reasons), "status": "UNKNOWN",
            "candidates": [
                {"formula": c.layout.formula(), "source": f"{c.layout.request_id:03X} 22 {c.layout.did:04X}",
                 "decoded": c.decoded, "error": round(c.error, 6), "score": round(c.score, 3),
                 "support": round(c.support, 3), "references": c.references, "rivals": c.rivals,
                 "conflict": c.conflict}
                for c in ranked.get(truth.signal_key, [])[:5]
            ],
        }
        if decision.candidate is not None:
            best = decision.candidate
            current = active.get(truth.signal_key)
            entry.update(status="확정" if decision.activate else "가설", decoded=best.decoded,
                         formula=best.layout.formula(), layout=best.layout.to_dict(),
                         score=round(best.score, 3),
                         evidence=best.evidence(truth) | {"reasons": decision.reasons, "analysis_run_id": run.id},
                         code=decoder_code(truth.signal_key, best.layout),
                         matches_active=current is not None and _layout(current) == best.layout)
            if current is not None and not entry["matches_active"]:
                entry["reasons"].append(f"적용 중 수식(v{current.revision}: {current.formula})과 다릅니다. "
                                        "적용 화면에서 변경 전후를 비교하세요.")
        result[truth.signal_key] = entry

    run.result = result
    run.duration_ms = int((time.perf_counter() - started) * 1000)
    audit.record("CAN 역산 실행", "AnalysisRun", run.id, user_id=actor.id,
                 changes={"wescan": wescan.id, "reverse": run.reverse_dataset_ids, "signals": len(truths),
                          "commands": {k: len(v) for k, v in run.commands.items()}})
    db.session.commit()
    return run


def list_runs() -> list[AnalysisRun]:
    return list(db.session.scalars(select(AnalysisRun).order_by(AnalysisRun.id.desc()).limit(50)))


def get_run(run_id: int) -> AnalysisRun:
    run = db.session.get(AnalysisRun, run_id)
    if run is None:
        raise ServiceError("분석 기록을 찾을 수 없습니다.", 404)
    return run


def list_rules() -> dict[str, list[DecodeRule]]:
    """신호별 규칙. 신호 목록 순서, 각 신호 안에서는 최신 버전이 먼저."""
    grouped: dict[str, list[DecodeRule]] = {}
    for rule in db.session.scalars(select(DecodeRule).order_by(DecodeRule.revision.desc())):
        grouped.setdefault(rule.signal_key, []).append(rule)
    order = [s.key for s in signals.SIGNALS]
    return {k: grouped[k] for k in sorted(grouped, key=lambda k: order.index(k) if k in order else len(order))}


def get_rule(rule_id: int) -> DecodeRule:
    rule = db.session.get(DecodeRule, rule_id)
    if rule is None:
        raise ServiceError("규칙을 찾을 수 없습니다.", 404)
    return rule


def activate_rule(actor: User, rule: DecodeRule, version: int) -> DecodeRule:
    """보류·이전 버전 규칙을 적용한다(되돌리기 포함)."""
    if rule.version != version:
        raise ServiceError(CONFLICT, 409)
    if rule.status == RuleStatus.ACTIVE:
        return rule
    current = active_rule(rule.signal_key)
    if current is not None:
        current.status, current.retired_at = RuleStatus.RETIRED, _now()
    try:
        db.session.flush()
        rule.status, rule.activated_at, rule.retired_at = RuleStatus.ACTIVE, _now(), None
        audit.record("디코딩 규칙 적용", "DecodeRule", rule.id, user_id=actor.id,
                     changes={"signal": rule.signal_key, "revision": rule.revision,
                              "replaced": current.revision if current else None})
        db.session.commit()
    except StaleDataError as exc:
        db.session.rollback()
        raise ServiceError(CONFLICT, 409) from exc
    return rule


def retire_rule(actor: User, rule: DecodeRule, version: int) -> DecodeRule:
    if rule.version != version:
        raise ServiceError(CONFLICT, 409)
    if rule.status != RuleStatus.ACTIVE:
        return rule
    rule.status, rule.retired_at = RuleStatus.RETIRED, _now()
    audit.record("디코딩 규칙 해제", "DecodeRule", rule.id, user_id=actor.id,
                 changes={"signal": rule.signal_key, "revision": rule.revision})
    try:
        db.session.commit()
    except StaleDataError as exc:
        db.session.rollback()
        raise ServiceError(CONFLICT, 409) from exc
    return rule


def active_rule_refs() -> list[RuleRef]:
    rules = db.session.scalars(select(DecodeRule).where(DecodeRule.status == RuleStatus.ACTIVE)).all()
    return [RuleRef(r.id, r.revision, r.signal_key, _layout(r), r.confidence) for r in rules]


# ── 스캔 로직(스캔하기에 쓰는 명령·수식 묶음) ─────────────────────────────

CHOICES = {"before": "변경 전 유지", "after": "변경 후 적용", "exclude": "빼기"}


def active_logic() -> ScanLogic | None:
    return db.session.scalar(select(ScanLogic).where(ScanLogic.status == LogicStatus.ACTIVE))


def list_logics() -> list[ScanLogic]:
    return list(db.session.scalars(select(ScanLogic).order_by(ScanLogic.revision.desc()).limit(50)))


def get_logic(logic_id: int) -> ScanLogic:
    logic = db.session.get(ScanLogic, logic_id)
    if logic is None:
        raise ServiceError("스캔 로직을 찾을 수 없습니다.", 404)
    return logic


def logic_commands() -> list[dict]:
    logic = active_logic()
    return list(logic.commands) if logic else []


def _rule_side(rule: DecodeRule) -> dict:
    return {"rule_id": rule.id, "revision": rule.revision, "formula": rule.formula,
            "source": f"{rule.request_id} 22 {rule.did}", "layout": _layout(rule).to_dict()}


def item_options(item: dict) -> list[str]:
    if item["change"] == "same":
        return ["before", "exclude"]
    return [c for c in ("before", "after") if item[c]] + ["exclude"]


def draft_logic(actor: User, run: AnalysisRun) -> ScanLogic:
    """분석 결과로 적용 전(draft) 로직을 만든다. 현재 적용 중인 명령·수식(변경 전)과 분석 결과(변경 후)를
    항목별로 비교하고 기본안(확정 수식은 변경 후, 가설·UNKNOWN은 변경 전 유지)을 정한다."""
    before_cmds = {(c["header"], c["command"]): c for c in logic_commands()}
    after_cmds: dict[tuple[str, str], dict] = {}
    for c in run.commands.get("common", []) + run.commands.get("wescan_only", []):
        if c["sendable"]:
            label = f"위스캔 명령 {c['header']} {c['command']}"
            after_cmds[(c["header"], c["command"])] = {"header": c["header"], "command": c["command"], "label": label}
    for key, entry in run.result.items():
        if entry.get("layout"):
            header, command = entry["layout"]["request_id"], f"22{entry['layout']['did']}"
            after_cmds.setdefault((header, command), {"header": header, "command": command,
                                                      "label": f"{entry['label']} 조회 {header} {command}"})

    items = []
    for key in list(before_cmds) + [k for k in after_cmds if k not in before_cmds]:
        before, after = before_cmds.get(key), after_cmds.get(key)
        change = "same" if before and after else ("added" if after else "removed")
        items.append({"key": f"cmd:{key[0]}:{key[1]}", "kind": "command", "label": f"{key[0]} {key[1]}",
                      "before": before, "after": after, "change": change,
                      "default": "after" if change == "added" else "before"})

    active = {r.signal_key: r for r in db.session.scalars(
        select(DecodeRule).where(DecodeRule.status == RuleStatus.ACTIVE))}
    order = [s.key for s in signals.SIGNALS]
    keys = sorted(set(active) | {k for k, e in run.result.items() if e.get("layout")},
                  key=lambda k: order.index(k) if k in order else len(order))
    for key in keys:
        rule, entry = active.get(key), run.result.get(key) or {}
        before = _rule_side(rule) if rule else None
        after = ({"formula": entry["formula"], "layout": entry["layout"], "status": entry["status"],
                  "decoded": entry["decoded"], "truth": entry["truth"], "score": entry["score"],
                  "evidence": entry["evidence"]} if entry.get("layout") else None)
        if before and after and before["layout"] == after["layout"]:
            change, default = "same", "before"
        elif after:
            change = "changed" if before else "added"
            default = "after" if after["status"] == "확정" else ("before" if before else "exclude")
        else:
            change, default = "removed", "before"
        signal = signals.BY_KEY.get(key)
        items.append({"key": f"sig:{key}", "kind": "signal", "signal_key": key,
                      "label": signal.label if signal else key, "unit": signal.unit if signal else "",
                      "before": before, "after": after, "change": change, "default": default})

    revision = (db.session.scalar(select(func.max(ScanLogic.revision))) or 0) + 1
    current = active_logic()
    logic = ScanLogic(revision=revision, status=LogicStatus.DRAFT, commands=[], rules=[], analysis_run_id=run.id,
                      created_by=actor.id,
                      diff={"items": items, "run_id": run.id, "base_revision": current.revision if current else None})
    db.session.add(logic)
    db.session.flush()
    audit.record("스캔 로직 초안", "ScanLogic", logic.id, user_id=actor.id,
                 changes={"revision": revision, "run": run.id, "items": len(items)})
    db.session.commit()
    return logic


def recommended(logic: ScanLogic) -> dict[str, dict]:
    """항목별 추천(AI 최적안이 있으면 그것, 없으면 기본안)."""
    advice = (logic.ai_advice or {}).get("items", {})
    out = {}
    for item in logic.diff["items"]:
        given = advice.get(item["key"]) or {}
        if given.get("choice") in item_options(item):
            out[item["key"]] = {"choice": given["choice"], "reason": given.get("reason") or ""}
        else:
            out[item["key"]] = {"choice": item["default"], "reason": "기본안"}
    return out


def advise_logic(actor: User, logic: ScanLogic) -> tuple[ScanLogic, str | None]:
    """AI에게 변경 전후를 보내 항목별 최적안을 받는다. AI를 쓸 수 없으면 기본안을 저장하고 이유를 돌려준다."""
    if logic.status != LogicStatus.DRAFT:
        raise ServiceError("적용 전 로직만 최적안을 받을 수 있습니다.", 409)
    facts = [{"key": i["key"], "kind": i["kind"], "label": i["label"], "change": i["change"],
              "options": item_options(i), "default": i["default"],
              "before": {k: v for k, v in (i["before"] or {}).items() if k not in ("layout", "evidence")} or None,
              "after": {k: v for k, v in (i["after"] or {}).items() if k not in ("layout", "evidence")} or None}
             for i in logic.diff["items"]]
    problem = None
    try:
        items, summary, provider = ai.advise_logic(facts)
        valid = {i["key"]: item_options(i) for i in logic.diff["items"]}
        advice = {"provider": provider, "summary": summary,
                  "items": {k: v for k, v in items.items() if v.get("choice") in valid.get(k, [])}}
    except ServiceError as error:
        problem = error.message
        advice = {"provider": None, "summary": f"AI를 쓸 수 없어 규칙 기반 기본안을 보여 줍니다. ({error.message})",
                  "items": {i["key"]: {"choice": i["default"], "reason": "기본안"} for i in logic.diff["items"]}}
    logic.ai_advice = advice
    audit.record("스캔 로직 AI 최적안", "ScanLogic", logic.id, user_id=actor.id,
                 changes={"provider": advice["provider"], "items": len(advice["items"])})
    db.session.commit()
    return logic, problem


def _switch_active_logic(logic: ScanLogic) -> ScanLogic | None:
    previous = active_logic()
    if previous is not None and previous is not logic:
        previous.status, previous.retired_at = LogicStatus.RETIRED, _now()
        db.session.flush()
    logic.status, logic.activated_at, logic.retired_at = LogicStatus.ACTIVE, _now(), None
    return previous


def confirm_logic(actor: User, logic: ScanLogic, version: int, choices: dict[str, str]) -> ScanLogic:
    """관리자가 고른 항목으로 로직을 적용한다. 고른 수식은 규칙으로 적용하고 이전 로직은 '이전 버전'이 된다."""
    if logic.version != version:
        raise ServiceError(CONFLICT, 409)
    if logic.status != LogicStatus.DRAFT:
        raise ServiceError("이미 처리한 로직입니다. 디코딩 규칙 화면에서 버전을 확인하세요.", 409)
    commands, rules, chosen, activated = [], [], {}, 0
    try:
        for item in logic.diff["items"]:
            choice = choices.get(item["key"])
            if choice not in item_options(item):
                choice = item["default"]
            chosen[item["key"]] = choice
            if item["kind"] == "command":
                if choice != "exclude":
                    commands.append(item[choice] or item["before"] or item["after"])
                continue
            key, current = item["signal_key"], active_rule(item["signal_key"])
            if choice == "after":
                after = item["after"]
                rule, changed = _activate_layout(key, Layout.from_dict(after["layout"]), after["evidence"],
                                                 after["score"], logic.analysis_run_id, actor)
                activated += changed
            elif choice == "before" and current is not None:
                rule = current
            else:
                rule = None
                if current is not None:
                    current.status, current.retired_at = RuleStatus.RETIRED, _now()
            if rule is not None:
                rules.append({"signal_key": key, "rule_id": rule.id, "revision": rule.revision,
                              "formula": rule.formula})
        previous = _switch_active_logic(logic)
        logic.commands, logic.rules = commands, rules
        logic.diff = dict(logic.diff, chosen=chosen)
        if logic.analysis_run_id and (run := db.session.get(AnalysisRun, logic.analysis_run_id)):
            run.activated_count = (run.activated_count or 0) + activated
        audit.record("스캔 로직 적용", "ScanLogic", logic.id, user_id=actor.id,
                     changes={"revision": logic.revision, "commands": len(commands), "rules": len(rules),
                              "activated": activated, "replaced": previous.revision if previous else None})
        db.session.commit()
    except StaleDataError as exc:
        db.session.rollback()
        raise ServiceError(CONFLICT, 409) from exc
    return logic


def restore_logic(actor: User, logic: ScanLogic, version: int) -> ScanLogic:
    """이전 버전 로직을 다시 적용한다. 그 버전의 수식(규칙 버전)도 함께 되돌린다."""
    if logic.version != version:
        raise ServiceError(CONFLICT, 409)
    if logic.status != LogicStatus.RETIRED:
        raise ServiceError("이전 버전 로직만 되돌릴 수 있습니다.", 409)
    try:
        wanted = {r["signal_key"]: r["rule_id"] for r in logic.rules}
        for rule in db.session.scalars(select(DecodeRule).where(DecodeRule.status == RuleStatus.ACTIVE)):
            if wanted.get(rule.signal_key) != rule.id:
                rule.status, rule.retired_at = RuleStatus.RETIRED, _now()
        db.session.flush()
        for rule_id in wanted.values():
            rule = db.session.get(DecodeRule, rule_id)
            if rule is not None and rule.status != RuleStatus.ACTIVE:
                rule.status, rule.activated_at, rule.retired_at = RuleStatus.ACTIVE, _now(), None
        previous = _switch_active_logic(logic)
        audit.record("스캔 로직 되돌리기", "ScanLogic", logic.id, user_id=actor.id,
                     changes={"revision": logic.revision, "replaced": previous.revision if previous else None})
        db.session.commit()
    except StaleDataError as exc:
        db.session.rollback()
        raise ServiceError(CONFLICT, 409) from exc
    return logic


def capture_requests() -> list[dict]:
    """실시간 수집·스캔에서 보낼 요청. 적용 중 스캔 로직의 명령, 그다음 적용 규칙이 쓰는 ECU·DID와
    고장코드·VIN 조회."""
    requests = [{"header": c["header"], "command": c["command"]} for c in logic_commands()]
    pairs = sorted({(r.layout.request_id, r.layout.did) for r in active_rule_refs()})
    rule_requests = [{"header": f"{req:03X}", "command": f"22{did:04X}"} for req, did in pairs]
    for header in sorted({f"{req:03X}" for req, _ in pairs}):
        rule_requests.append({"header": header, "command": "1902FF"})
    if rule_requests:
        rule_requests.append({"header": rule_requests[0]["header"], "command": "22F190"})
    requests += [r for r in rule_requests if r not in requests]
    return requests


def obd_config() -> dict:
    """웹 블루투스 연결·수집 화면 설정. 프로필이 없어도 알려진 진단기는 자동 감지로 연결한다.
    devices는 현재 사용자가 웹·앱에서 연결했던 진단기로, 이 브라우저에 기억이 없을 때 설정을 미리 채운다."""
    # api 패키지는 이 모듈을 가져오므로 순환 import를 피해 여기서 가져온다.
    from app.modules.api.casing import camelize
    from app.modules.api.serializers import obd_device_dict

    profiles = [p for p in list_profiles() if p.enabled and p.transport == "ble"]
    requests, from_rules = capture_requests(), True
    if not requests:
        # 적용 규칙이 없을 때는 프로필의 조회 명령으로 기초데이터를 모은다.
        requests, from_rules = [{"header": p.request_header, "command": c} for p in profiles[:1]
                                if p.request_header for c in p.read_commands], False
    return {
        "profiles": [{"id": p.id, "name": p.name, "namePrefix": p.device_name_prefix, "service": p.service_uuid,
                      "write": p.write_uuid, "notify": p.notify_uuid, "init": p.init_commands,
                      "timeout": p.response_timeout_ms, "dialect": p.dialect, "canBitrate": p.can_bitrate}
                     for p in profiles],
        "requests": requests,
        "fromRules": from_rules,
        "saveUrl": url_for("canlab.live"),
        "previewUrl": url_for("canlab.live_preview"),
        "devices": camelize([obd_device_dict(d) for d in obd_devices.list_for(current_user)]),
        "devicesUrl": url_for("obd.my_device_save"),
    }


HEX = re.compile(r"(?:[0-9A-Fa-f]{2})+")
HEADER = re.compile(r"[0-9A-Fa-f]{3}|[0-9A-Fa-f]{8}")
MAX_EXCHANGES = 2000


def store_app_capture(actor: User, vehicle: str, exchanges: list, device_name: str | None) -> DiagnosticReport:
    """모바일 앱 수집 기록을 저장하고 적용 중 규칙으로 바로 결과지를 만든다."""
    if not isinstance(exchanges, list) or not exchanges or len(exchanges) > MAX_EXCHANGES:
        raise ServiceError(f"exchanges는 1~{MAX_EXCHANGES}개 배열이어야 합니다.", 422)
    for index, item in enumerate(exchanges):
        if not (isinstance(item, dict) and HEADER.fullmatch(str(item.get("header") or ""))
                and HEX.fullmatch(str(item.get("command") or ""))):
            raise ServiceError(f"exchanges[{index}]의 header·command는 16진수여야 합니다.", 422)
    started = _now()
    text = elm_from_exchanges(exchanges, {"vehicle": vehicle, "device": device_name or "",
                                          "started": started.isoformat(), "source": "app"})
    dataset = upload_dataset(actor, filename=f"app-{started:%Y%m%d-%H%M%S}.txt", content=text.encode(),
                             kind=DatasetKind.LIVE_CAPTURE, vehicle=vehicle, source=DatasetSource.APP)
    return create_report(actor, dataset)


# ── 운영 결과지 ─────────────────────────────────────────────────────────

def _thin(series: list[tuple[float, float]]) -> list[list[float]]:
    step = max(1, len(series) // MAX_SERIES_POINTS)
    return [[t, v] for t, v in series[::step]]


def _describe_dtcs(diagnosis: dict) -> None:
    """고장코드 마스터(codes)에 있는 설명을 붙인다. 고장유형 바이트를 뺀 5자리로도 찾는다."""
    from app.modules.scans.models import Code

    dtcs = [d for codes in diagnosis.get("dtcs", {}).values() for d in codes]
    keys = {d["code"] for d in dtcs} | {d["code"][:5] for d in dtcs}
    if not keys:
        return
    found = {c.code: c.desc for c in db.session.scalars(
        select(Code).where(Code.code.in_(keys), Code.deleted_at.is_(None)))}
    for dtc in dtcs:
        dtc["desc"] = found.get(dtc["code"]) or found.get(dtc["code"][:5])


def _interpret(trace: Trace) -> tuple[dict, dict]:
    """적용 중 규칙으로 값을 계산하고 VIN·ECU·고장코드를 정리한다."""
    values = decode_signals(trace.samples, active_rule_refs())
    for value in values.values():
        value["series"] = _thin(value["series"])
    diagnosis = diagnose(trace)
    _describe_dtcs(diagnosis)
    return values, diagnosis


def preview_capture(content: bytes) -> dict:
    """블루투스 빠른 점검: 기록을 저장하지 않고 해석만 한다."""
    if not content:
        raise ServiceError("빈 기록입니다.")
    limit = current_app.config["CANLAB_MAX_UPLOAD_BYTES"]
    if len(content) > limit:
        raise ServiceError(f"기록이 너무 큽니다. {limit // (1024 * 1024)}MB 이하만 보낼 수 있습니다.", 413)
    values, diagnosis = _interpret(_responded_trace(content))
    return {
        "values": [{"key": key, "label": v["label"], "value": v["value"], "unit": v["unit"]}
                   for key, v in values.items()],
        "vin": diagnosis["vin"],
        "ecus": diagnosis["ecus"],
        "dtcs": diagnosis["dtcs"],
        "dtcCheckedEcus": diagnosis["dtc_checked_ecus"],
    }


def create_report(actor: User, dataset: CanDataset) -> DiagnosticReport:
    if not dataset.is_trace:
        raise ServiceError("결과지는 통신 기록(TRC·실시간 수집)으로만 만들 수 있습니다.")
    trace = load_trace(decode_text(get_dataset(dataset.id, with_content=True).content))
    values, diagnosis = _interpret(trace)
    used = sorted({(v["rule_id"], v["rule_version"]) for v in values.values()})
    report = DiagnosticReport(
        dataset_id=dataset.id, vehicle=dataset.vehicle, values=values, diagnosis=diagnosis,
        rules_used=[{"rule_id": rid, "revision": rev} for rid, rev in used],
        created_by=actor.id, created_at=_now(),
    )
    db.session.add(report)
    db.session.flush()
    audit.record("운영 결과지 생성", "DiagnosticReport", report.id, user_id=actor.id,
                 changes={"dataset": dataset.id, "values": len(values), "rules": len(used)})
    db.session.commit()
    return report


def list_reports() -> list[DiagnosticReport]:
    return list(db.session.scalars(select(DiagnosticReport).order_by(DiagnosticReport.id.desc()).limit(50)))


def get_report(report_id: int) -> DiagnosticReport:
    report = db.session.get(DiagnosticReport, report_id)
    if report is None:
        raise ServiceError("결과지를 찾을 수 없습니다.", 404)
    return report


def report_truths(report: DiagnosticReport) -> dict[str, float]:
    """같은 데이터에 정답값이 있으면 비교용으로 쓴다."""
    if report.dataset is None:
        return {}
    return {t.signal_key: t.value for t in ground_truths(report.dataset)}


def _fmt(value: float | None, unit: str = "") -> str:
    if value is None:
        return "-"
    text = f"{value:,.2f}".rstrip("0").rstrip(".")
    if not unit:
        return text
    return text + (unit if unit in ("%", "°C") else f" {unit}")


def _value(report: DiagnosticReport, key: str) -> float | None:
    entry = report.values.get(key)
    return entry["value"] if entry else None


def template_summary(report: DiagnosticReport) -> str:
    """AI를 쓸 수 없을 때 같은 데이터로 만드는 기본 요약."""
    lines = []
    soc, soh = _value(report, "soc"), _value(report, "soh")
    voltage, current = _value(report, "pack_voltage"), _value(report, "pack_current")
    status = []
    if soc is not None:
        status.append(f"충전 상태(SOC) {_fmt(soc, '%')}")
    if soh is not None:
        status.append(f"건강 상태(SOH) {_fmt(soh, '%')}")
    if voltage is not None:
        status.append(f"팩 전압 {_fmt(voltage, 'V')}")
    if current is not None:
        status.append(f"팩 전류 {_fmt(current, 'A')}")
    lines.append("1. 종합: " + (", ".join(status) + "입니다." if status else "적용 중인 규칙으로 읽은 값이 없습니다."))

    hi, lo = _value(report, "max_cell_v"), _value(report, "min_cell_v")
    if hi is not None and lo is not None:
        gap = (hi - lo) * 1000
        verdict = "양호" if gap <= 30 else ("주의" if gap <= 100 else "점검 필요")
        lines.append(f"2. 셀 전압 편차: 최대 {_fmt(hi, 'V')} / 최소 {_fmt(lo, 'V')}, 차이 {gap:.0f}mV({verdict}).")
    t_hi, t_lo = _value(report, "max_temp"), _value(report, "min_temp")
    if t_hi is not None and t_lo is not None:
        verdict = "양호" if t_hi - t_lo <= 5 else "편차 큼"
        lines.append(f"3. 배터리 온도: 최고 {_fmt(t_hi, '°C')} / 최저 {_fmt(t_lo, '°C')}({verdict}).")

    obd = report.diagnosis.get("obd") or {}
    dtcs = [d for codes in report.diagnosis.get("dtcs", {}).values() for d in codes] + obd.get("dtcs", [])
    codes = list(dict.fromkeys(d["code"] for d in dtcs))
    checked = report.diagnosis.get("dtc_checked_ecus", [])
    if codes:
        lines.append("4. 고장코드: " + ", ".join(codes[:10]) + " — 정비소 점검을 권장합니다.")
    elif checked or any(s.get("command") == "03" and s.get("status") == "ok" for s in obd.get("steps", [])):
        lines.append("4. 고장코드: 조회한 제어기에서 고장코드가 없습니다.")
    else:
        lines.append("4. 고장코드: 이 기록에는 고장코드 조회가 없습니다.")
    errors = report.diagnosis.get("errors") or []
    if errors:
        lines.append(f"5. 스캔 오류 {len(errors)}건: " + ", ".join(f"{e['label']}({e['status_label']})"
                                                         for e in errors[:5]))
    references = [v["label"] for v in report.values.values() if not v.get("rule_id")]
    low_confidence = [v["label"] for v in report.values.values() if v.get("rule_id") and v["confidence"] < 0.8]
    if low_confidence:
        lines.append("※ 신뢰도가 낮은 수식으로 읽은 항목: " + ", ".join(low_confidence))
    if references:
        lines.append("※ 공개 자료로 읽은 참고 값(미검증): " + ", ".join(references))
    return "\n".join(lines)


def summarize_with_ai(actor: User, report: DiagnosticReport) -> DiagnosticReport:
    facts = {
        "vehicle": report.vehicle,
        "values": {v["label"]: {"value": v["value"], "unit": v["unit"], "confidence": v["confidence"]}
                   for v in report.values.values()},
        "dtcs": report.diagnosis.get("dtcs", {}),
        "dtc_checked_ecus": report.diagnosis.get("dtc_checked_ecus", []),
    }
    text, provider = ai.summarize_report(facts)
    report.ai_summary, report.ai_provider = text.strip()[:8000], provider
    audit.record("결과지 AI 요약", "DiagnosticReport", report.id, user_id=actor.id, changes={"provider": provider})
    db.session.commit()
    return report


def chart_data(report: DiagnosticReport) -> dict:
    """결과지 그래프에 넘길 값. 화면 스크립트는 이 JSON만 읽는다."""
    values = report.values
    truths = report_truths(report)

    def pick(keys):
        return [{"label": values[k]["label"], "value": values[k]["value"]} for k in keys if k in values]

    temps = pick(["max_temp", "min_temp", *[f"module_temp_{i}" for i in range(1, 6)], "inlet_temp"])
    cells = pick(["max_cell_v", "min_cell_v"])
    series = {k: values[k]["series"] for k in ("pack_voltage", "pack_current", "soc") if k in values}
    compare = [{"label": values[k]["label"], "truth": truths[k], "decoded": values[k]["value"]}
               for k in values if k in truths]
    return {"soc": _value(report, "soc"), "soh": _value(report, "soh"), "temps": temps, "cells": cells,
            "series": {k: {"label": values[k]["label"], "unit": values[k]["unit"], "points": v}
                       for k, v in series.items()},
            "compare": compare}


RESET_MODELS = (DiagnosticReport, ScanLogic, DecodeRule, AnalysisRun, GroundTruthValue, CanDataset)


def reset_counts() -> dict[str, int]:
    return {m.__tablename__: db.session.scalar(select(func.count()).select_from(m)) for m in RESET_MODELS}


def reset_all() -> dict[str, int]:
    """CAN 분석 데이터(데이터셋, 정답값, 역산 기록, 규칙, 스캔 로직, 운영 결과지)를 모두 지운다.
    스캔 기록(scans)은 남고 그 안의 결과지·통신 기록 번호는 '삭제됨'으로 보인다."""
    counts = reset_counts()
    for model in RESET_MODELS:
        db.session.execute(delete(model))
    audit.record("CAN 분석 초기화", "CanDataset", changes=counts, message="flask canlab reset")
    db.session.commit()
    return counts


def report_exists(report_id: int | None) -> bool:
    return bool(report_id) and db.session.get(DiagnosticReport, report_id) is not None


def overview() -> dict:
    count = {
        "datasets": db.session.scalar(select(func.count(CanDataset.id))),
        "active_rules": db.session.scalar(select(func.count(DecodeRule.id))
                                          .where(DecodeRule.status == RuleStatus.ACTIVE)),
        "runs": db.session.scalar(select(func.count(AnalysisRun.id))),
        "reports": db.session.scalar(select(func.count(DiagnosticReport.id))),
    }
    return count | {"signals": len(signals.SIGNALS), "ai_ready": ai.available_connection() is not None}
