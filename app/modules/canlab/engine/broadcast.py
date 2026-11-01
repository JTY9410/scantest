"""방송(주기) CAN 로그 변화 감지·분석 (읽기 전용, 오프라인).

실제 차량 C-CAN 방송이 없어도, 같은 ID가 일정 주기로 반복되는 프레임
(진단 폴링 응답 포함)에 대해 주기·바이트 변화·카운터 후보를 요약한다.
CANLAB_BROADCAST_ANALYSIS 플래그가 켜져 있을 때만 diagnose() 결과에 붙는다.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Iterable

from app.modules.canlab.engine import e2e
from app.modules.canlab.engine.frames import Frame

# UDS/OBD 진단·기능주소·보안 관측 ID (방송 후보에서 구분)
_DIAG_11 = set(range(0x7E0, 0x7F0)) | {0x7DF}
_DIAG_29_PREFIX = 0x18DA
_SECURITY_ISH = set(range(0x5D0, 0x5E0))


def _is_diagnostic(can_id: int) -> bool:
    if can_id in _DIAG_11 or can_id in _SECURITY_ISH:
        return True
    if can_id == 0x18DB33F1:
        return True
    if (can_id >> 16) == _DIAG_29_PREFIX:
        return True
    # 흔한 진단 응답 대역 7E8-7EF already in range; 또한 7xx 단일 폴링 응답은 애매 → 주기성으로만 판단
    return False


def _period_ms(times: list[float]) -> float | None:
    if len(times) < 3:
        return None
    dts = [times[i] - times[i - 1] for i in range(1, len(times)) if times[i] >= times[i - 1]]
    if len(dts) < 2:
        return None
    return round(statistics.median(dts), 3)


def _byte_activity(payloads: list[bytes]) -> list[dict]:
    if not payloads:
        return []
    width = min(len(p) for p in payloads)
    rows = []
    for index in range(width):
        column = [p[index] for p in payloads]
        uniq = sorted(set(column))
        changes = sum(1 for a, b in zip(column, column[1:]) if a != b)
        rows.append({
            "byte": index,
            "unique": len(uniq),
            "changes": changes,
            "min": uniq[0],
            "max": uniq[-1],
        })
    return rows


def _stable_period(times: list[float], period: float | None, *, tol: float = 0.25) -> bool:
    if period is None or period <= 0 or len(times) < 4:
        return False
    dts = [times[i] - times[i - 1] for i in range(1, len(times))]
    if not dts:
        return False
    ok = sum(1 for d in dts if abs(d - period) <= max(1.0, tol * period))
    return ok / len(dts) >= 0.7


def analyze_id(can_id: int, frames: list[Frame]) -> dict:
    times = [f.t_ms for f in frames]
    payloads = [f.data for f in frames]
    period = _period_ms(times)
    counters = sorted(e2e.counter_bytes(payloads)) if len(payloads) >= 8 else []
    activity = _byte_activity(payloads)
    changing = [a for a in activity if a["changes"] > 0]
    static_bytes = [a["byte"] for a in activity if a["changes"] == 0]
    diag = _is_diagnostic(can_id)
    periodic = _stable_period(times, period)
    kind = "diagnostic_poll" if diag else ("periodic_candidate" if periodic else "sparse")
    return {
        "id": f"{can_id:X}",
        "count": len(frames),
        "unique_payloads": len(set(payloads)),
        "period_ms": period,
        "periodic": periodic,
        "kind": kind,
        "diagnostic": diag,
        "counter_bytes": counters,
        "changing_bytes": [a["byte"] for a in changing],
        "static_bytes": static_bytes,
        "byte_activity": activity,
        "t_first_ms": round(times[0], 3) if times else None,
        "t_last_ms": round(times[-1], 3) if times else None,
    }


def compare_windows(frames: list[Frame], *, split_ratio: float = 0.5) -> list[dict]:
    """같은 ID의 앞·뒤 구간 페이로드 집합 차이를 보고한다."""
    by_id: dict[int, list[Frame]] = defaultdict(list)
    for frame in frames:
        by_id[frame.can_id].append(frame)
    diffs = []
    for can_id, rows in sorted(by_id.items()):
        if len(rows) < 6:
            continue
        cut = max(2, int(len(rows) * split_ratio))
        left = {f.data for f in rows[:cut]}
        right = {f.data for f in rows[cut:]}
        only_left = len(left - right)
        only_right = len(right - left)
        if only_left or only_right:
            diffs.append({
                "id": f"{can_id:X}",
                "only_first_half": only_left,
                "only_second_half": only_right,
                "shared": len(left & right),
            })
    return diffs


def analyze_frames(frames: Iterable[Frame], *, min_count: int = 3) -> dict:
    """프레임 목록에서 ID별 주기·변화 요약. 방송이 없으면 limitation을 명시한다."""
    by_id: dict[int, list[Frame]] = defaultdict(list)
    for frame in frames:
        if frame.direction == "serial":
            continue
        by_id[frame.can_id].append(frame)

    ids = [analyze_id(cid, rows) for cid, rows in sorted(by_id.items()) if len(rows) >= min_count]
    periodic = [row for row in ids if row["periodic"]]
    broadcast_like = [row for row in periodic if not row["diagnostic"]]
    window_changes = compare_windows([f for rows in by_id.values() for f in rows])

    limitations = []
    if not broadcast_like:
        limitations.append(
            "트레이스에 진단·보안이 아닌 안정 주기 방송 ID가 거의 없습니다. "
            "차량 C-CAN 방송 로그가 아니라 진단 폴링 로그일 가능성이 큽니다."
        )
    if not ids:
        limitations.append("분석할 만큼 반복된 CAN ID가 없습니다.")

    return {
        "frame_count": sum(len(v) for v in by_id.values()),
        "id_count": len(by_id),
        "ids": ids,
        "periodic_ids": [r["id"] for r in periodic],
        "broadcast_candidate_ids": [r["id"] for r in broadcast_like],
        "window_changes": window_changes,
        "limitations": limitations,
    }


def analyze_trace_text(text: str) -> dict:
    from app.modules.canlab.engine.frames import parse_trace
    parsed = parse_trace(text)
    return analyze_frames(parsed.frames)
