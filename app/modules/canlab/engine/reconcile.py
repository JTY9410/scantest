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

# 허용오차·필수 명령: 2026-11-05 실데이터 산출(docs/flows/reconcile_tolerances.md에 표본 수·분포).
#  - 반복 측정 잡음: 바탕화면 실차 로그 22개 중 BMS 응답이 있는 10개(표본 587)의 연속 표본 차이·범위
#  - 위스캔·지스캔 쌍: 같은 차량 3쌍(시차 200~317초, 0101 누적 작동 시간 차로 계산)의 최종값 차이
# mode: point(마지막 값 비교) · range(리버스 최소~최대 ± 허용) · counter(감소 불가, 증가는 시차 비례 상한)
#       · info(동률 셀 사이에서 바뀌는 위치 번호 — 판정에 쓰지 않고 항상 일치로 본다)
# 운영에서 바꿀 때는 RECONCILE_TOLERANCES(JSON, 키별 일부만)로 덮어쓴다.
DEFAULT_TOLERANCES: dict[str, dict] = {
    "soh": {"mode": "point", "abs": 0.1},                   # 잡음 0(318), 쌍 차이 0 → 표시 분해능 0.1
    "soc": {"mode": "range", "abs": 0.5},                   # 범위 최대 0.5, 쌍 0
    "soc_display": {"mode": "range", "abs": 0.5},           # 범위 최대 1.5(충전 중), 쌍 ≤0.5
    "max_temp": {"mode": "point", "abs": 1}, "min_temp": {"mode": "point", "abs": 1},   # 잡음 0, 쌍 0, 분해능 1
    "module_temp": {"mode": "range", "abs": 1},             # module_temp_N 공통. 잡음 0, 쌍 0
    "inlet_temp": {"mode": "point", "abs": 1},              # 쌍 차이 최대 1
    "dc_inlet_temp_1": {"mode": "point", "abs": 1}, "dc_inlet_temp_2": {"mode": "point", "abs": 1},
    "ac_inlet_temp_1": {"mode": "point", "abs": 1},         # 같은 차 2쌍 차이 ≤1
    "max_cell_v": {"mode": "range", "abs": 0.02}, "min_cell_v": {"mode": "range", "abs": 0.02},  # 범위 최대 0.02(1 LSB)
    "max_cell_no": {"mode": "info"}, "min_cell_no": {"mode": "info"},  # 연속 표본 p95 차이 92·55번 — 비교 불가
    "pack_current": {"mode": "range", "abs": 2},            # p95 0.7, 범위 최대 11.9 → 리버스 범위 + 2A
    "pack_voltage": {"mode": "range", "rel": 0.005, "min": 1},  # p95 0.3, 범위 최대 2.3V
    "inverter_cap_voltage": {"mode": "range", "abs": 3},    # p95 1, 범위 최대 3, 쌍 차이 1
    "ldc_voltage": {"mode": "range", "abs": 0.05},          # 쌍 차이 0.008·0.029V
    "ldc_input_voltage": {"mode": "range", "rel": 0.005, "min": 1},
    "aux_voltage": {"mode": "range", "abs": 0.2},           # 범위 최대 0.1, 쌍 0
    "isolation_kohm": {"mode": "point", "rel": 0.01, "min": 5},  # 범위 최대 5, 쌍 1
    "remaining_energy_kwh": {"mode": "range", "abs": 0.1},  # 범위 0.078, 쌍 0.06~0.08
    "motor_rpm_1": {"mode": "range", "abs": 15}, "motor_rpm_2": {"mode": "range", "abs": 15},  # p95 15
    "max_charge_power_kw": {"mode": "range", "abs": 1}, "max_discharge_power_kw": {"mode": "range", "abs": 1},
    "status_bits": {"mode": "range", "abs": 0},
    # 누적값: 감소는 분해능까지만. 증가 상한 = 시차(초) × 최대 증가율 + 분해능.
    # 증가율은 물리 상한(팩 전류 540A·충전 360kW)이다. [확인 필요] 주행·급속충전 쌍 데이터로 좁힐 것.
    "cum_charge_ah": {"mode": "counter", "abs": 0.1, "rate": 0.15},
    "cum_discharge_ah": {"mode": "counter", "abs": 0.1, "rate": 0.15},
    "cum_charge_kwh": {"mode": "counter", "abs": 0.1, "rate": 0.1},
    "cum_discharge_kwh": {"mode": "counter", "abs": 0.1, "rate": 0.1},
    "operating_time_s": {"mode": "counter", "abs": 1, "rate": None},  # 시차 자체(쌍 200~317초)
    "normal_charge_count": {"mode": "counter", "abs": 0, "rate": None},
    "quick_charge_count": {"mode": "counter", "abs": 0, "rate": None},
    "normal_charge_kwh": {"mode": "counter", "abs": 1, "rate": 0.1},
    "quick_charge_kwh": {"mode": "counter", "abs": 1, "rate": 0.1},
}
_FALLBACK = {"mode": "point", "rel": 0.01, "min": 0.01}
COUNTERS = {k for k, v in DEFAULT_TOLERANCES.items() if v["mode"] == "counter"}

