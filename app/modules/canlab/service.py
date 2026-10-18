"""CAN 분석 업무 규칙: 데이터 등록, 정답값, 역산 실행과 규칙 적용, 운영 결과지."""

import hashlib
import io
import re
import time
from collections import Counter
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
from app.modules.canlab import ai, references
from app.modules.canlab.engine import signals, uds
from app.modules.canlab.engine.decode import RuleRef, Trace, decode_signals, diagnose, load_trace
from app.modules.canlab.engine.frames import decode_text, elm_from_exchanges
from app.modules.canlab.engine.search import GroundTruth, Layout, Samples, search
from app.modules.canlab.engine.validate import judge
from app.modules.canlab.models import (
    AnalysisRun, CanDataset, ChangeAction, DatasetKind, DatasetSource, DecodeRule, DiagnosticReport,
    GroundTruthValue, LogicStatus, RuleChange, RuleIncident, RuleStatus, ScanLogic, ScanWescanCompare,
    TruthSource,
)
from app.modules.knowledge import service as knowledge_service
from app.modules.obd import devices as obd_devices
from app.modules.obd.service import list_profiles
from app.modules.scans import car_info

CONFLICT = "다른 관리자가 먼저 바꿨습니다. 새로고침한 뒤 다시 시도하세요."
TRACE_EXTENSIONS = (".trc", ".txt", ".log")
VALUE_EXTENSIONS = (".txt", ".csv", ".tsv")
MAX_TRUTH_LINES = 200
MAX_PDF_PAGES = 20
MAX_AI_PAGES = 3
MAX_SERIES_POINTS = 120
MAX_COMMANDS = 200
MAX_BACKTEST_DATASETS = 30
MAX_INTERPRETED = 50
# 스캔 로직에 넣을 수 있는 읽기 서비스. 세션 변경·보안 접근·쓰기·루틴·지우기는 넣지 않는다.
READ_SERVICES = {0x01, 0x02, 0x03, 0x06, 0x07, 0x09, 0x0A, 0x19, 0x21, 0x22}
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _now() -> datetime:
    return datetime.now(UTC)


# ── 적용 범위(차종 → 제조사 → 공통) ─────────────────────────────────────────

def norm(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "").upper()


def scope_car(maker: str | None, model: str | None) -> dict | None:
    """범위를 차량정보 형태로. 스캔할 때와 같은 방식으로 규칙을 고르려고 쓴다."""
    return {"diag_company": maker, "diag_model": model} if maker else None


def _rank(maker: str | None, model: str | None, car: dict | None) -> int | None:
    """차량에 맞는 범위의 우선순위(클수록 먼저). 맞지 않으면 None.
    차량 정보가 없으면 공통 규칙을 먼저 쓰고, 공통 규칙이 없는 신호는 가장 최근에 적용한 범위 규칙을 쓴다."""
    if not car:
        return 2 if not maker else 1
    if not maker:
        return 0
    if norm(maker) != norm(car.get("diag_company")):
        return None
    if not model:
        return 1
    return 2 if norm(model) == norm(car.get("diag_model")) else None


def _pick(items, car: dict | None, key) -> dict:
    car = car if car and car.get("diag_company") else None
    best: dict = {}
    for item in items:
        rank = _rank(item.maker, item.model, car)
        if rank is None:
            continue
        order = (rank, item.activated_at or EPOCH)
        k = key(item)
        if k not in best or order > best[k][0]:
            best[k] = (order, item)
    return {k: v[1] for k, v in best.items()}


def _exact(query, model_cls, maker: str | None, model: str | None):
    return query.where(func.coalesce(model_cls.maker, "") == (maker or ""),
                       func.coalesce(model_cls.model, "") == (model or ""))


def scope_label(maker: str | None, model: str | None) -> str:
    if maker and model:
        return f"차종 {maker} {model}"
    return f"제조사 {maker}" if maker else "공통"


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
    try:
        dataset = upload_dataset(actor, filename=filename, content=content, kind=DatasetKind.WECAN_TRC,
                                 vehicle=vehicle, note=note)
    except ServiceError as error:
        if error.status != 409:
            raise
        # 같은 기록을 다시 올리면 그 데이터로 다시 분석한다. 최종값이 없던 데이터에만 값을 넣는다.
        dataset = get_dataset(error.extra["dataset_id"])
        if dataset.kind != DatasetKind.WECAN_TRC:
            raise ServiceError(f"이 통신기록은 이미 '{dataset.kind_label}'(데이터 #{dataset.id})로 등록되어 있습니다.",
                               409) from error
        if dataset.truths:
            return dataset
    truths = [_truth(dataset, label, value, unit, None, TruthSource.MANUAL, True) for label, value, unit in typed]
    truths += [_truth(dataset, label, value, unit, page, source, False)
               for label, value, unit, page, source in from_pdf]
    db.session.add_all(truths)
    audit.record("위스캔 최종값 등록", "CanDataset", dataset.id, user_id=actor.id,
                 changes={"typed": len(typed), "pdf": len(from_pdf),
                          "ai": sum(1 for row in from_pdf if row[4] == TruthSource.AI_OCR)})
    db.session.commit()
    return dataset


def vehicle_snapshot(car_no: str, car: dict) -> dict:
    return {"car_no": car_no, "maker": (car.get("diag_company") or "").strip() or None,
            "model": (car.get("diag_model") or "").strip() or None, "submodel": car.get("diag_submodel"),
            "grade": car.get("diag_grade"), "year": car.get("diag_year"),
            "registered": car.get("diag_registred_date")}


def lookup_vehicle(actor: User, car_no: str | None) -> dict:
    """차량번호 조회(차량검색과 같은 조회·캐시). 차종을 정하려면 제조사와 모델이 있어야 한다."""
    try:
        dto, _ = car_info.lookup(actor, car_no)
    except car_info.CarInfoError as error:
        raise ServiceError(f"차량정보 조회 실패: {error.guide}", error.status) from error
    vehicle = vehicle_snapshot(car_info.normalize_car_no(car_no), car_info.normalize_dto(dto))
    if not (vehicle["maker"] and vehicle["model"]):
        raise ServiceError("차량정보에 제조사·모델이 없어 차종을 정할 수 없습니다.")
    return vehicle


