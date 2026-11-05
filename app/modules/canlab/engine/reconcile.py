"""완료 데이터 대조: 위스캔 통신기록(실측)과 리버스데이터(같은 차량의 지스캔 통신기록)만으로 최종값을 정한다.

정답값(위스캔 결과지)이 없으므로 규칙을 찾거나 바꾸지 않는다. 신호마다 정의 하나를 골라
같은 정의로 양쪽 응답을 해석해 비교한다.

정의 우선순위: 적용 중 디코딩 규칙(rule) > 검증된 BMS 해석(bms) > 정의표(table, 선택 입력) > 참고자료(reference).
항목 판정: 일치 / 불일치 / 위스캔에만(리버스 응답 없음) / 정의만(위스캔 응답 없음, 리버스 값은 참고) / 경합.
신뢰등급: 확인됨 / 유력 / 미확인. 최종값은 위스캔 실측이며 확인됨·유력만 보고서 판정에 쓴다.
"""

import difflib
import hashlib
from dataclasses import dataclass
from typing import Any, Callable

from app.modules.canlab.engine import bms, signals, uds
from app.modules.canlab.engine.decode import Trace, diagnose
from app.modules.canlab.engine.search import Layout

CONFIRMED, LIKELY, UNKNOWN = bms.CONFIRMED, bms.LIKELY, bms.UNKNOWN
MATCH, MISMATCH, WESCAN_ONLY, DEFINITION_ONLY, CONFLICT = "일치", "불일치", "위스캔에만", "정의만", "경합"
SOURCE_LABELS = {"rule": "적용 중 디코딩 규칙", "bms": "검증된 BMS 해석", "table": "정의표", "reference": "참고자료"}
_RANK = {"rule": 0, "bms": 1, "table": 2, "reference": 3}

# 허용오차(대조방식_계획 3.1). 절대값 또는 비율(rel). 누적 카운터는 단조 증가 규칙.
# [확인 필요] 절연저항·전압·전류 허용오차는 제안값이다.
_ABS = {"soh": 0.1, "soc": 0.5, "soc_display": 0.5, "max_temp": 1, "min_temp": 1, "inlet_temp": 1,
        "max_cell_v": 0.02, "min_cell_v": 0.02, "pack_current": 2, "aux_voltage": 0.2,
        "max_cell_no": 0, "min_cell_no": 0}
_REL = {"pack_voltage": 0.005, "isolation_kohm": 0.01}
COUNTERS = {"cum_charge_ah", "cum_discharge_ah", "cum_charge_kwh", "cum_discharge_kwh", "operating_time_s"}
# 위치 번호·상태 비트처럼 값이 자주 바뀌는 항목은 리버스 범위 안이면 일치로 본다.
_DRIFT = {"pack_current", "pack_voltage", "max_cell_no", "min_cell_no", "status_bits", "soc", "soc_display",
          "max_charge_power_kw", "max_discharge_power_kw", "aux_voltage", "max_cell_v", "min_cell_v"}

# 유형별 필수 명령(헤더, 요청 접두). [확인 필요] 차종별 위스캔 기록으로 확정해야 한다.
REQUIRED = {
    "ev": (("7E4", "220101"), ("7E4", "220105"), ("*", "1902")),
    "hev": (("7E4", "220101"), ("7E0", "1902")),
    "ice": (("7E0", "1902"),),
}


@dataclass
class Definition:
    key: str
    label: str
    unit: str
    request_id: int
    did: int
    decode: Callable[[bytes], float | None]
    source: str
    grade: str
    formula: str
    note: str = ""


def vin_hash(vin: str | None) -> str | None:
    return hashlib.sha256(vin.encode()).hexdigest()[:12] if vin else None


def tolerance(key: str, value: float) -> float:
    if key in _ABS:
        return _ABS[key]
    if key in _REL:
        return max(abs(value) * _REL[key], 5 if key == "isolation_kohm" else 0.1)
    if key.startswith("module_temp_"):
        return 1
    return max(abs(value) * 0.01, 0.01)


def _layout_def(key: str, layout: Layout, source: str, grade: str, label: str | None = None,
                unit: str | None = None) -> Definition:
    signal = signals.BY_KEY.get(key)
    return Definition(key, label or (signal.label if signal else key), unit if unit is not None else
                      (signal.unit if signal else ""), layout.request_id, layout.did, layout.value, source, grade,
                      layout.formula())