# 유형별 필수 명령(헤더, 요청 접두). 실데이터: 바탕화면 로그의 양성 응답 비율
#  - EV: 위스캔 3/3·지스캔(BMS 응답 있는 8개) 8/8이 7E4 220101~220105·1902를 보냄. 셀 전압(0102~0104)은 셀 편차 판정에 필요
#  - HEV: 지스캔 3개 모두 7E0·7E4 1902, BMS 220101·220105는 2/3 [확인 필요: 표본 3, 위스캔 HEV 기록 없음]
#  - ICE: 지스캔 6개 중 7E0 1902 5/6, 7E1 1902 6/6 [확인 필요: 표본 6, 위스캔 ICE 기록 없음, 쌍용은 주소 다름]
DEFAULT_REQUIRED: dict[str, tuple[tuple[str, str], ...]] = {
    "ev": (("7E4", "220101"), ("7E4", "220102"), ("7E4", "220103"), ("7E4", "220104"), ("7E4", "220105"),
           ("7E4", "1902")),
    "hev": (("7E4", "220101"), ("7E4", "220105"), ("7E0", "1902"), ("7E4", "1902")),
    "ice": (("7E0", "1902"), ("7E1", "1902")),
}
REQUIRED = DEFAULT_REQUIRED


def tolerance_table(overrides: dict | None = None) -> dict[str, dict]:
    table = {k: dict(v) for k, v in DEFAULT_TOLERANCES.items()}
    for key, value in (overrides or {}).items():
        base = dict(table.get(key, _FALLBACK))
        if "abs" in value:  # 절대·비율 중 덮어쓴 쪽만 남긴다
            base.pop("rel", None), base.pop("min", None)
        if "rel" in value:
            base.pop("abs", None)
        table[key] = {**base, **value}
    return table


def _spec(key: str, table: dict | None) -> dict:
    table = table or DEFAULT_TOLERANCES
    if key.startswith("module_temp_") and key not in table:
        key = "module_temp"
    return table.get(key, _FALLBACK)


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


def tolerance(key: str, value: float, table: dict | None = None) -> float:
    spec = _spec(key, table)
    if "rel" in spec:
        return max(abs(value) * spec["rel"], spec.get("min", 0))
    return spec.get("abs", 0)


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
    fields += bms.ecu_fields(platform)
    for f in fields:
        out.append(Definition(f.key, f.label, f.unit, f.request, f.did, f.value, "bms", f.grade,
                              f"{f.request:03X} {f.did:04X}[{f.start}:{f.start + f.width}]×{f.scale}"
                              + (f"{f.offset:+g}" if f.offset else ""), f.note))

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


