"""활성 규칙으로 수집 데이터를 물리값으로 바꾸고 진단 결과를 모은다."""

from dataclasses import dataclass, field

from app.modules.canlab.engine import signals, uds
from app.modules.canlab.engine.frames import parse_trace
from app.modules.canlab.engine.isotp import reassemble
from app.modules.canlab.engine.search import Layout, Samples


@dataclass
class Trace:
    format: str
    frame_count: int
    skipped_lines: int
    transactions: list[uds.Transaction]
    samples: Samples
    meta: dict = field(default_factory=dict)


def load_trace(text: str) -> Trace:
    parsed = parse_trace(text)
    transactions = uds.pair_transactions(reassemble(parsed.frames))
    return Trace(parsed.format, len(parsed.frames), parsed.skipped_lines, transactions,
                 uds.did_samples(transactions), parsed.meta)


@dataclass(frozen=True)
class RuleRef:
    rule_id: int
    version: int
    signal_key: str
    layout: Layout
    confidence: float


def decode_signals(samples: Samples, rules: list[RuleRef]) -> dict[str, dict]:
    """신호마다 마지막 표본 값과 시간별 값 목록을 만든다. 물리 범위를 벗어나면 값으로 쓰지 않는다."""
    values = {}
    for rule in rules:
        rows = samples.get((rule.layout.request_id, rule.layout.did))
        if not rows:
            continue
        signal = signals.BY_KEY.get(rule.signal_key)
        series = []
        for t_ms, data in rows:
            value = rule.layout.value(data)
            if value is None or (signal and not signal.minimum <= value <= signal.maximum):
                continue
            series.append((round(t_ms, 1), value))
        if not series:
            continue
        values[rule.signal_key] = {
            "value": series[-1][1],
            "series": series,
            "label": signal.label if signal else rule.signal_key,
            "unit": signal.unit if signal else "",
            "rule_id": rule.rule_id,
            "rule_version": rule.version,
            "confidence": rule.confidence,
            "formula": rule.layout.formula(),
            "source": f"{rule.layout.request_id:03X} 22 {rule.layout.did:04X}",
        }
    return values


def diagnose(trace: Trace) -> dict:
    """DTC, VIN, 응답한 ECU와 DID 목록. 규칙이 없어도 얻을 수 있는 정보다."""
    dtcs: dict[str, list[dict]] = {}
    ecus: dict[str, dict] = {}
    for tx in trace.transactions:
        responder = tx.response_id or tx.request_id + 8
        entry = ecus.setdefault(f"{tx.request_id:03X}", {
            "request_id": f"{tx.request_id:03X}", "response_id": f"{responder:03X}",
            "label": uds.ecu_label(tx.request_id), "dids": [], "negative": [],
        })
        if tx.service == 0x19 and tx.positive:
            dtcs.setdefault(f"{tx.request_id:03X}", []).extend(uds.parse_dtcs(tx))
        if tx.service == 0x22 and tx.did is not None:
            did = f"{tx.did:04X}"
            if tx.positive and did not in entry["dids"]:
                entry["dids"].append(did)
            elif tx.negative_code is not None:
                entry["negative"].append({"did": did, "code": f"{tx.negative_code:02X}",
                                          "meaning": uds.NEGATIVE_CODES.get(tx.negative_code, "기타")})
    checked = [key for key, entry in ecus.items()
               if any(tx.service == 0x19 and tx.positive and f"{tx.request_id:03X}" == key
                      for tx in trace.transactions)]
    return {
        "vin": uds.mask_vin(uds.find_vin(trace.transactions)),
        "ecus": list(ecus.values()),
        "dtcs": dtcs,
        "dtc_checked_ecus": checked,
        "transaction_count": len(trace.transactions),
    }