def bms_definitions(platform: str) -> list[Definition]:
    """engine/bms.py의 검증된 해석(BMS 바이트 검증)을 정의로 쓴다."""
    out = []
    fields = list(bms.FIELDS)
    if platform in ("egmp", "niro", "porter"):
        fields += [f for f in bms.EGMP_EXTRA if not (f.did == 0x0105 and platform == "porter")]
    for f in fields:
        out.append(Definition(f.key, f.label, f.unit, bms.BMS_REQUEST, f.did, f.value, "bms", f.grade,
                              f"{f.did:04X}[{f.start}:{f.start + f.width}]×{f.scale}", f.note))

    def soh(data: bytes) -> float | None:
        if len(data) < 27:
            return None
        raw = int.from_bytes(data[25:27], "big") * 0.1
        return round(raw, 1) if 0 < raw <= 110 else None

    out.append(Definition("soh", "SOH(BMS 산출)", "%", bms.BMS_REQUEST, 0x0105, soh, "bms",
                          CONFIRMED if platform in ("egmp", "niro", "hkmc_ev_gen1") else LIKELY,
                          "0105[25:27]×0.1"))

    def inlet(data: bytes) -> float | None:
        if len(data) <= 22:
            return None
        temps = {"max_temp": int.from_bytes(data[14:15], "big", signed=True),
                 "min_temp": int.from_bytes(data[15:16], "big", signed=True)}
        return bms.inlet_temp(data[22], platform, temps)[0]

    inlet_grade = {"egmp": CONFIRMED, "hkmc_ev_gen1": CONFIRMED}.get(
        platform, LIKELY if platform in ("niro", "porter", "hev") else UNKNOWN)
    out.append(Definition("inlet_temp", "배터리 입구(냉각수) 온도", "°C", bms.BMS_REQUEST, 0x0101, inlet, "bms",
                          inlet_grade, "0101[22] 차종별 오프셋"))
    return out


def parse_table(text: str) -> list[Definition]:
    """정의표 CSV: signal_key,header,did,start,width[,endian,signed,scale,offset,unit,label]. 첫 줄은 머리글."""
    import csv
    import io

    rows = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
    out = []
    for n, row in enumerate(rows, 2):
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        try:
            layout = Layout(int(row["header"], 16), int(row["did"], 16), int(row["start"]), int(row["width"]),
                            row.get("endian") or "big", (row.get("signed") or "").lower() in ("1", "true", "y", "yes"),
                            float(row.get("scale") or 1), float(row.get("offset") or 0))
            key = row["signal_key"]
        except (KeyError, ValueError) as error:
            raise ValueError(f"정의표 {n}행을 읽지 못했습니다: {error}") from error
        if not key:
            raise ValueError(f"정의표 {n}행에 signal_key가 없습니다.")
        out.append(_layout_def(key, layout, "table", LIKELY, row.get("label") or None,
                               row.get("unit") if row.get("unit") else None))
    return out


def _values(defn: Definition, rows) -> list[float]:
    out = []
    for _, payload in rows or []:
        try:
            value = defn.decode(payload)
        except (IndexError, ValueError):
            value = None
        if value is not None:
            out.append(value)
    return out


def _in_range(key: str, value: float) -> bool:
    signal = signals.BY_KEY.get(key)
    return signal is None or signal.minimum <= value <= signal.maximum


def _compare(key: str, ours: float, theirs: list[float]) -> tuple[str, str]:
    lo, hi, last = min(theirs), max(theirs), theirs[-1]
    tol = tolerance(key, ours)
    if key in COUNTERS:
        # 위스캔이 나중에 찍힌다(지스캔 먼저). 누적값은 줄어들 수 없다.
        if ours + tol >= hi:
            return MATCH, "누적값 정상 증가" if ours > hi else "누적값 같음"
        return MISMATCH, f"누적값이 리버스({hi})보다 작음"
    if key in _DRIFT or key.startswith("module_temp_"):
        if lo - tol <= ours <= hi + tol:
            return MATCH, "리버스 범위 안" if lo != hi else ""
        return MISMATCH, f"리버스 범위 {lo}~{hi} 밖(허용 ±{tol:g})"
    if abs(ours - last) <= tol:
        return MATCH, ""
    return MISMATCH, f"차이 {round(ours - last, 4)} (허용 ±{tol:g})"


def _grade(base: str, status: str) -> str:
    if base == UNKNOWN or status in (MISMATCH, CONFLICT, DEFINITION_ONLY):
        return UNKNOWN
    if status == MATCH:
        return base
    return LIKELY if base == CONFIRMED else UNKNOWN  # 위스캔에만: 리버스로 검증하지 못했다


