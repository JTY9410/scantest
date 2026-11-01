"""후보 수식의 자동 적용 여부 판정.

정답값 오차, 물리적 범위, 다른 해석과의 경합, 신호 사이 관계를 모두 통과해야 적용한다.
"""

from dataclasses import dataclass, field

from app.modules.canlab.engine import e2e, signals
from app.modules.canlab.engine.features import flag
from app.modules.canlab.engine.search import Candidate, GroundTruth, Layout, Samples

MIN_SCORE = 0.6
PAIRS = (("min_temp", "max_temp"), ("min_cell_v", "max_cell_v"))


@dataclass
class Decision:
    signal_key: str
    candidate: Candidate | None
    activate: bool
    reasons: list[str] = field(default_factory=list)


def _decoded_series(candidate: Candidate, samples: Samples) -> list[float]:
    rows = samples.get((candidate.layout.request_id, candidate.layout.did), [])
    return [v for _, data in rows if (v := candidate.layout.value(data)) is not None]


def endian_evidence(best: Candidate, rivals: list[Candidate], samples: Samples) -> str | None:
    """같은 바이트 범위에서 엔디안·부호만 다른 후보가 있을 때 표본 근거 문장."""
    if best.layout.width <= 1 and not best.layout.bit_length:
        return None
    alts = [
        c for c in rivals
        if c is not best
        and c.layout.request_id == best.layout.request_id
        and c.layout.did == best.layout.did
        and c.layout.start == best.layout.start
        and c.layout.width == best.layout.width
        and (c.layout.endian != best.layout.endian or c.layout.signed != best.layout.signed)
    ]
    if not alts:
        return None
    rows = samples.get((best.layout.request_id, best.layout.did)) or []
    if len(rows) < 2:
        return "엔디안·부호 후보가 여럿이나 표본이 부족합니다(추가 표본 필요)."
    payloads = [data for _, data in rows]
    start, width, endian = best.layout.start, best.layout.width, best.layout.endian
    if width >= 2:
        high = start if endian == "big" else start + width - 1
        low = start + width - 1 if endian == "big" else start
        high_span = max(p[high] for p in payloads if len(p) > high) - min(
            p[high] for p in payloads if len(p) > high
        )
        low_span = max(p[low] for p in payloads if len(p) > low) - min(
            p[low] for p in payloads if len(p) > low
        )
        order = "빅엔디언" if endian == "big" else "리틀엔디언"
        if high_span >= low_span:
            return (f"표본에서 상위 바이트(b{high}) 변화폭({high_span})이 "
                    f"하위(b{low}, {low_span}) 이상이라 {order} 해석을 우선합니다.")
        return (f"표본에서 하위 바이트(b{low}) 변화폭({low_span})이 "
                f"상위(b{high}, {high_span})보다 커 엔디안 확정에 추가 표본이 필요합니다.")
    if best.layout.signed:
        return "부호 비트를 쓰는 해석입니다(음수 표본 또는 참고자료)."
    return None


def _counter_warning(signal_key: str, layout: Layout, samples: Samples) -> str | None:
    if not flag("CANLAB_COUNTER_WARN") or not e2e.should_warn(signal_key):
        return None
    counters = e2e.counter_bytes_for_samples(samples, layout.request_id, layout.did)
    if e2e.overlaps_counter(layout, counters):
        used = sorted(
            set(range(layout.start, layout.start + max(layout.width, 1))) & counters
        )
        return (f"카운터처럼 보이는 바이트({', '.join(f'b{i}' for i in used)})를 "
                "포함합니다(가설, 확정하지 않음).")
    return None


def decide(truth: GroundTruth, candidates: list[Candidate], samples: Samples) -> Decision:
    if truth.value == 0:
        return Decision(truth.signal_key, None, False, ["정답값이 0이라 바이트를 구별할 수 없습니다(UNKNOWN)."])
    if not candidates:
        return Decision(truth.signal_key, None, False, ["허용 오차 안에서 맞는 바이트가 없습니다(UNKNOWN)."])
    best = candidates[0]
    reasons = []
    if best.conflict:
        reasons.append("다른 신호가 먼저 확정한 바이트와 겹칩니다.")
    signal = signals.BY_KEY[truth.signal_key]
    series = _decoded_series(best, samples)
    outside = [v for v in series if not signal.minimum <= v <= signal.maximum]
    if outside:
        reasons.append(f"물리 범위({signal.minimum:g}~{signal.maximum:g}{signal.unit})를 벗어난 값이 "
                       f"{len(outside)}개 있습니다.")
    if best.rivals and not best.references:
        reasons.append(f"같은 점수의 다른 해석이 {best.rivals}개 있어 하나로 정할 수 없습니다(가설).")
    if best.score < MIN_SCORE:
        reasons.append(f"신뢰 점수 {best.score:.2f}가 기준 {MIN_SCORE}보다 낮습니다.")
    if warn := _counter_warning(truth.signal_key, best.layout, samples):
        reasons.append(warn)
    if flag("CANLAB_ENDIAN_EVIDENCE"):
        note = endian_evidence(best, candidates, samples)
        if note:
            # 근거 문장은 정보용이다. '추가 표본 필요'만 확정을 막는다.
            if "추가 표본" in note:
                reasons.append(note)
            else:
                # 확정 여부와 무관하게 남기되, 다른 사유가 없을 때는 성공 메시지에 합친다.
                if reasons:
                    reasons.append(note)
                else:
                    return Decision(
                        truth.signal_key, best, True,
                        ["정답값과 일치하고 모든 검증을 통과했습니다.", note],
                    )
    return Decision(truth.signal_key, best, not reasons, reasons or ["정답값과 일치하고 모든 검증을 통과했습니다."])


def cross_check(decisions: dict[str, Decision], samples: Samples) -> None:
    """최소·최대 짝, 팩 전압과 셀 전압의 관계를 확인해 어긋나면 둘 다 보류한다."""
    for low_key, high_key in PAIRS:
        low, high = decisions.get(low_key), decisions.get(high_key)
        if not (low and high and low.activate and high.activate):
            continue
        lows = _decoded_series(low.candidate, samples)
        highs = _decoded_series(high.candidate, samples)
        if any(a > b for a, b in zip(lows, highs)):
            for decision in (low, high):
                decision.activate = False
                decision.reasons.append("최솟값이 최댓값보다 큰 표본이 있습니다.")

    pack, cell = decisions.get("pack_voltage"), decisions.get("max_cell_v")
    if pack and cell and pack.activate and cell.activate and cell.candidate.decoded:
        series_count = pack.candidate.decoded / cell.candidate.decoded
        if not 20 <= series_count <= 250:
            pack.activate = False
            pack.reasons.append(f"팩 전압/셀 전압 비({series_count:.0f})가 직렬 셀 수로 맞지 않습니다.")


def judge(truths: list[GroundTruth], ranked: dict[str, list[Candidate]], samples: Samples) -> dict[str, Decision]:
    decisions = {t.signal_key: decide(t, ranked.get(t.signal_key, []), samples) for t in truths}
    cross_check(decisions, samples)
    return decisions
