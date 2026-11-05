"""명령 순서 리포트와 두 통신기록(위스캔 대 지스캔) 비교."""

from collections import Counter
from statistics import median

from app.modules.canlab.engine import uds

MAX_STEPS = 300


def _key(tx: uds.Transaction) -> tuple[str, str, str | None]:
    sub = None
    if tx.service == 0x22 and tx.did is not None:
        sub = f"{tx.did:04X}"
    elif len(tx.request) >= 2 and tx.service in (0x10, 0x19, 0x27, 0x09, 0x1A, 0x21, 0x3E, 0x01, 0x31):
        sub = f"{tx.request[1]:02X}"
    return f"{tx.request_id:03X}" if tx.request_id <= 0x7FF else f"{tx.request_id:08X}", f"{tx.service:02X}", sub


def _latency(tx: uds.Transaction) -> float | None:
    if tx.response_t_ms is None:
        return None
    return round(tx.response_t_ms - tx.t_ms, 1)


def command_sequence(transactions: list[uds.Transaction]) -> dict:
    """보낸 순서대로 (요청 ID, 서비스, DID·하위기능)을 묶는다. 연속으로 같은 명령은 한 단계로 센다."""
    steps: list[dict] = []
    counts: Counter = Counter()
    negatives: Counter = Counter()
    latencies: list[float] = []
    for tx in transactions:
        key = _key(tx)
        counts[key] += 1
        if tx.negative_code is not None:
            negatives[(key[0], key[1], f"{tx.negative_code:02X}")] += 1
        if (lat := _latency(tx)) is not None and tx.negative_code is None:
            latencies.append(lat)
        status = "positive" if tx.positive else ("negative" if tx.negative_code is not None else
                                                 ("silent_ok" if not tx.expects_response else "none"))
        if steps and steps[-1]["key"] == key:
            step = steps[-1]
            step["repeat"] += 1
            step[status] = step.get(status, 0) + 1
            continue
        if len(steps) >= MAX_STEPS:
            continue
        steps.append({"key": key, "t_s": round(tx.t_ms / 1000, 3), "request_id": key[0], "service": key[1],
                      "sub": key[2], "name": uds_name(tx.service), "repeat": 1, status: 1})
    for step in steps:
        step.pop("key")
    services = Counter(tx.service for tx in transactions)
    return {
        "steps": steps,
        "truncated": len(steps) >= MAX_STEPS,
        "total": len(transactions),
        "services": [{"service": f"{s:02X}", "name": uds_name(s), "count": n} for s, n in services.most_common()],
        "top": [{"request_id": k[0], "service": k[1], "sub": k[2], "count": n} for k, n in counts.most_common(15)],
        "negatives": [{"request_id": k[0], "service": k[1], "code": k[2],
                       "meaning": uds.NEGATIVE_CODES.get(int(k[2], 16), "기타"), "count": n}
                      for k, n in negatives.most_common(20)],
        "ecus": len({k[0] for k in counts}),
        "latency_ms": _stats(latencies),
    }


_NAMES = {0x01: "OBD 현재값", 0x03: "OBD DTC", 0x09: "OBD 차량정보", 0x10: "세션 전환", 0x14: "DTC 지우기",
          0x19: "DTC 읽기", 0x1A: "ECU 식별(KWP)", 0x21: "로컬ID 읽기(KWP)", 0x22: "DID 읽기", 0x27: "보안 접근",
          0x2E: "DID 쓰기", 0x31: "루틴", 0x3E: "세션 유지"}


def uds_name(service: int) -> str:
    return _NAMES.get(service, f"서비스 {service:02X}")


def _stats(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    return {"count": len(values), "median": round(median(ordered), 1), "max": round(ordered[-1], 1),
            "p90": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))], 1)}


def _first_positive(transactions: list[uds.Transaction]) -> dict:
    found: dict = {}
    for tx in transactions:
        if tx.service == 0x22 and tx.positive and tx.did is not None:
            found.setdefault((tx.request_id, tx.did), tx)
    return found


def compare_tools(a: list[uds.Transaction], b: list[uds.Transaction]) -> dict:
    """같은 차량의 두 기록(예: 위스캔 a, 지스캔 b)을 ECU·DID 커버리지, 응답 일치, 지연으로 비교한다.
    누적·시간 값처럼 몇 초 사이 변하는 바이트가 있어 '부분 일치'(길이 같고 90% 이상 같은 바이트)도 따로 센다."""
    ecus_a = {tx.request_id for tx in a if tx.response is not None}
    ecus_b = {tx.request_id for tx in b if tx.response is not None}
    dids_a, dids_b = _first_positive(a), _first_positive(b)
    rows = []
    for key in sorted(set(dids_a) & set(dids_b)):
        da, db_ = dids_a[key].data, dids_b[key].data
        same = sum(1 for x, y in zip(da, db_) if x == y)
        if da == db_:
            verdict = "일치"
        elif len(da) == len(db_) and len(da) and same / len(da) >= 0.9:
            verdict = "부분 일치"
        else:
            verdict = "불일치"
        rows.append({"request_id": f"{key[0]:03X}", "did": f"{key[1]:04X}", "verdict": verdict,
                     "length_a": len(da), "length_b": len(db_), "same_bytes": same,
                     "latency_a": _latency(dids_a[key]), "latency_b": _latency(dids_b[key])})
    fmt = lambda keys: sorted(f"{r:03X} {d:04X}" for r, d in keys)  # noqa: E731
    lat_a = [v for tx in a if tx.positive and (v := _latency(tx)) is not None]
    lat_b = [v for tx in b if tx.positive and (v := _latency(tx)) is not None]
    return {
        "ecus": {"a": len(ecus_a), "b": len(ecus_b), "common": len(ecus_a & ecus_b),
                 "only_a": sorted(f"{x:03X}" for x in ecus_a - ecus_b),
                 "only_b": sorted(f"{x:03X}" for x in ecus_b - ecus_a)},
        "dids": {"a": len(dids_a), "b": len(dids_b), "common": len(rows),
                 "only_a": fmt(set(dids_a) - set(dids_b)), "only_b": fmt(set(dids_b) - set(dids_a))},
        "rows": rows,
        "verdicts": dict(Counter(r["verdict"] for r in rows)),
        "latency_ms": {"a": _stats(lat_a), "b": _stats(lat_b)},
        "transactions": {"a": len(a), "b": len(b)},
    }