def _commands(trace: Trace) -> list[tuple[str, str]]:
    out = []
    for tx in trace.transactions:
        key = (f"{tx.request_id:03X}", tx.request.hex().upper())
        if not out or out[-1] != key:
            out.append(key)
    return out


def coverage(kind: str, ours: list[tuple[str, str]], theirs: list[tuple[str, str]]) -> dict:
    def has(commands, header, prefix):
        return any((header == "*" or h == header) and c.startswith(prefix) for h, c in commands)

    rows = [{"header": h, "command": p, "wescan": has(ours, h, p), "reverse": has(theirs, h, p)}
            for h, p in REQUIRED.get(kind, ())]
    both = sum(1 for r in rows if r["wescan"] and r["reverse"])
    common = set(ours) & set(theirs)
    seq_ours = [c for c in ours if c in common]
    seq_theirs = [c for c in theirs if c in common]
    ratio = difflib.SequenceMatcher(None, seq_ours, seq_theirs, autojunk=False).ratio() if common else 0.0
    return {"required": rows, "required_ratio": round(both / len(rows), 3) if rows else 1.0,
            "common": len(common), "wescan_commands": len(set(ours)), "reverse_commands": len(set(theirs)),
            "common_ratio": round(len(common) / len(set(ours)), 3) if ours else 0.0,
            "sequence_ratio": round(ratio, 3)}


def _dtcs(trace: Trace) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for ecu, rows in diagnose(trace)["dtcs"].items():
        out.setdefault(ecu, set()).update(r.get("code") for r in rows if r.get("code"))
    return out