def ingest(actor: User, *, car_no: str | None, wescan: tuple[str, bytes], values_text: str,
           values_pdf: tuple[str, bytes] | None, reverse: list[tuple[str, bytes]]) -> tuple[CanDataset, list[CanDataset]]:
    """데이터입력분석: 차량번호로 차종을 정하고 위스캔 통신기록·최종값과 리버스데이터를 올려 명령·응답을 추출한다.
    이미 올린 파일은 그 데이터를 다시 쓴다. 파일 검사를 먼저 해서 일부만 저장되는 일을 줄인다."""
    vehicle = lookup_vehicle(actor, car_no)
    if not reverse:
        raise ServiceError("리버스데이터를 하나 이상 올리세요.")
    for filename, content in reverse:
        if not filename.lower().endswith(TRACE_EXTENSIONS):
            raise ServiceError(f"'{filename}': 리버스데이터는 .trc, .txt, .log 파일이어야 합니다.")
        _responded_trace(content)
    name = " ".join(v for v in (vehicle["maker"], vehicle["model"], vehicle["submodel"]) if v)
    wescan_dataset = upload_wescan(actor, filename=wescan[0], content=wescan[1], vehicle=name,
                                   values_text=values_text, values_pdf=values_pdf)
    reverse_datasets = []
    for filename, content in reverse:
        try:
            dataset = upload_dataset(actor, filename=filename, content=content, kind=DatasetKind.GSCAN_TRC,
                                     vehicle=name)
        except ServiceError as error:
            if error.status != 409:
                raise
            dataset = get_dataset(error.extra["dataset_id"])
            if not dataset.is_trace or dataset.id == wescan_dataset.id:
                raise ServiceError(f"'{filename}'은 리버스데이터로 쓸 수 없습니다(데이터 #{dataset.id}).") from error
        if dataset not in reverse_datasets:
            reverse_datasets.append(dataset)
    for dataset in (wescan_dataset, *reverse_datasets):
        dataset.maker, dataset.model = vehicle["maker"], vehicle["model"]
        dataset.summary = dict(dataset.summary or {}, car=vehicle)
    audit.record("데이터입력분석 등록", "CanDataset", wescan_dataset.id, user_id=actor.id,
                 changes={"vehicle": scope_label(vehicle["maker"], vehicle["model"]),
                          "reverse": [d.id for d in reverse_datasets]})
    db.session.commit()
    return wescan_dataset, reverse_datasets


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


def active_rule(signal_key: str, maker: str | None = None, model: str | None = None) -> DecodeRule | None:
    """그 범위에 적용 중인 규칙(다른 범위에서 빌려 쓰는 규칙은 넣지 않는다)."""
    return db.session.scalar(_exact(select(DecodeRule).where(DecodeRule.signal_key == signal_key,
                                                             DecodeRule.status == RuleStatus.ACTIVE),
                                    DecodeRule, maker, model))


def rules_for(car: dict | None = None) -> dict[str, DecodeRule]:
    """차량에 쓸 규칙. 신호마다 차종 규칙 → 제조사 규칙 → 공통 규칙 순으로 고른다."""
    rules = db.session.scalars(select(DecodeRule).where(DecodeRule.status == RuleStatus.ACTIVE)).all()
    return _pick(rules, car, lambda r: r.signal_key)


def _next_revision(signal_key: str, maker: str | None, model: str | None) -> int:
    current = db.session.scalar(_exact(select(func.max(DecodeRule.revision)).where(DecodeRule.signal_key == signal_key),
                                       DecodeRule, maker, model))
    return (current or 0) + 1


def _activate_layout(signal_key: str, layout: Layout, evidence: dict, confidence: float,
                     run_id: int | None, actor: User, maker: str | None = None,
                     model: str | None = None) -> tuple[DecodeRule, bool]:
    """그 범위에 수식을 적용한다. 같은 수식의 규칙이 있으면 그 버전을, 없으면 새 버전을 쓴다.
    기존 적용 규칙은 '이전 버전'이 된다. (규칙, 새로 적용했는지)를 돌려준다."""
    rules = db.session.scalars(_exact(select(DecodeRule).where(DecodeRule.signal_key == signal_key),
                                      DecodeRule, maker, model)).all()
    same = next((r for r in rules if _layout(r) == layout), None)
    current = next((r for r in rules if r.status == RuleStatus.ACTIVE), None)
    if same is not None and same is current:
        current.evidence, current.confidence = evidence, confidence
        return current, False
    if current is not None:
        current.status, current.retired_at = RuleStatus.RETIRED, _now()
        db.session.flush()
    if same is None:
        same = DecodeRule(signal_key=signal_key, revision=_next_revision(signal_key, maker, model),
                          analysis_run_id=run_id, created_by=actor.id, maker=maker, model=model,
                          **_rule_fields(layout))
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


def _structure(rows: list[tuple[float, bytes]] | None) -> dict | None:
    """응답 바이트 구조: 가장 흔한 길이와 표본 사이에 값이 바뀌는 바이트 위치."""
    if not rows:
        return None
    length = Counter(len(data) for _, data in rows).most_common(1)[0][0]
    payloads = [data for _, data in rows if len(data) == length]
    varying = [i for i in range(length) if len({p[i] for p in payloads}) > 1]
    return {"length": length, "samples": len(rows), "varying": varying}


def _add_structures(commands: dict, ours: Samples, theirs: Samples) -> None:
    """2단계: 공통 명령(22 DID)의 위스캔·리버스 응답 구조를 나란히 놓는다."""
    for row in commands["common"]:
        if row["service"] != "22" or not row["did"]:
            continue
        key = (int(row["header"], 16), int(row["did"], 16))
        w, r = _structure(ours.get(key)), _structure(theirs.get(key))
        row["structure"] = {"wescan": w, "reverse": r,
                            "same_length": bool(w and r and w["length"] == r["length"])}


