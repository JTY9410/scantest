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
    frames: list = field(default_factory=list)


def load_trace(text: str) -> Trace:
    parsed = parse_trace(text)
    can_frames = [frame for frame in parsed.frames if frame.direction != "serial"]
    transactions = uds.pair_transactions(reassemble(can_frames))
    return Trace(parsed.format, len(parsed.frames), parsed.skipped_lines, transactions,
                 uds.did_samples(transactions), parsed.meta, frames=list(parsed.frames))


@dataclass(frozen=True)
class RuleRef:
    rule_id: int
    version: int
    signal_key: str
    layout: Layout
    confidence: float


def decode_signals(samples: Samples, rules: list[RuleRef]) -> dict[str, dict]:
    """신호마다 마지막 표본 값과 시간별 값 목록을 만든다. 
    
    물리 범위를 벗어난 값은 '정의불일치'로 표시하고 추가 정보에 기록한다.
    """
    values = {}
    out_of_range = []  # 범위 밖 값 목록
    
    for rule in rules:
        rows = samples.get((rule.layout.request_id, rule.layout.did))
        if not rows:
            continue
        signal = signals.BY_KEY.get(rule.signal_key)
        series = []
        range_violations = []
        
        for t_ms, data in rows:
            value = rule.layout.value(data)
            if value is None:
                continue
            # 범위 체크
            if signal and not signal.minimum <= value <= signal.maximum:
                range_violations.append({
                    "value": value,
                    "expected_range": f"{signal.minimum} ~ {signal.maximum}",
                    "unit": signal.unit,
                })
                continue
            series.append((round(t_ms, 1), value))
        
        if range_violations:
            # 범위 밖 값 기록
            out_of_range.append({
                "signal": rule.signal_key,
                "label": signal.label if signal else rule.signal_key,
                "source": f"{rule.layout.request_id:03X} 22 {rule.layout.did:04X}",
                "violations": range_violations,
                "reason": "정의불일치 (범위 밖 값)",
            })
        
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
    
    # 범위 밖 값을 별도로 반환 (호출자가 처리)
    if out_of_range:
        values["_out_of_range_signals"] = out_of_range
    
    return values


def diagnose(trace: Trace) -> dict:
    """DTC, VIN, 응답한 ECU와 DID 목록. 규칙이 없어도 얻을 수 있는 정보다."""
    dtcs: dict[str, list[dict]] = {}
    ecus: dict[str, dict] = {}
    for tx in trace.transactions:
        responder = tx.response_id or tx.request_id + 8
        
        # 기능주소(7DF) 응답 시 ECU 물리주소로 별도 등록
        if tx.ecu_physical_id is not None:
            ecu_key = f"{tx.ecu_physical_id:03X}"
            entry = ecus.setdefault(ecu_key, {
                "request_id": ecu_key, "response_id": f"{tx.response_id:03X}" if tx.response_id else ecu_key,
                "label": uds.ecu_label(tx.ecu_physical_id), "dids": [], "negative": [],
            })
        else:
            entry = ecus.setdefault(f"{tx.request_id:03X}", {
                "request_id": f"{tx.request_id:03X}", "response_id": f"{responder:03X}",
                "label": uds.ecu_label(tx.request_id), "dids": [], "negative": [],
            })
        
        # 브로드캐스트의 추가 응답자(extra_responders)도 ECU로 등록
        for extra_id in tx.extra_responders:
            if 0x500 <= extra_id <= 0x7FF:
                extra_key = f"{extra_id:03X}"
                ecus.setdefault(extra_key, {
                    "request_id": extra_key, "response_id": extra_key,
                    "label": uds.ecu_label(extra_id), "dids": [], "negative": [],
                })
        
        if tx.service == 0x19 and tx.positive:
            dtc_key = f"{tx.ecu_physical_id:03X}" if tx.ecu_physical_id else f"{tx.request_id:03X}"
            dtcs.setdefault(dtc_key, []).extend(uds.parse_dtcs(tx))
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
    result = {
        "vin": uds.mask_vin(uds.find_vin(trace.transactions)),
        "ecus": list(ecus.values()),
        "dtcs": dtcs,
        "dtc_checked_ecus": checked,
        "transaction_count": len(trace.transactions),
        "silent_ok": sum(
            1 for tx in trace.transactions
            if not tx.expects_response and tx.response is None and tx.negative_code is None
        ),
    }
    try:
        from app.modules.canlab.engine.byd_atto3 import decode as decode_atto3

        if atto3 := decode_atto3(getattr(trace, "frames", None), trace.transactions):
            result["atto3"] = atto3
    except Exception:
        pass
    try:
        from app.modules.scanner.security.status import analyze_security_trace
        result["security"] = analyze_security_trace(trace.transactions)
    except Exception:
        pass
    try:
        from app.modules.canlab.engine.features import flag
        if flag("CANLAB_BROADCAST_ANALYSIS") and getattr(trace, "frames", None):
            from app.modules.canlab.engine import broadcast as broadcast_mod
            result["broadcast"] = broadcast_mod.analyze_frames(trace.frames)
    except Exception:
        pass
    return result