def reconcile(wescan: Trace, reverse: list[Trace], *, kind: str, model_hint: str | None,
              rules: dict[str, Layout] | None = None, table: list[Definition] | None = None,
              references: dict | None = None) -> dict:
    """대조 결과(JSON). VIN 원문은 넣지 않는다(앞 11자리 마스킹 + 해시)."""
    ours = wescan.samples
    theirs: dict = {}
    for trace in reverse:
        for key, rows in trace.samples.items():
            theirs.setdefault(key, []).extend(rows)
    vin_w = uds.find_vin(wescan.transactions)
    vin_r = next((v for t in reverse if (v := uds.find_vin(t.transactions))), None)
    vin = {"wescan": uds.mask_vin(vin_w), "reverse": uds.mask_vin(vin_r),
           "wescan_hash": vin_hash(vin_w), "reverse_hash": vin_hash(vin_r),
           "status": ("일치" if vin_w and vin_r and vin_w == vin_r else
                      "불일치" if vin_w and vin_r else "없음")}

    cell = bms.cells(ours)
    detail = cell_detail(ours)
    platform = bms.platform(model_hint, cell["count"] if cell else None)
    definitions: list[Definition] = []
    definitions += [_layout_def(key, layout, "rule", CONFIRMED) for key, layout in (rules or {}).items()]
    definitions += bms_definitions(platform)
    definitions += table or []
    by_key: dict[str, list[Definition]] = {}
    for d in definitions:
        by_key.setdefault(d.key, []).append(d)
    keys_defined = set(by_key)
    for (key, layout), sources in (references or {}).items():
        if key in keys_defined or (layout.request_id, layout.did) not in ours and (
                layout.request_id, layout.did) not in theirs:
            continue
        d = _layout_def(key, layout, "reference", LIKELY)
        d.note = ", ".join(sources[:2])
        by_key.setdefault(key, []).append(d)

    items = []
    used_keys: set[tuple[int, int]] = set()
    for key, defs in by_key.items():
        defs.sort(key=lambda d: _RANK[d.source])
        best = defs[0]
        rivals = []
        if best.source == "reference":
            # 참고자료 정의가 여럿이면 위스캔 값이 같은지 본다. 다르면 경합.
            candidates = [(d, _values(d, ours.get((d.request_id, d.did)))) for d in defs if d.source == "reference"]
            candidates = [(d, v) for d, v in candidates if v and _in_range(key, v[-1])] or \
                         [(d, _values(d, theirs.get((d.request_id, d.did)))) for d in defs]
            if candidates:
                best = candidates[0][0]
                rivals = [d.formula for d, v in candidates[1:]
                          if v and candidates[0][1] and abs(v[-1] - candidates[0][1][-1]) > tolerance(key, v[-1])]
        w_rows = ours.get((best.request_id, best.did))
        r_rows = theirs.get((best.request_id, best.did))
        w_vals = [v for v in _values(best, w_rows) if _in_range(key, v)]
        r_vals = [v for v in _values(best, r_rows) if _in_range(key, v)]
        if not w_vals and not r_vals:
            continue
        used_keys.add((best.request_id, best.did))
        note = best.note
        if w_vals and r_vals:
            status, note2 = _compare(key, w_vals[-1], r_vals)
            note = "; ".join(x for x in (note2, note) if x)
        elif w_vals:
            status = WESCAN_ONLY
        else:
            status = DEFINITION_ONLY
        if rivals:
            status, note = CONFLICT, f"다른 참고 정의와 값이 다름({', '.join(rivals[:2])})"
        items.append({
            "key": key, "label": best.label, "unit": best.unit, "source": best.source,
            "source_label": SOURCE_LABELS[best.source], "formula": best.formula,
            "header": f"{best.request_id:03X}", "did": f"{best.did:04X}",
            "wescan": w_vals[-1] if w_vals else None,
            "reverse": ({"last": r_vals[-1], "min": min(r_vals), "max": max(r_vals), "n": len(r_vals)}
                        if r_vals else None),
            "status": status, "grade": _grade(best.grade, status), "base_grade": best.grade, "note": note,
        })
    order = {s.key: i for i, s in enumerate(signals.SIGNALS)}
    items.sort(key=lambda i: (order.get(i["key"], 999), i["key"]))

    measured_only = []
    for (req, did), rows in sorted(ours.items()):
        if (req, did) in used_keys or any((d.request_id, d.did) == (req, did) for defs in by_key.values()
                                          for d in defs):
            continue
        measured_only.append({"header": f"{req:03X}", "did": f"{did:04X}", "raw": rows[-1][1][:24].hex(" ").upper(),
                              "in_reverse": (req, did) in theirs})

    dtc_w, dtc_r = _dtcs(wescan), {}
    for trace in reverse:
        for ecu, codes in _dtcs(trace).items():
            dtc_r.setdefault(ecu, set()).update(codes)
    w_all = {(e, c) for e, codes in dtc_w.items() for c in codes}
    r_all = {(e, c) for e, codes in dtc_r.items() for c in codes}
    w_checked = set(diagnose(wescan)["dtc_checked_ecus"])
    dtc = {
        "final": [{"ecu": e, "code": c, "in_reverse": (e, c) in r_all} for e, c in sorted(w_all)],
        "reverse_only": [{"ecu": e, "code": c} for e, c in sorted(r_all - w_all)],
        "checked_ecus": sorted(w_checked),
    }

    counts: dict[str, int] = {}
    grades: dict[str, int] = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
        grades[item["grade"]] = grades.get(item["grade"], 0) + 1
    return {
        "kind": kind, "platform": platform, "vin": vin,
        "coverage": coverage(kind, _commands(wescan), [c for t in reverse for c in _commands(t)]),
        "items": items, "measured_only": measured_only, "dtc": dtc,
        "cells": detail, "counts": counts, "grades": grades,
    }


def cell_detail(samples: dict) -> dict | None:
    """셀별 전압(위스캔 실측). engine/bms.cells와 같은 PID·배율로 셀 번호를 붙인다. 결과 화면 형식(interpret)과 같다."""
    voltages = []
    for did in bms.CELL_PIDS:
        rows = samples.get((bms.BMS_REQUEST, did))
        if rows:
            voltages += [round(raw * bms.CELL_SCALE, 3) for raw in rows[-1][1][4:36]
                         if raw >= bms.CELL_MIN_RAW and raw != 0xFF]
    if not voltages:
        return None
    return {"values": [{"no": n, "voltage": v} for n, v in enumerate(voltages, 1)], "count": len(voltages),
            "min": min(voltages), "max": max(voltages), "spread_mv": round((max(voltages) - min(voltages)) * 1000),
            "sum": round(sum(voltages), 1), "range": None, "outliers": [], "origin": "BMS 셀 전압 PID",
            "grade": CONFIRMED}


def final_values(result: dict) -> dict[str, dict[str, Any]]:
    """보고서 판정에 쓸 값(확인됨·유력). 미확인은 빼서 해당 판정 항목이 '측정불가'(→ 판정보류)가 되게 한다."""
    return {item["key"]: {"label": item["label"], "value": item["wescan"], "unit": item["unit"],
                          "grade": item["grade"], "source": "reconcile", "origin": item["source_label"],
                          "reference": False, "outlier": False}
            for item in result["items"] if item["wescan"] is not None and item["grade"] in (CONFIRMED, LIKELY)}