def interpret_reverse(samples: Samples, index: dict, limit: int = MAX_INTERPRETED) -> list[dict]:
    """1단계: 리버스 응답을 공개 참고자료(승인 자료·OBDb·참고 해석)로 해석한다. 물리 범위 밖 값은 뺀다."""
    out = []
    for (request_id, did), rows in sorted(samples.items())[:limit]:
        payload = rows[-1][1]
        values, seen = [], set()
        for (key, layout), sources in index.items():
            if (layout.request_id, layout.did) != (request_id, did) or key in seen:
                continue
            value = layout.value(payload)
            signal = signals.BY_KEY.get(key)
            if value is None or signal is None or not signal.minimum <= value <= signal.maximum:
                continue
            seen.add(key)
            values.append({"signal_key": key, "label": signal.label, "value": value, "unit": signal.unit,
                           "formula": layout.formula(), "sources": sources[:3]})
        order = [s.key for s in signals.SIGNALS]
        values.sort(key=lambda v: order.index(v["signal_key"]))
        out.append({"header": f"{request_id:03X}", "did": f"{did:04X}", "command": f"22{did:04X}",
                    "example": payload[:24].hex(" ").upper(), "samples": len(rows), "values": values})
    return out


def run_analysis(actor: User, wescan_id: int, reverse_ids: list[int]) -> AnalysisRun:
    """역산 분석 3단계. 1) 리버스 기록의 명령·응답을 참고자료로 해석 2) 위스캔 통신기록과 명령·응답 구조를 대조
    3) 위스캔 최종값과 일치하는 바이트·수식을 찾는다. 규칙은 바꾸지 않는다(디코딩 규칙 후보에서 관리자가 적용)."""
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
        raise ServiceError("위스캔 최종값 중 신호가 지정된 확인 값이 없습니다. 최종값을 확인하고 신호를 고르세요.")
    started = time.perf_counter()
    trace_ids = [wescan.id, *[d.id for d in reverse]]
    ours, theirs = merged_samples([wescan.id]), merged_samples([d.id for d in reverse])
    samples: Samples = {}
    for part in (ours, theirs):
        for key, rows in part.items():
            samples.setdefault(key, []).extend(rows)
    if not samples:
        raise ServiceError("고른 기록에 데이터 조회(0x22) 응답이 없습니다.")
    car = scope_car(wescan.maker, wescan.model)
    index = references.hypotheses(car)
    ranked = search(samples, truths, index)
    decisions = judge(truths, ranked, samples)

    commands = compare_commands(wescan, reverse)
    _add_structures(commands, ours, theirs)
    run = AnalysisRun(trace_dataset_ids=trace_ids, reverse_dataset_ids=[d.id for d in reverse],
                      truth_dataset_id=wescan.id, commands=commands, maker=wescan.maker, model=wescan.model,
                      vehicle=(wescan.summary or {}).get("car"), interpretation=interpret_reverse(theirs, index),
                      created_by=actor.id, created_at=_now(), result={})
    db.session.add(run)
    db.session.flush()

    active = rules_for(car)
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
                entry["reasons"].append(f"적용 중 수식({current.scope_label} v{current.revision}: {current.formula})과 "
                                        "다릅니다. 디코딩 규칙 후보에서 변경 전후를 비교하세요.")
        result[truth.signal_key] = entry

    run.result = result
    run.duration_ms = int((time.perf_counter() - started) * 1000)
    audit.record("CAN 역산 실행", "AnalysisRun", run.id, user_id=actor.id,
                 changes={"wescan": wescan.id, "reverse": run.reverse_dataset_ids, "signals": len(truths),
                          "scope": scope_label(run.maker, run.model),
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
    """보류·이전 버전 규칙을 그 범위에 적용한다(되돌리기 포함)."""
    if rule.version != version:
        raise ServiceError(CONFLICT, 409)
    if rule.status == RuleStatus.ACTIVE:
        return rule
    before = scope_snapshot(rule.maker, rule.model)
    current = active_rule(rule.signal_key, rule.maker, rule.model)
    if current is not None:
        current.status, current.retired_at = RuleStatus.RETIRED, _now()
    try:
        db.session.flush()
        rule.status, rule.activated_at, rule.retired_at = RuleStatus.ACTIVE, _now(), None
        db.session.flush()
        _record_change(actor, ChangeAction.ACTIVATE, rule.maker, rule.model, before,
                       note=f"{rule.signal_key} v{rule.revision}")
        audit.record("디코딩 규칙 적용", "DecodeRule", rule.id, user_id=actor.id,
                     changes={"signal": rule.signal_key, "revision": rule.revision, "scope": rule.scope_label,
                              "replaced": current.revision if current else None})
        from app.modules.knowledge.service import remember_rule

        remember_rule(rule, actor.id)
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
    before = scope_snapshot(rule.maker, rule.model)
    rule.status, rule.retired_at = RuleStatus.RETIRED, _now()
    try:
        db.session.flush()
        _record_change(actor, ChangeAction.RETIRE, rule.maker, rule.model, before,
                       note=f"{rule.signal_key} v{rule.revision}")
        audit.record("디코딩 규칙 해제", "DecodeRule", rule.id, user_id=actor.id,
                     changes={"signal": rule.signal_key, "revision": rule.revision, "scope": rule.scope_label})
        db.session.commit()
    except StaleDataError as exc:
        db.session.rollback()
        raise ServiceError(CONFLICT, 409) from exc
    return rule


def active_rule_refs(car: dict | None = None) -> list[RuleRef]:
    return [RuleRef(r.id, r.revision, r.signal_key, _layout(r), r.confidence) for r in rules_for(car).values()]


# ── 변경 이력과 되돌리기 ───────────────────────────────────────────────

def _logic_in_scope(maker: str | None, model: str | None) -> ScanLogic | None:
    return db.session.scalar(_exact(select(ScanLogic).where(ScanLogic.status == LogicStatus.ACTIVE),
                                    ScanLogic, maker, model))


def scope_snapshot(maker: str | None, model: str | None) -> dict:
    """범위 하나의 적용 상태: 적용 중 로직과 그 범위의 적용 규칙."""
    logic = _logic_in_scope(maker, model)
    rules = db.session.scalars(_exact(select(DecodeRule).where(DecodeRule.status == RuleStatus.ACTIVE),
                                      DecodeRule, maker, model).order_by(DecodeRule.signal_key)).all()
    return {"logic_id": logic.id if logic else None, "logic_revision": logic.revision if logic else None,
            "rules": [{"signal_key": r.signal_key, "rule_id": r.id, "revision": r.revision, "formula": r.formula}
                      for r in rules]}


def _record_change(actor: User, action: str, maker: str | None, model: str | None, before: dict,
                   logic: ScanLogic | None = None, backtest: dict | None = None,
                   note: str | None = None) -> RuleChange:
    change = RuleChange(action=action, maker=maker, model=model, logic_id=logic.id if logic else None,
                        before=before, after=scope_snapshot(maker, model), backtest=backtest,
                        note=(note or "")[:300] or None, created_by=actor.id, created_at=_now())
    db.session.add(change)
    db.session.flush()
    return change


def list_changes(limit: int = 50) -> list[RuleChange]:
    return list(db.session.scalars(select(RuleChange).order_by(RuleChange.id.desc()).limit(limit)))


def get_change(change_id: int) -> RuleChange:
    change = db.session.get(RuleChange, change_id)
    if change is None:
        raise ServiceError("변경 이력을 찾을 수 없습니다.", 404)
    return change


def rollback_change(actor: User, change: RuleChange) -> RuleChange:
    """변경 이전 상태(before)로 그 범위만 되돌린다. 다른 범위의 규칙은 그대로 둔다."""
    if change.reverted_by_id:
        raise ServiceError("이미 되돌린 변경입니다. 변경 이력에서 최신 상태를 확인하세요.", 409)
    maker, model = change.maker, change.model
    before_now = scope_snapshot(maker, model)
    wanted = {r["signal_key"]: r["rule_id"] for r in change.before.get("rules", [])}
    try:
        for rule in db.session.scalars(_exact(select(DecodeRule).where(DecodeRule.status == RuleStatus.ACTIVE),
                                              DecodeRule, maker, model)):
            if wanted.get(rule.signal_key) != rule.id:
                rule.status, rule.retired_at = RuleStatus.RETIRED, _now()
        target = change.before.get("logic_id")
        current = _logic_in_scope(maker, model)
        if current is not None and current.id != target:
            current.status, current.retired_at = LogicStatus.RETIRED, _now()
        db.session.flush()
        from app.modules.knowledge.service import remember_command, remember_rule

        for rule_id in wanted.values():
            rule = db.session.get(DecodeRule, rule_id)
            if rule is not None and rule.status != RuleStatus.ACTIVE:
                rule.status, rule.activated_at, rule.retired_at = RuleStatus.ACTIVE, _now(), None
            if rule is not None and rule.status == RuleStatus.ACTIVE:
                remember_rule(rule, actor.id)
        logic = db.session.get(ScanLogic, target) if target else None
        if logic is not None and logic.status != LogicStatus.ACTIVE:
            logic.status, logic.activated_at, logic.retired_at = LogicStatus.ACTIVE, _now(), None
        if logic is not None and logic.status == LogicStatus.ACTIVE:
            for command in logic.commands or []:
                remember_command(maker=logic.maker, model=logic.model, header=command.get("header"),
                                 command=command.get("command") or "", label=command.get("label"),
                                 user_id=actor.id)
        db.session.flush()
        new = _record_change(actor, ChangeAction.ROLLBACK, maker, model, before_now, logic=logic,
                             note=f"변경 #{change.id}({change.action_label}) 이전으로")
        change.reverted_by_id = new.id
        audit.record("디코딩 규칙 되돌리기", "RuleChange", change.id, user_id=actor.id,
                     changes={"scope": scope_label(maker, model), "rollback": new.id})
        db.session.commit()
    except StaleDataError as exc:
        db.session.rollback()
        raise ServiceError(CONFLICT, 409) from exc
    return new


def record_incidents(scan_id: int, logic: ScanLogic | None, errors: list[dict]) -> int:
    """스캔에서 생긴 로직 문제(로직 명령 실패, 수식으로 값을 읽지 못함)를 문제 로그에 쌓는다."""
    rows = [RuleIncident(scan_id=scan_id, maker=logic.maker if logic else None,
                         model=logic.model if logic else None, logic_id=logic.id if logic else None,
                         label=str(e.get("label") or "")[:200],
                         command=" ".join(v for v in (e.get("header"), e.get("command")) if v)[:40] or None,
                         message=str(e.get("message") or "")[:300], created_at=_now())
            for e in errors if e.get("group") == "logic"]
    db.session.add_all(rows)
    return len(rows)


def list_incidents(limit: int = 50) -> list[RuleIncident]:
    return list(db.session.scalars(select(RuleIncident).order_by(RuleIncident.id.desc()).limit(limit)))


# ── 스캔 로직(스캔하기에 쓰는 명령·수식 묶음) ─────────────────────────────

CHOICES = {"before": "변경 전 유지", "after": "변경 후 적용", "exclude": "빼기"}


def active_logic(car: dict | None = None) -> ScanLogic | None:
    """차량에 쓸 스캔 로직: 차종 로직 → 제조사 로직 → 공통 로직."""
    logics = db.session.scalars(select(ScanLogic).where(ScanLogic.status == LogicStatus.ACTIVE)).all()
    return _pick(logics, car, lambda _: 0).get(0)


def active_logics() -> list[ScanLogic]:
    return list(db.session.scalars(select(ScanLogic).where(ScanLogic.status == LogicStatus.ACTIVE)
                                   .order_by(ScanLogic.maker.nulls_first(), ScanLogic.model.nulls_first())))


def draft_logics() -> list[ScanLogic]:
    return list(db.session.scalars(select(ScanLogic).where(ScanLogic.status == LogicStatus.DRAFT)
                                   .order_by(ScanLogic.id.desc())))


def list_logics() -> list[ScanLogic]:
    return list(db.session.scalars(select(ScanLogic).order_by(ScanLogic.revision.desc()).limit(50)))


def get_logic(logic_id: int) -> ScanLogic:
    logic = db.session.get(ScanLogic, logic_id)
    if logic is None:
        raise ServiceError("스캔 로직을 찾을 수 없습니다.", 404)
    return logic


def logic_commands(car: dict | None = None) -> list[dict]:
    logic = active_logic(car)
    return list(logic.commands) if logic else []


def _rule_side(rule: DecodeRule) -> dict:
    return {"rule_id": rule.id, "revision": rule.revision, "formula": rule.formula, "scope": rule.scope_label,
            "source": f"{rule.request_id} 22 {rule.did}", "layout": _layout(rule).to_dict()}


def item_options(item: dict) -> list[str]:
    if item["change"] == "same":
        return ["before", "exclude"]
    return [c for c in ("before", "after") if item[c]] + ["exclude"]


def _decoded_values(samples: Samples, layout: Layout, signal_key: str) -> list[float]:
    signal = signals.BY_KEY.get(signal_key)
    values = []
    for _, data in samples.get((layout.request_id, layout.did), []):
        value = layout.value(data)
        if value is not None and (signal is None or signal.minimum <= value <= signal.maximum):
            values.append(value)
    return values


def backtest_datasets(maker: str | None, model: str | None) -> list[CanDataset]:
    """과거 비교에 쓸 같은 범위의 통신 기록(차종 후보는 같은 차종, 제조사 후보는 같은 제조사)."""
    kinds = [k.value for k in DatasetKind if k.is_trace]
    rows = db.session.scalars(select(CanDataset).where(CanDataset.kind.in_(kinds), CanDataset.maker.is_not(None))
                              .order_by(CanDataset.id.desc())).all()
    picked = [d for d in rows if norm(d.maker) == norm(maker) and (not model or norm(d.model) == norm(model))]
    return picked[:MAX_BACKTEST_DATASETS]


def backtest(maker: str | None, model: str | None, items: list[dict]) -> dict:
    """신호 항목마다 현재 규칙(변경 전)과 후보 규칙(변경 후)으로 과거 기록을 다시 읽어 비교한다.
    최종값이 있는 기록은 일치 건수, 없는 기록은 물리 범위 안에서 읽힌 건수를 센다."""
    targets = [i for i in items if i["kind"] == "signal" and (i["before"] or i["after"])]
    datasets = backtest_datasets(maker, model) if maker else []
    stats = {i["signal_key"]: {"datasets": 0, "with_truth": 0, "before_match": 0, "after_match": 0,
                               "before_read": 0, "after_read": 0} for i in targets}
    for dataset in datasets:
        samples = load_trace(decode_text(get_dataset(dataset.id, with_content=True).content)).samples
        truths = {t.signal_key: t for t in ground_truths(dataset)}
        for item in targets:
            row, truth = stats[item["signal_key"]], truths.get(item["signal_key"])
            row["datasets"] += 1
            row["with_truth"] += truth is not None
            for side in ("before", "after"):
                if not item[side]:
                    continue
                values = _decoded_values(samples, Layout.from_dict(item[side]["layout"]), item["signal_key"])
                row[f"{side}_read"] += bool(values)
                if truth and values and min(abs(v - truth.value) for v in values) <= truth.tolerance:
                    row[f"{side}_match"] += 1
    for row in stats.values():
        metric = "match" if row["with_truth"] else "read"
        before, after = row[f"before_{metric}"], row[f"after_{metric}"]
        row["verdict"] = ("과거 데이터 없음" if not row["datasets"]
                          else "개선" if after > before else "악화" if after < before else "같음")
    return {"scope": scope_label(maker, model),
            "datasets": [{"id": d.id, "filename": d.filename, "kind": d.kind_label} for d in datasets],
            "signals": stats}


def _diff_items(before_cmds: dict, after_cmds: dict, before_rules: dict[str, DecodeRule],
                after_entries: dict[str, dict]) -> list[dict]:
    """명령·수식 항목별 변경 전·후와 기본안(확정 수식은 변경 후, 가설·UNKNOWN은 변경 전 유지)."""
    items = []
    for key in list(before_cmds) + [k for k in after_cmds if k not in before_cmds]:
        before, after = before_cmds.get(key), after_cmds.get(key)
        change = "same" if before and after else ("added" if after else "removed")
        items.append({"key": f"cmd:{key[0]}:{key[1]}", "kind": "command", "label": f"{key[0]} {key[1]}",
                      "before": before, "after": after, "change": change,
                      "default": "after" if change == "added" else "before"})
    order = [s.key for s in signals.SIGNALS]
    keys = sorted(set(before_rules) | set(after_entries), key=lambda k: order.index(k) if k in order else len(order))
    for key in keys:
        rule, after = before_rules.get(key), after_entries.get(key)
        before = _rule_side(rule) if rule else None
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
    return items


def _apply_backtest(items: list[dict], result: dict) -> None:
    """과거 데이터에서 후보가 현재보다 나쁘면 기본안을 '변경 전 유지'(없으면 빼기)로 바꾼다."""
    for item in items:
        row = result["signals"].get(item.get("signal_key") or "")
        if row and row["verdict"] == "악화" and item["default"] == "after":
            item["default"] = "before" if item["before"] else "exclude"
            item["note"] = "과거 데이터에서 현재 규칙보다 덜 맞아 기본안을 바꿨습니다."


def _new_logic(actor: User, maker: str | None, model: str | None, items: list[dict], diff: dict,
               run_id: int | None, action: str) -> ScanLogic:
    result = backtest(maker, model, items)
    _apply_backtest(items, result)
    revision = (db.session.scalar(select(func.max(ScanLogic.revision))) or 0) + 1
    current = active_logic(scope_car(maker, model))
    logic = ScanLogic(revision=revision, status=LogicStatus.DRAFT, commands=[], rules=[], analysis_run_id=run_id,
                      created_by=actor.id, maker=maker, model=model,
                      diff={"items": items, "backtest": result, "action": action,
                            "base_revision": current.revision if current else None,
                            "base_scope": current.scope_label if current else None, **diff})
    db.session.add(logic)
    db.session.flush()
    audit.record("디코딩 규칙 후보", "ScanLogic", logic.id, user_id=actor.id,
                 changes={"revision": revision, "scope": scope_label(maker, model), "items": len(items),
                          "action": action, "backtest_datasets": len(result["datasets"])})
    db.session.commit()
    return logic


def draft_logic(actor: User, run: AnalysisRun) -> ScanLogic:
    """분석 결과로 차종 범위의 디코딩 규칙 후보(적용 전 로직)를 만든다. 이 차종에 지금 쓰는 명령·수식(변경 전)과
    분석 결과(변경 후)를 비교하고, 같은 차종의 과거 데이터로 다시 읽어 본 결과를 함께 남긴다."""
    car = scope_car(run.maker, run.model)
    before_cmds = {(c["header"], c["command"]): c for c in logic_commands(car)}
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
    after_entries = {key: {"formula": e["formula"], "layout": e["layout"], "status": e["status"],
                           "decoded": e["decoded"], "truth": e["truth"], "score": e["score"],
                           "evidence": e["evidence"]}
                     for key, e in run.result.items() if e.get("layout")}
    items = _diff_items(before_cmds, after_cmds, rules_for(car), after_entries)
    return _new_logic(actor, run.maker, run.model, items, {"run_id": run.id}, run.id, ChangeAction.APPLY)


def draft_expansion(actor: User, logic: ScanLogic) -> ScanLogic:
    """적용 중인 차종 로직을 같은 제조사 전체로 넓히는 후보. 그 제조사의 다른 차종 데이터로 과거 비교를 한다."""
    if logic.status != LogicStatus.ACTIVE or not (logic.maker and logic.model):
        raise ServiceError("적용 중인 차종 로직만 제조사로 확대할 수 있습니다.", 409)
    car = scope_car(logic.maker, None)
    before_cmds = {(c["header"], c["command"]): c for c in logic_commands(car)}
    after_cmds = {(c["header"], c["command"]): c for c in logic.commands}
    after_entries = {}
    for ref in logic.rules:
        rule = db.session.get(DecodeRule, ref["rule_id"])
        if rule is None or rule.status != RuleStatus.ACTIVE:
            continue
        after_entries[rule.signal_key] = {"formula": rule.formula, "layout": _layout(rule).to_dict(),
                                          "status": "확정", "decoded": None, "truth": None,
                                          "score": rule.confidence, "evidence": rule.evidence,
                                          "from_rule": rule.id}
    items = _diff_items(before_cmds, after_cmds, rules_for(car), after_entries)
    return _new_logic(actor, logic.maker, None, items, {"run_id": logic.analysis_run_id, "from_logic": logic.id,
                                                        "from_scope": logic.scope_label},
                      logic.analysis_run_id, ChangeAction.EXPAND)


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
    previous = _logic_in_scope(logic.maker, logic.model)
    if previous is not None and previous is not logic:
        previous.status, previous.retired_at = LogicStatus.RETIRED, _now()
        db.session.flush()
    logic.status, logic.activated_at, logic.retired_at = LogicStatus.ACTIVE, _now(), None
    return previous


def confirm_logic(actor: User, logic: ScanLogic, version: int, choices: dict[str, str]) -> ScanLogic:
    """관리자가 고른 항목으로 후보를 그 범위(차종 또는 제조사)에 적용한다. 고른 수식은 그 범위의 규칙이 되고
    그 범위의 이전 로직은 '이전 버전'이 된다. 변경 전 상태는 변경 이력에 남겨 되돌릴 수 있다."""
    if logic.version != version:
        raise ServiceError(CONFLICT, 409)
    if logic.status != LogicStatus.DRAFT:
        raise ServiceError("이미 처리한 후보입니다. 디코딩 규칙 화면에서 버전을 확인하세요.", 409)
    maker, model = logic.maker, logic.model
    before_state = scope_snapshot(maker, model)
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
            key, current = item["signal_key"], active_rule(item["signal_key"], maker, model)
            if choice == "after":
                after = item["after"]
                rule, changed = _activate_layout(key, Layout.from_dict(after["layout"]), after["evidence"],
                                                 after["score"], logic.analysis_run_id, actor, maker, model)
                activated += changed
            elif choice == "before" and item["before"]:
                rule = db.session.get(DecodeRule, item["before"]["rule_id"])
                rule = rule if rule is not None and rule.status == RuleStatus.ACTIVE else None
            else:
                rule = None
                if current is not None:
                    current.status, current.retired_at = RuleStatus.RETIRED, _now()
            if rule is not None:
                rules.append({"signal_key": key, "rule_id": rule.id, "revision": rule.revision,
                              "formula": rule.formula, "scope": rule.scope_label})
        previous = _switch_active_logic(logic)
        logic.commands, logic.rules = commands, rules
        logic.diff = dict(logic.diff, chosen=chosen)
        if logic.analysis_run_id and (run := db.session.get(AnalysisRun, logic.analysis_run_id)):
            run.activated_count = (run.activated_count or 0) + activated
        db.session.flush()
        action = logic.diff.get("action") or ChangeAction.APPLY
        _record_change(actor, action, maker, model, before_state, logic=logic, backtest=logic.diff.get("backtest"),
                       note=f"후보 v{logic.revision}")
        from app.modules.knowledge.service import remember_command, remember_rule

        for command in commands:
            remember_command(maker=maker, model=model, header=command.get("header"),
                             command=command.get("command") or "", label=command.get("label"), user_id=actor.id)
        for ref in rules:
            applied = db.session.get(DecodeRule, ref["rule_id"])
            if applied is not None:
                remember_rule(applied, actor.id)
        audit.record("디코딩 규칙 후보 적용", "ScanLogic", logic.id, user_id=actor.id,
                     changes={"revision": logic.revision, "scope": logic.scope_label, "commands": len(commands),
                              "rules": len(rules), "activated": activated,
                              "replaced": previous.revision if previous else None})
        db.session.commit()
    except StaleDataError as exc:
        db.session.rollback()
        raise ServiceError(CONFLICT, 409) from exc
    return logic


def capture_requests(car: dict | None = None) -> list[dict]:
    """실시간 수집·스캔에서 보낼 요청. 이 차량에 쓰는 스캔 로직의 명령, 그다음 적용 규칙이 쓰는 ECU·DID와
    고장코드·VIN 조회."""
    requests = [{"header": c["header"], "command": c["command"]} for c in logic_commands(car)]
    pairs = sorted({(r.layout.request_id, r.layout.did) for r in active_rule_refs(car)})
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


def _interpret(trace: Trace, car: dict | None = None) -> tuple[dict, dict]:
    """차량에 쓰는 적용 규칙으로 값을 계산하고 VIN·ECU·고장코드를 정리한다."""
    values = decode_signals(trace.samples, active_rule_refs(car))
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
    values, diagnosis = _interpret(trace, scope_car(dataset.maker, dataset.model))
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


def _attach_wescan_truths(actor: User, dataset: CanDataset, values_text: str,
                          values_pdf: tuple[str, bytes] | None) -> int:
    """위스캔 결과치를 스캔 데이터셋에 확인된(또는 PDF면 미확인) 정답값으로 넣는다."""
    typed = [row for row in parse_truth_lines(values_text) if _numeric(row[1])]
    from_pdf = pdf_values(*values_pdf) if values_pdf else []
    if not typed and not from_pdf:
        raise ServiceError("위스캔 결과치를 '항목명 | 값 | 단위'로 올리거나 붙여 넣으세요(숫자 값 1개 이상).")
    truths = [_truth(dataset, label, value, unit, None, TruthSource.MANUAL, True) for label, value, unit in typed]
    truths += [_truth(dataset, label, value, unit, page, source, False)
               for label, value, unit, page, source in from_pdf]
    truths = [t for t in truths if t is not None]
    db.session.add_all(truths)
    audit.record("스캔·위스캔 비교 정답값", "CanDataset", dataset.id, user_id=actor.id,
                 changes={"typed": len(typed), "pdf": len(from_pdf)})
    db.session.commit()
    return len(truths)


def _compare_diff(decoded: dict, truths: list[GroundTruth], car: dict | None = None) -> list[dict]:
    """적용 규칙으로 읽은 값과 위스캔 결과치를 신호별로 나란히 본다."""
    by_key = {t.signal_key: t for t in truths}
    active_keys = set(rules_for(car))
    rows = []
    order = [s.key for s in signals.SIGNALS]
    keys = sorted(set(decoded) | set(by_key), key=lambda k: order.index(k) if k in order else len(order))
    for key in keys:
        signal = signals.BY_KEY.get(key)
        label = signal.label if signal else key
        unit = signal.unit if signal else ""
        scan = decoded.get(key)
        truth = by_key.get(key)
        scan_value = scan["value"] if scan else None
        wescan_value = truth.value if truth else None
        if scan is None and truth is not None:
            if key not in active_keys:
                status, note = "no_rule", "적용 중 규칙이 없습니다."
            else:
                status, note = "wescan_only", "규칙으로 값을 읽지 못했습니다."
        elif truth is None:
            status, note = "scan_only", "위스캔 결과치에 없습니다."
        elif abs(scan_value - wescan_value) <= truth.tolerance:
            status, note = "match", "일치"
        else:
            status, note = "mismatch", f"오차 {abs(scan_value - wescan_value):.4g} (허용 {truth.tolerance})"
        rows.append({"signal_key": key, "label": label, "unit": unit, "status": status,
                     "scan_value": scan_value, "wescan_value": wescan_value, "note": note,
                     "formula": (scan or {}).get("formula"), "rule_id": (scan or {}).get("rule_id")})
    return rows


def run_scan_truth_analysis(actor: User, dataset: CanDataset) -> AnalysisRun:
    """스캔 기록 표본과 그 데이터에 붙인 위스캔 결과치로 수식을 찾는다(리버스 없이). 규칙은 바꾸지 않는다."""
    truths = ground_truths(dataset)
    if not truths:
        raise ServiceError("위스캔 결과치 중 신호가 지정된 확인 값이 없습니다. 값을 확인하고 신호를 고르세요.")
    started = time.perf_counter()
    samples = merged_samples([dataset.id])
    if not samples:
        raise ServiceError("스캔 기록에 데이터 조회(0x22) 응답이 없습니다.")
    car = scope_car(dataset.maker, dataset.model)
    index = references.hypotheses(car)
    ranked = search(samples, truths, index)
    decisions = judge(truths, ranked, samples)
    run = AnalysisRun(trace_dataset_ids=[dataset.id], reverse_dataset_ids=[], truth_dataset_id=dataset.id,
                      commands={"common": [], "wescan_only": [], "reverse_only": []},
                      maker=dataset.maker, model=dataset.model,
                      vehicle=(dataset.summary or {}).get("car"), interpretation=[],
                      created_by=actor.id, created_at=_now(), result={})
    db.session.add(run)
    db.session.flush()
    active = rules_for(car)
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
        result[truth.signal_key] = entry
    run.result = result
    run.duration_ms = int((time.perf_counter() - started) * 1000)
    audit.record("스캔·위스캔 비교 역산", "AnalysisRun", run.id, user_id=actor.id,
                 changes={"dataset": dataset.id, "signals": len(truths), "scope": scope_label(run.maker, run.model)})
    db.session.commit()
    return run


def compare_scan_wescan(actor: User, *, dataset: CanDataset, values_text: str,
                        values_pdf: tuple[str, bytes] | None = None,
                        scan_id: int | None = None) -> ScanWescanCompare:
    """스캔 통신기록을 적용 규칙으로 읽고 위스캔 결과치와 비교한 뒤, 수식 후보·AI 최적안 DRAFT를 만든다."""
    if not dataset.is_trace:
        raise ServiceError("비교할 스캔은 통신 기록이어야 합니다.")
    _attach_wescan_truths(actor, dataset, values_text, values_pdf)
    dataset = get_dataset(dataset.id)
    if any(not t.confirmed for t in dataset.truths):
        raise ServiceError("PDF에서 읽은 미확인 결과치가 있습니다. 데이터 화면에서 확인한 뒤 다시 비교하세요.", 409)
    car = scope_car(dataset.maker, dataset.model)
    trace = load_trace(decode_text(get_dataset(dataset.id, with_content=True).content))
    decoded_full, _ = _interpret(trace, car)
    decoded = {k: {"label": v["label"], "value": v["value"], "unit": v["unit"],
                   "formula": v.get("formula"), "rule_id": v.get("rule_id")} for k, v in decoded_full.items()}
    truths = ground_truths(dataset)
    diff = _compare_diff(decoded, truths, car)
    run = run_scan_truth_analysis(actor, dataset)
    logic = draft_logic(actor, run)
    problem = None
    try:
        _, problem = advise_logic(actor, logic)
    except ServiceError as error:
        problem = error.message
    logic = get_logic(logic.id)
    summary = (logic.ai_advice or {}).get("summary") or (
        f"차이 {sum(1 for d in diff if d['status'] == 'mismatch')}건, 규칙 없음 "
        f"{sum(1 for d in diff if d['status'] == 'no_rule')}건."
        + (f" ({problem})" if problem else "")
    )
    compare = ScanWescanCompare(
        scan_dataset_id=dataset.id, scan_id=scan_id, analysis_run_id=run.id, logic_id=logic.id,
        maker=dataset.maker, model=dataset.model, decoded=decoded, diff=diff,
        ai_summary=summary, ai_provider=(logic.ai_advice or {}).get("provider"),
        created_by=actor.id, created_at=_now(),
    )
    db.session.add(compare)
    db.session.flush()
    audit.record("스캔·위스캔 비교", "ScanWescanCompare", compare.id, user_id=actor.id,
                 changes={"dataset": dataset.id, "diff": len(diff), "logic": logic.id, "run": run.id})
    db.session.commit()
    return compare


def start_compare(actor: User, *, dataset_id: int | None, scan_file: tuple[str, bytes] | None,
                  values_text: str, values_pdf: tuple[str, bytes] | None = None,
                  scan_id: int | None = None) -> ScanWescanCompare:
    """저장된 스캔 dataset 또는 업로드 파일로 비교를 시작한다."""
    if dataset_id:
        dataset = get_dataset(dataset_id)
    elif scan_file:
        filename, content = scan_file
        try:
            dataset = upload_dataset(actor, filename=filename, content=content,
                                     kind=DatasetKind.LIVE_CAPTURE, vehicle="스캔 비교")
        except ServiceError as error:
            if error.status != 409 or "dataset_id" not in error.extra:
                raise
            dataset = get_dataset(error.extra["dataset_id"])
            if not dataset.is_trace:
                raise ServiceError(f"'{filename}'은 스캔 통신 기록으로 쓸 수 없습니다.") from error
    else:
        raise ServiceError("저장된 스캔 통신기록을 고르거나 파일을 올리세요.")
    if scan_id and not (dataset.maker and dataset.model):
        from app.modules.scans.models import Scan

        scan = db.session.get(Scan, scan_id)
        if scan is not None:
            dataset.maker = dataset.maker or scan.car_maker
            dataset.model = dataset.model or scan.car_model
            car = dict((dataset.summary or {}).get("car") or {})
            car.setdefault("car_no", scan.car_no)
            car.setdefault("maker", scan.car_maker)
            car.setdefault("model", scan.car_model)
            dataset.summary = dict(dataset.summary or {}, car=car)
            db.session.commit()
    return compare_scan_wescan(actor, dataset=dataset, values_text=values_text,
                               values_pdf=values_pdf, scan_id=scan_id)


def list_compares(limit: int = 50) -> list[ScanWescanCompare]:
    return list(db.session.scalars(select(ScanWescanCompare).order_by(ScanWescanCompare.id.desc()).limit(limit)))


def get_compare(compare_id: int) -> ScanWescanCompare:
    row = db.session.get(ScanWescanCompare, compare_id)
    if row is None:
        raise ServiceError("비교 기록을 찾을 수 없습니다.", 404)
    return row


def dataset_choice_label(dataset: CanDataset) -> str:
    car = ((dataset.summary or {}).get("car") or {}).get("car_no") or ""
    label = f"#{dataset.id} {dataset.filename}"
    if car:
        label += f" · {car}"
    elif dataset.vehicle:
        label += f" · {dataset.vehicle}"
    return label


def scan_trace_datasets() -> list[CanDataset]:
    """비교에 고를 수 있는 스캔·수집 통신 기록(실시간 수집·업로드 TRC)."""
    kinds = [DatasetKind.LIVE_CAPTURE.value, DatasetKind.GSCAN_TRC.value, DatasetKind.WECAN_TRC.value]
    return list(db.session.scalars(select(CanDataset).where(CanDataset.kind.in_(kinds))
                                   .order_by(CanDataset.id.desc()).limit(100)))


RESET_MODELS = (ScanWescanCompare, DiagnosticReport, RuleIncident, RuleChange, ScanLogic, DecodeRule, AnalysisRun,
                GroundTruthValue, CanDataset)


def reset_counts() -> dict[str, int]:
    return {m.__tablename__: db.session.scalar(select(func.count()).select_from(m)) for m in RESET_MODELS}


def reset_all() -> dict[str, int]:
    """CAN 분석 데이터(데이터셋, 정답값, 역산 기록, 규칙, 스캔 로직, 변경·문제 로그, 운영 결과지)를 모두 지운다.
    참고자료 DB(can_references)는 분석 데이터가 아니므로 남긴다.
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
    # Knowledge base stats
    kb_commands = len(knowledge_service.list_commands(status="verified", limit=1000))
    kb_formulas = len(knowledge_service.list_formulas(status="verified", limit=1000))
    kb_dtcs = len(knowledge_service.list_dtcs(status="verified", limit=10000))
    return count | {
        "signals": len(signals.SIGNALS), "ai_ready": ai.available_connection() is not None,
        "kb_commands": kb_commands, "kb_formulas": kb_formulas, "kb_dtcs": kb_dtcs,
    }
