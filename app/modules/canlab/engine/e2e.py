"""E2E·카운터 휴리스틱(표시·확정 억제용).

점수를 바꾸거나 후보를 삭제하지 않는다. CANLAB_COUNTER_WARN일 때만
카운터처럼 보이는 바이트를 쓰는 후보에 경고 사유를 붙인다.
"""

from __future__ import annotations

# 누적·시간처럼 실제로 +1씩 증가하는 신호는 경고 대상에서 뺀다.
SKIP_SIGNALS = frozenset({
    "operating_time_s",
    "cum_charge_ah", "cum_discharge_ah",
    "cum_charge_kwh", "cum_discharge_kwh",
})


def counter_bytes(payloads: list[bytes], *, threshold: float = 0.9) -> set[int]:
    """인접 표본에서 (다음−이전) mod 256 == 1 비율이 threshold 이상인 바이트 번호."""
    if len(payloads) < 8:
        return set()
    length = min(len(p) for p in payloads)
    out: set[int] = set()
    for index in range(length):
        column = [p[index] for p in payloads]
        hits = sum((b - a) % 256 == 1 for a, b in zip(column, column[1:]))
        if hits / (len(column) - 1) >= threshold:
            out.add(index)
    return out


def counter_bytes_for_samples(samples: dict, request_id: int, did: int) -> set[int]:
    rows = samples.get((request_id, did)) or []
    payloads = [data for _, data in rows]
    return counter_bytes(payloads)


def overlaps_counter(layout, counters: set[int]) -> bool:
    if not counters:
        return False
    if getattr(layout, "bit_length", 0):
        span = (layout.bit_offset + layout.bit_length + 7) // 8
        used = set(range(layout.start, layout.start + max(span, 1)))
    else:
        used = set(range(layout.start, layout.start + layout.width))
    return bool(used & counters)


def should_warn(signal_key: str) -> bool:
    return signal_key not in SKIP_SIGNALS