def _compare(key: str, ours: float, theirs: list[float], table: dict | None = None,
             lag_s: float | None = None) -> tuple[str, str]:
    lo, hi, last = min(theirs), max(theirs), theirs[-1]
    spec = _spec(key, table)
    tol = tolerance(key, ours, table)
    mode = spec["mode"]
    if mode == "info":
        return MATCH, "위치 번호는 동률 셀 사이에서 바뀌어 비교하지 않음"
    if mode == "counter":
        # 위스캔이 나중에 찍힌다(지스캔 먼저). 누적값은 줄어들 수 없다.
        if ours + tol < hi:
            return MISMATCH, f"누적값이 리버스({hi})보다 작음"
        rate = spec.get("rate")
        if rate is not None and lag_s is not None and ours - hi > lag_s * rate + tol:
            return MISMATCH, f"누적값 증가 {round(ours - hi, 3)}가 시차 {round(lag_s)}초 상한 {round(lag_s * rate + tol, 3)} 초과"
        return MATCH, "누적값 정상 증가" if ours > hi else "누적값 같음"
    if mode == "range":
        if lo - tol <= ours <= hi + tol:
            return MATCH, "리버스 범위 안" if lo != hi else ""
        return MISMATCH, f"리버스 범위 {lo}~{hi} 밖(허용 ±{tol:g})"
    if abs(ours - last) <= tol:
        return MATCH, ""
    return MISMATCH, f"차이 {round(ours - last, 4)} (허용 ±{tol:g})"


def _lag_seconds(ours: dict, theirs: dict) -> float | None:
    """위스캔과 리버스 기록의 시차(초): BMS 누적 작동 시간(0101[46:50]) 차. 둘 다 있어야 한다."""
    field = next(f for f in bms.FIELDS if f.key == "operating_time_s")
    w = ours.get((bms.BMS_REQUEST, field.did))
    r = theirs.get((bms.BMS_REQUEST, field.did))
    if not w or not r:
        return None
    a = field.value(w[-1][1])
    b = max((v for _, d in r if (v := field.value(d)) is not None), default=None)
    return a - b if a is not None and b is not None and a >= b else None


def _grade(base: str, status: str) -> str:
    if base == UNKNOWN or status in (MISMATCH, CONFLICT, DEFINITION_ONLY):
        return UNKNOWN
    if status == MATCH:
        return base
    return LIKELY if base == CONFIRMED else UNKNOWN  # 위스캔에만: 리버스로 검증하지 못했다


_SERVICE_STEP = {  # 서비스 → (결과 화면 단계 출처 group, 이름)
    0x01: ("pid", "실시간 데이터"), 0x02: ("freeze", "고장 당시 데이터"), 0x03: ("dtc", "고장코드(OBD)"),
    0x07: ("dtc", "대기 고장코드(OBD)"), 0x09: ("vehicle", "차량정보"), 0x0A: ("dtc", "영구 고장코드(OBD)"),
    0x10: ("uds", "진단 세션"), 0x14: ("dtc", "고장코드 지우기"), 0x19: ("dtc", "고장코드(UDS)"),
    0x1A: ("maker", "제조사 정보(KWP)"), 0x21: ("maker", "제조사 데이터(KWP)"), 0x22: ("maker", "제조사 데이터"),
    0x27: ("uds", "보안 접근"), 0x3E: ("uds", "연결 유지"),
}
_UNSUPPORTED_NRC = {0x11, 0x12, 0x31, 0x7E, 0x7F}


