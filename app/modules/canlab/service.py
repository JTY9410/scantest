"""CAN 분석 업무 규칙: 데이터 등록, 정답값, 역산 실행과 규칙 적용, 운영 결과지."""

import hashlib
import io
import re
import time
from datetime import UTC, datetime
from typing import Any

from flask import current_app, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import undefer
from sqlalchemy.orm.exc import StaleDataError

from app.core import audit
from app.core.errors import ServiceError
from app.extensions import db
from app.modules.accounts.models import User
from app.modules.canlab import ai
from app.modules.canlab.engine import signals
from app.modules.canlab.engine.decode import RuleRef, Trace, decode_signals, diagnose, load_trace
from app.modules.canlab.engine.frames import decode_text, elm_from_exchanges
from app.modules.canlab.engine.search import GroundTruth, Layout, Samples, search
from app.modules.canlab.engine.validate import judge
from app.modules.canlab.models import (
    AnalysisRun, CanDataset, DatasetKind, DatasetSource, DecodeRule, DiagnosticReport,
    GroundTruthValue, RuleStatus, TruthSource,
)
from app.modules.obd.service import list_profiles

CONFLICT = "다른 관리자가 먼저 바꿨습니다. 새로고침한 뒤 다시 시도하세요."
TRACE_EXTENSIONS = (".trc", ".txt", ".log")
MAX_TRUTH_LINES = 200
MAX_SERIES_POINTS = 120


def _now() -> datetime:
    return datetime.now(UTC)


# ── 데이터 ─────────────────────────────────────────────────────────────

def list_datasets() -> list[CanDataset]:
    return list(db.session.scalars(select(CanDataset).order_by(CanDataset.id.desc())))


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
    }


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
    images = list(reader.pages[page - 1].images)
    if not images:
        raise ServiceError("이 페이지에는 그림이 없습니다.", 404)
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


