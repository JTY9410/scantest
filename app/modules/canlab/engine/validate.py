"""후보 수식의 자동 적용 여부 판정.

정답값 오차, 물리적 범위, 다른 해석과의 경합, 신호 사이 관계를 모두 통과해야 적용한다.
"""

from dataclasses import dataclass, field

from app.modules.canlab.engine import signals
from app.modules.canlab.engine.search import Candidate, GroundTruth, Samples

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