def comm_steps(trace: Trace) -> list[dict]:
    """위스캔 통신기록의 요청/응답 짝을 결과 화면 단계 형식(scanner.interpret._row)으로 만든다.

    단계 구분(header)은 요청 주소, 출처(group)는 서비스 종류다. 응답 원문은 200자까지만 둔다.
    VIN 응답(09 02, 22 F190)은 원문을 남기지 않는다(개인정보)."""
    from app.modules.canlab.engine.uds import NEGATIVE_CODES, ecu_label

    rows = []
    for index, tx in enumerate(trace.transactions, 1):
        group, name = _SERVICE_STEP.get(tx.service, ("uds", f"서비스 {tx.service:02X}"))
        command = tx.request.hex(" ").upper()
        did = tx.did
        label = f"{ecu_label(tx.request_id)} · {name}" + (f" {did:04X}" if did is not None else "")
        vin = (tx.service == 0x09 and tx.request[1:2] == b"\x02") or did == 0xF190
        if tx.negative_code is not None:
            status = "unsupported" if tx.negative_code in _UNSUPPORTED_NRC else "negative"
            message = f"NRC {tx.negative_code:02X} {NEGATIVE_CODES.get(tx.negative_code, '')}".strip()
        elif tx.response is not None:
            status = "ok"
            message = "VIN 응답(원문 생략)" if vin else tx.response.hex(" ").upper()[:60]
        elif not tx.expects_response:
            status, message = "ok", "응답 생략 요청(정상)"
        else:
            status, message = "no_data", "응답 없음"
        raw = "" if vin or tx.response is None else tx.response.hex(" ").upper()[:200]
        latency = None if tx.response_t_ms is None else round(tx.response_t_ms - tx.t_ms, 1)
        rows.append({"id": index, "group": group, "label": label, "header": f"{tx.request_id:03X}",
                     "command": command, "status": status, "status_label": _STATUS_LABEL.get(status, status),
                     "message": message + (f" · {latency} ms" if latency is not None else ""), "raw": raw,
                     "t_ms": round(tx.t_ms, 1)})
    return rows


_STATUS_LABEL = {"ok": "성공", "no_data": "응답 없음", "unsupported": "지원 안 함", "negative": "부정 응답"}


def _commands(trace: Trace) -> list[tuple[str, str]]:
    out = []
    for tx in trace.transactions:
        key = (f"{tx.request_id:03X}", tx.request.hex().upper())
        if not out or out[-1] != key:
            out.append(key)
    return out


def coverage(kind: str, ours: list[tuple[str, str]], theirs: list[tuple[str, str]],
             required: dict | None = None) -> dict:
    def has(commands, header, prefix):
        return any((header == "*" or h == header) and c.startswith(prefix) for h, c in commands)

    rows = [{"header": h, "command": p, "wescan": has(ours, h, p), "reverse": has(theirs, h, p)}
            for h, p in (required or DEFAULT_REQUIRED).get(kind, ())]
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
              references: dict | None = None, tolerances: dict | None = None,
              required: dict | None = None) -> dict:
    """대조 결과(JSON). VIN 원문은 넣지 않는다(앞 11자리 마스킹 + 해시).

    tolerances: tolerance_table() 결과(기본 DEFAULT_TOLERANCES). required: 유형별 필수 명령(기본 DEFAULT_REQUIRED)."""
    tol_table = tolerances or DEFAULT_TOLERANCES
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

    lag_s = _lag_seconds(ours, theirs)
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
                          if v and candidates[0][1] and abs(v[-1] - candidates[0][1][-1]) > tolerance(key, v[-1], tol_table)]
        w_rows = ours.get((best.request_id, best.did))
        r_rows = theirs.get((best.request_id, best.did))
        w_vals = [v for v in _values(best, w_rows) if _in_range(key, v)]
        r_vals = [v for v in _values(best, r_rows) if _in_range(key, v)]
        if not w_vals and not r_vals:
            continue
        used_keys.add((best.request_id, best.did))
        note = best.note
        if w_vals and r_vals:
            status, note2 = _compare(key, w_vals[-1], r_vals, tol_table, lag_s)
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
        "steps": comm_steps(wescan),
        "lag_s": lag_s,
        "coverage": coverage(kind, _commands(wescan), [c for t in reverse for c in _commands(t)], required),
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