def truth_datasets() -> list[CanDataset]:
    """확인된 정답값이 하나 이상 있는 데이터."""
    ids = select(GroundTruthValue.dataset_id).where(GroundTruthValue.confirmed.is_(True)).distinct()
    return list(db.session.scalars(select(CanDataset).where(CanDataset.id.in_(ids))
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


def _apply(signal_key: str, layout: Layout, evidence: dict, confidence: float, run: AnalysisRun,
           actor: User, activate: bool) -> tuple[DecodeRule, str]:
    """후보 수식을 규칙으로 남긴다. 적용하면 기존 적용 규칙은 '이전 버전'이 된다."""
    rules = db.session.scalars(select(DecodeRule).where(DecodeRule.signal_key == signal_key)).all()
    same = next((r for r in rules if _layout(r) == layout), None)
    current = next((r for r in rules if r.status == RuleStatus.ACTIVE), None)

    if not activate:
        if same is None:
            same = DecodeRule(signal_key=signal_key, revision=_next_revision(signal_key),
                              status=RuleStatus.CANDIDATE, analysis_run_id=run.id, created_by=actor.id,
                              confidence=confidence, evidence=evidence, **_rule_fields(layout))
            db.session.add(same)
            db.session.flush()
            return same, "가설 저장"
        if same.status == RuleStatus.CANDIDATE:
            same.evidence, same.confidence = evidence, confidence
        return same, "보류"

    if current is not None:
        current.evidence, current.confidence = evidence, confidence
        return current, "유지"
    if same is None:
        same = DecodeRule(signal_key=signal_key, revision=_next_revision(signal_key), analysis_run_id=run.id,
                          created_by=actor.id, **_rule_fields(layout))
        db.session.add(same)
    same.status, same.activated_at, same.retired_at = RuleStatus.ACTIVE, _now(), None
    same.evidence, same.confidence = evidence, confidence
    db.session.flush()
    return same, "새로 적용"


def _overlaps(a: Layout, b: Layout) -> bool:
    return (a.request_id, a.did) == (b.request_id, b.did) and a.start < b.start + b.width and b.start < a.start + a.width


def _guard(signal_key: str, layout: Layout, active: dict[str, DecodeRule]) -> list[str]:
    """자동 적용을 막는 이유. 규칙은 모든 차량에 함께 쓰이므로 이미 적용된 수식은 사람이 바꾼다."""
    reasons = []
    current = active.get(signal_key)
    if current is not None and _layout(current) != layout:
        reasons.append(f"적용 중 수식(v{current.revision}: {current.formula})과 달라 자동으로 바꾸지 않았습니다. "
                       "규칙 화면에서 확인 후 적용하세요.")
    for key, rule in active.items():
        if key != signal_key and _overlaps(layout, _layout(rule)):
            label = signals.BY_KEY[key].label if key in signals.BY_KEY else key
            reasons.append(f"'{label}'에 적용 중인 바이트와 겹칩니다.")
            break
    return reasons


def run_analysis(actor: User, trace_ids: list[int], truth_dataset_id: int, apply: bool = True) -> AnalysisRun:
    """apply=False면 판정만 기록하고 규칙은 바꾸지 않는다(기록과 정답의 측정 시각이 다를 때)."""
    if not trace_ids:
        raise ServiceError("분석할 통신 기록을 하나 이상 고르세요.")
    truth_dataset = get_dataset(truth_dataset_id)
    truths = ground_truths(truth_dataset)
    if not truths:
        raise ServiceError("확인된 숫자 정답값이 없습니다. 정답값을 확인(체크)한 뒤 실행하세요.")
    started = time.perf_counter()
    samples = merged_samples(trace_ids)
    if not samples:
        raise ServiceError("고른 기록에 데이터 조회(0x22) 응답이 없습니다.")
    ranked = search(samples, truths)
    decisions = judge(truths, ranked, samples)

    run = AnalysisRun(trace_dataset_ids=trace_ids, truth_dataset_id=truth_dataset.id, created_by=actor.id,
                      created_at=_now(), result={})
    db.session.add(run)
    db.session.flush()

    active = {r.signal_key: r for r in db.session.scalars(
        select(DecodeRule).where(DecodeRule.status == RuleStatus.ACTIVE))}
    result, activated = {}, 0
    for truth in truths:
        decision = decisions[truth.signal_key]
        if decision.activate and (blocked := _guard(truth.signal_key, decision.candidate.layout, active)):
            decision.activate, decision.reasons = False, blocked
        signal = signals.BY_KEY[truth.signal_key]
        entry = {
            "label": signal.label, "unit": signal.unit, "truth": truth.value, "activate": decision.activate,
            "reasons": decision.reasons, "status": "UNKNOWN", "rule_id": None, "outcome": None,
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
            entry.update(status="확정" if decision.activate else "가설", decoded=best.decoded,
                         outcome="검증만(적용 안 함)")
            current = active.get(truth.signal_key)
            entry["matches_active"] = current is not None and _layout(current) == best.layout
            if apply:
                evidence = best.evidence(truth) | {"reasons": decision.reasons, "analysis_run_id": run.id}
                rule, outcome = _apply(truth.signal_key, best.layout, evidence, round(best.score, 3), run, actor,
                                       decision.activate)
                entry.update(rule_id=rule.id, outcome=outcome)
                if decision.activate and outcome != "유지":
                    activated += 1
        result[truth.signal_key] = entry

    run.result = result
    run.activated_count = activated
    run.duration_ms = int((time.perf_counter() - started) * 1000)
    audit.record("CAN 역산 실행", "AnalysisRun", run.id, user_id=actor.id,
                 changes={"traces": trace_ids, "truth_dataset": truth_dataset.id, "signals": len(truths),
                          "activated": activated, "apply": apply})
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


def capture_requests() -> list[dict]:
    """실시간 수집에서 보낼 요청. 적용 중 규칙이 쓰는 ECU·DID와 고장코드·VIN 조회."""
    pairs = sorted({(r.layout.request_id, r.layout.did) for r in active_rule_refs()})
    requests = [{"header": f"{req:03X}", "command": f"22{did:04X}"} for req, did in pairs]
    for header in sorted({f"{req:03X}" for req, _ in pairs}):
        requests.append({"header": header, "command": "1902FF"})
    if requests:
        requests.append({"header": requests[0]["header"], "command": "22F190"})
    return requests


def obd_config() -> dict:
    """웹 블루투스 연결·수집 화면 설정. 프로필이 없어도 알려진 진단기는 자동 감지로 연결한다."""
    profiles = [p for p in list_profiles() if p.enabled and p.transport == "ble"]
    requests, from_rules = capture_requests(), True
    if not requests:
        # 적용 규칙이 없을 때는 프로필의 조회 명령으로 기초데이터를 모은다.
        requests, from_rules = [{"header": p.request_header, "command": c} for p in profiles[:1]
                                if p.request_header for c in p.read_commands], False
    return {
        "profiles": [{"id": p.id, "name": p.name, "namePrefix": p.device_name_prefix, "service": p.service_uuid,
                      "write": p.write_uuid, "notify": p.notify_uuid, "init": p.init_commands,
                      "timeout": p.response_timeout_ms} for p in profiles],
        "requests": requests,
        "fromRules": from_rules,
        "saveUrl": url_for("canlab.live"),
        "previewUrl": url_for("canlab.live_preview"),
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

    dtcs = [d for codes in report.diagnosis.get("dtcs", {}).values() for d in codes]
    checked = report.diagnosis.get("dtc_checked_ecus", [])
    if dtcs:
        lines.append("4. 고장코드: " + ", ".join(d["code"] for d in dtcs[:10]) + " — 정비소 점검을 권장합니다.")
    elif checked:
        lines.append(f"4. 고장코드: 조회한 ECU {len(checked)}곳에서 고장코드가 없습니다.")
    else:
        lines.append("4. 고장코드: 이 기록에는 고장코드 조회가 없습니다.")
    low_confidence = [v["label"] for v in report.values.values() if v["confidence"] < 0.8]
    if low_confidence:
        lines.append("※ 신뢰도가 낮은 수식으로 읽은 항목: " + ", ".join(low_confidence))
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


def overview() -> dict:
    count = {
        "datasets": db.session.scalar(select(func.count(CanDataset.id))),
        "active_rules": db.session.scalar(select(func.count(DecodeRule.id))
                                          .where(DecodeRule.status == RuleStatus.ACTIVE)),
        "runs": db.session.scalar(select(func.count(AnalysisRun.id))),
        "reports": db.session.scalar(select(func.count(DiagnosticReport.id))),
    }
    return count | {"signals": len(signals.SIGNALS), "ai_ready": ai.available_connection() is not None}
