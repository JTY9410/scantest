"""현대·기아 EV/HEV BMS(요청 7E4, 응답 7EC) `22 0101~010C` 응답 해석.

근거와 등급은 2026-11-05 검증 결과(실차 로그 14개 + OBDb Hyundai-IONIQ-5 + JejuSoul OBD-PIDs-for-HKMC-EVs)와
같은 날 2차 검증(OBDb 상위 저장소 signalsets/v3, OBDb Kia-Niro-EV·하이브리드, 제조사 사양서)을 따른다.
- 확인됨: 출처 2개 일치, 또는 출처 1개 + 로그 계산 검증(셀 합계 = 팩 전압, kWh/Ah = 공칭 전압 등)
- 유력: 출처 1개 또는 값 범위만 부합
- 미확인: 공개 근거 없음(원시값만 보여 준다)
바이트 위치는 응답 `62 01 xx` 다음 첫 바이트를 0으로 센다(uds.Transaction.data와 같다).
"""

from dataclasses import dataclass

BMS_REQUEST = 0x7E4
CONFIRMED, LIKELY, UNKNOWN = "확인됨", "유력", "미확인"
CELL_PIDS = (0x0102, 0x0103, 0x0104, 0x010A, 0x010B, 0x010C)
CELL_SCALE = 0.02
# 2V 미만(원시값 100 미만: 0x00·0x01·0xFF 마스크 이외의 패딩)은 미장착 셀로 보고 뺀다.
CELL_MIN_RAW = 100
UNVERIFIED_PIDS = (0x0106, 0x0107, 0x0108, 0x0114, 0x0130, 0x0131, 0x0132, 0x0133, 0x0134,
                   0x0135, 0x0136, 0x0137, 0x01F2)


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    did: int
    start: int
    width: int
    scale: float
    unit: str
    grade: str
    signed: bool = False
    offset: float = 0.0
    note: str = ""

    def value(self, data: bytes) -> float | None:
        if len(data) < self.start + self.width:
            return None
        raw = int.from_bytes(data[self.start : self.start + self.width], "big", signed=self.signed)
        return round(raw * self.scale + self.offset, 4)


FIELDS: tuple[Field, ...] = (
    Field("soc", "SOC(BMS)", 0x0101, 4, 1, 0.5, "%", CONFIRMED),
    Field("max_charge_power_kw", "최대 회생(충전) 가능 전력", 0x0101, 5, 2, 0.01, "kW", CONFIRMED,
          note="정의: OBDb Kia-Niro-EV·JejuSoul 일치. 정차 로그라 값 0(실측 검증은 주행 로그 필요)"),
    Field("max_discharge_power_kw", "최대 방전 가능 전력", 0x0101, 7, 2, 0.01, "kW", CONFIRMED,
          note="정의: OBDb Kia-Niro-EV·JejuSoul 일치. 정차 로그라 값 0(실측 검증은 주행 로그 필요)"),
    Field("status_bits", "상태 비트(bit7 충전중·bit6 급속포트·bit5 완속포트·bit0 메인릴레이)", 0x0101, 9, 1, 1, "",
          CONFIRMED, note="OBDb IONIQ-5·JejuSoul 비트 위치 일치"),
    Field("pack_current", "팩 전류(+방전)", 0x0101, 10, 2, 0.1, "A", CONFIRMED, signed=True),
    Field("pack_voltage", "팩 전압", 0x0101, 12, 2, 0.1, "V", CONFIRMED),
    Field("max_temp", "최고 모듈 온도", 0x0101, 14, 1, 1, "°C", CONFIRMED, signed=True),
    Field("min_temp", "최저 모듈 온도", 0x0101, 15, 1, 1, "°C", CONFIRMED, signed=True),
    *(Field(f"module_temp_{n}", f"모듈 온도 {n}", 0x0101, 15 + n, 1, 1, "°C", CONFIRMED, signed=True,
            note="HEV는 모듈 5 값 0(모듈 4개)" if n == 5 else "") for n in range(1, 6)),
    Field("max_cell_v", "최고 셀 전압", 0x0101, 23, 1, CELL_SCALE, "V", CONFIRMED),
    Field("max_cell_no", "최고 셀 번호", 0x0101, 24, 1, 1, "", CONFIRMED),
    Field("min_cell_v", "최저 셀 전압", 0x0101, 25, 1, CELL_SCALE, "V", CONFIRMED),
    Field("min_cell_no", "최저 셀 번호", 0x0101, 26, 1, 1, "", CONFIRMED),
    Field("fan_status", "배터리 냉각팬 상태", 0x0101, 27, 1, 1, "", CONFIRMED, note="OBDb·JejuSoul 일치(수랭 차량은 0)"),
    Field("fan_feedback_hz", "배터리 냉각팬 피드백", 0x0101, 28, 1, 1, "Hz", CONFIRMED, note="OBDb·JejuSoul 일치"),
    Field("aux_voltage", "12V 보조배터리 전압", 0x0101, 29, 1, 0.1, "V", CONFIRMED,
          note="OBDb·JejuSoul 일치, 로그 12.5~14.7V"),
    Field("cum_charge_ah", "누적 충전 전류량", 0x0101, 30, 4, 0.1, "Ah", CONFIRMED),
    Field("cum_discharge_ah", "누적 방전 전류량", 0x0101, 34, 4, 0.1, "Ah", CONFIRMED),
    Field("cum_charge_kwh", "누적 충전 전력량", 0x0101, 38, 4, 0.1, "kWh", CONFIRMED),
    Field("cum_discharge_kwh", "누적 방전 전력량", 0x0101, 42, 4, 0.1, "kWh", CONFIRMED),
    Field("operating_time_s", "누적 BMS 작동 시간", 0x0101, 46, 4, 1, "s", CONFIRMED,
          note="대기 시간 포함 추정 — 시간 기반 SOH에 그대로 쓰기 부적합(유력)"),
    Field("ignition_bits", "상태 비트(bit2 BMS 점화)", 0x0101, 50, 1, 1, "", CONFIRMED, note="OBDb·JejuSoul 일치"),
    Field("inverter_cap_voltage", "인버터 커패시터 전압", 0x0101, 51, 2, 1, "V", CONFIRMED),
    Field("motor_rpm_1", "구동모터 회전수 1", 0x0101, 53, 2, 1, "rpm", CONFIRMED, signed=True, note="OBDb·JejuSoul 일치"),
    Field("motor_rpm_2", "구동모터 회전수 2", 0x0101, 55, 2, 1, "rpm", CONFIRMED, signed=True, note="OBDb·JejuSoul 일치"),
    Field("isolation_kohm", "절연 저항", 0x0101, 57, 2, 1, "kΩ", CONFIRMED, note="상한 포화 값으로 보임"),
    Field("cell_deviation_v", "셀 전압 편차(BMS)", 0x0105, 20, 1, CELL_SCALE, "V", LIKELY),
    Field("soc_display", "표시 SOC", 0x0105, 31, 1, 0.5, "%", CONFIRMED),
)


# E-GMP·니로 계열 전용(차종별 길이 다름): 0105 남은 에너지, 0111 충전 횟수·에너지. OBDb IONIQ-5 정의 1개 + 값 범위 → 유력.
EGMP_EXTRA: tuple[Field, ...] = (
    Field("remaining_energy_kwh", "남은 에너지(BMS)", 0x0105, 28, 2, 0.002, "kWh", LIKELY,
          note="OBDb IONIQ-5만 근거. 0111 [20–21]과 같은 값"),
    Field("normal_charge_count", "완속 충전 횟수", 0x0111, 4, 4, 1, "회", LIKELY, note="OBDb IONIQ-5만 근거"),
    Field("quick_charge_count", "급속 충전 횟수", 0x0111, 8, 4, 1, "회", LIKELY, note="OBDb IONIQ-5만 근거"),
    Field("normal_charge_kwh", "완속 충전 누적 에너지", 0x0111, 12, 4, 1, "kWh", LIKELY,
          note="OBDb IONIQ-5만 근거. 완속+급속 ≤ 누적 충전 에너지(로그 8대 성립)"),
    Field("quick_charge_kwh", "급속 충전 누적 에너지", 0x0111, 16, 4, 1, "kWh", LIKELY, note="OBDb IONIQ-5만 근거"),
)
# 0111 [26]/[27] 모듈 온도 17·18: 셀 96·180·192 차량에서만 모듈 온도와 같은 범위(아이오닉6 132셀은 0 → 다른 배치).
EXTRA_TEMP_CELLS = (96, 180, 192)

# 공칭 용량: 제조사 공식 자료 수치만(셀 직렬 수로 팩 구분). 없으면 등가 사이클을 계산하지 않는다.
#  - 192직렬(384셀, 77.4kWh, 111.2Ah, 697V): Kia EV6 공식 사양서, 미국 EPA 인증서(Hyundai IONIQ 5)
#  - 180직렬(72.6kWh): Hyundai 공식 보도자료의 용량. 180직렬=72.6kWh 대응은 분해 자료 근거라 '유력'
NOMINAL_PACKS: dict[tuple[str, int], dict] = {
    ("egmp", 192): {"kwh": 77.4, "ah": 111.2, "v": 697, "grade": CONFIRMED,
                    "source": "Kia EV6 사양서(kia.com)·EPA 인증서 IONIQ 5(dis.epa.gov docid 54043)"},
    ("egmp", 180): {"kwh": 72.6, "ah": None, "v": None, "grade": LIKELY,
                    "source": "Hyundai 보도자료 72.6kWh. 셀 수 대응은 분해 자료(InsideEVs) 근거"},
}


def platform(model_hint: str | None, cell_count: int | None) -> str:
    """흡기 온도 오프셋·SOH 등급이 갈리는 플랫폼.
    'egmp'(아이오닉5·6·EV6·GV60), 'niro'(니로EV, 세대 구분 불가), 'hkmc_ev_gen1'(코나EV·아이오닉 일렉트릭·쏘울EV),
    'porter'(포터·봉고EV), 'hev', 'unknown'."""
    hint = (model_hint or "").replace(" ", "").upper()
    if any(k in hint for k in ("포터", "PORTER", "봉고", "BONGO")):
        return "porter"
    if any(k in hint for k in ("HEV", "하이브리드", "HYBRID")):
        return "hev"
    if any(k in hint for k in ("아이오닉5", "아이오닉6", "IONIQ5", "IONIQ6", "EV6", "GV60")):
        return "egmp"
    if any(k in hint for k in ("니로", "NIRO")):
        return "niro"
    if any(k in hint for k in ("코나", "KONA", "아이오닉일렉트릭", "IONIQELECTRIC", "쏘울", "SOUL")):
        return "hkmc_ev_gen1"
    if cell_count == 72:
        return "hev"
    if cell_count == 90:
        return "porter"
    if cell_count == 96:
        return "niro"
    if cell_count in (132, 180, 192):
        return "egmp"
    return "unknown"


def _hex(data: bytes) -> str:
    return data.hex(" ").upper()


def cells(samples: dict) -> dict | None:
    """셀 전압 PID를 모아 셀 수·최고·최저·편차를 계산한다. 셀 수는 하드코딩하지 않고 데이터에서 센다."""
    values: list[float] = []
    found = []
    for did in CELL_PIDS:
        rows = samples.get((BMS_REQUEST, did))
        if not rows:
            continue
        found.append(f"{did:04X}")
        data = rows[-1][1]
        values += [raw * CELL_SCALE for raw in data[4:36] if raw >= CELL_MIN_RAW and raw != 0xFF]
    if not values:
        return None
    return {
        "count": len(values), "min": round(min(values), 3), "max": round(max(values), 3),
        "avg": round(sum(values) / len(values), 3), "sum_v": round(sum(values), 2),
        "spread_mv": round((max(values) - min(values)) * 1000), "pids": found, "grade": CONFIRMED,
    }


def decode_bms(samples: dict, model_hint: str | None = None) -> dict | None:
    """BMS 응답이 있으면 필드별 값·등급과 셀 통계, SOH, 자기검증 지표를 돌려준다."""
    rows_0101 = samples.get((BMS_REQUEST, 0x0101))
    rows_0105 = samples.get((BMS_REQUEST, 0x0105))
    if not rows_0101 and not rows_0105:
        return None
    cell = cells(samples)
    plat = platform(model_hint, cell["count"] if cell else None)
    latest = {did: rows[-1][1] for (req, did), rows in samples.items() if req == BMS_REQUEST and rows}
    fields = []
    values: dict[str, float] = {}
    for field in FIELDS:
        data = latest.get(field.did)
        if data is None or (value := field.value(data)) is None:
            continue
        values[field.key] = value
        fields.append({"key": field.key, "label": field.label, "value": value, "unit": field.unit,
                       "grade": field.grade, "pid": f"{field.did:04X}", "bytes": f"{field.start}"
                       + (f"–{field.start + field.width - 1}" if field.width > 1 else ""), "note": field.note})
    if (data := latest.get(0x0101)) is not None and len(data) > 22:
        value, grade, note = inlet_temp(data[22], plat, values)
        fields.append({"key": "inlet_temp", "label": "배터리 입구(냉각수) 온도", "value": value, "unit": "°C",
                       "grade": grade, "pid": "0101", "bytes": "22", "note": note})
        if value is not None:
            values["inlet_temp"] = value
    if plat in ("egmp", "niro", "porter"):
        for field in EGMP_EXTRA:
            data = latest.get(field.did)
            if data is None or (value := field.value(data)) is None:
                continue
            if field.did == 0x0105 and plat == "porter":
                continue  # 포터 0105는 앞부분 배치가 다르다
            values[field.key] = value
            fields.append({"key": field.key, "label": field.label, "value": value, "unit": field.unit,
                           "grade": field.grade, "pid": f"{field.did:04X}", "bytes": f"{field.start}–"
                           f"{field.start + field.width - 1}", "note": field.note})
        if (data := latest.get(0x0111)) is not None and len(data) >= 28 and cell and cell["count"] in EXTRA_TEMP_CELLS:
            for n, idx in ((17, 26), (18, 27)):
                t = int.from_bytes(data[idx:idx + 1], "big", signed=True)
                values[f"module_temp_{n}"] = t
                fields.append({"key": f"module_temp_{n}", "label": f"모듈 온도 {n}", "value": t, "unit": "°C",
                               "grade": LIKELY, "pid": "0111", "bytes": str(idx),
                               "note": "OBDb IONIQ-5만 근거, 0101 모듈 온도와 같은 범위"})
    soh = None
    if (data := latest.get(0x0105)) is not None and len(data) >= 27:
        raw = int.from_bytes(data[25:27], "big") * 0.1
        if 0 < raw <= 110:
            grade = CONFIRMED if plat in ("egmp", "niro", "hkmc_ev_gen1") else LIKELY
            note = ""
            if plat == "hev":
                note = "HEV: OBDb 싼타페·투싼 하이브리드 정의 1개뿐(값만 부합)"
            elif grade != CONFIRMED:
                note = "포터EV 등: 위치 근거 없음(값만 부합)"
            soh = {"value": round(raw, 1), "grade": grade, "pid": "0105", "bytes": "25–26", "note": note}
            values["soh"] = soh["value"]
            fields.append({"key": "soh", "label": "SOH(BMS 산출)", "value": soh["value"], "unit": "%",
                           "grade": grade, "pid": "0105", "bytes": "25–26", "note": soh["note"]})
    pack = NOMINAL_PACKS.get((plat, cell["count"])) if cell else None
    checks = self_checks(values, cell, pack)
    unknown = [{"pid": f"{did:04X}", "length": len(latest[did]), "raw": _hex(latest[did][:24])}
               for did in UNVERIFIED_PIDS if did in latest]
    return {"platform": plat, "fields": fields, "values": values, "cells": cell, "soh": soh, "pack": pack,
            "checks": checks, "unverified": unknown,
            "samples": {f"{did:04X}": len(samples.get((BMS_REQUEST, did)) or []) for did in sorted(latest)}}


def inlet_temp(raw: int, plat: str, values: dict) -> tuple[int | None, str, str]:
    """0101 [22] 배터리 입구 온도. 오프셋이 차종마다 다르다(OBDb E-GMP −40, OBDb 코나·니로 1세대·JejuSoul 0).

    - E-GMP: OBDb(IONIQ5·6·EV6·GV60) −40 + 로그(모듈 온도와 0~6°C 차) → 확인됨
    - 코나EV·아이오닉 일렉트릭·쏘울EV(1세대): OBDb·JejuSoul 모두 오프셋 0 → 확인됨(로그 없음)
    - 니로EV·포터EV·HEV: 출처가 없거나 세대별로 엇갈려 모듈 온도와 맞는 쪽 하나만 고른다 → 유력
    - 차종 불명: 미확인(원시값만)
    """
    signed = int.from_bytes(bytes([raw]), "big", signed=True)
    if plat == "egmp":
        return raw - 40, CONFIRMED, "−40 오프셋(OBDb E-GMP + 모듈 온도와 부합)"
    if plat == "hkmc_ev_gen1":
        return signed, CONFIRMED, "오프셋 없음(OBDb 코나·니로 1세대·JejuSoul 일치)"
    if plat in ("niro", "porter", "hev"):
        temps = [values[k] for k in ("max_temp", "min_temp") if k in values]
        if temps:
            lo, hi = min(temps) - 10, max(temps) + 10
            fits = [(off, v) for off, v in ((-40, raw - 40), (0, signed)) if lo <= v <= hi]
            if len(fits) == 1:
                off, v = fits[0]
                return v, LIKELY, f"{'−40' if off else '오프셋 없음'}: 모듈 온도({min(temps)}~{max(temps)}°C)와 맞는 쪽"
        return None, UNKNOWN, f"오프셋 판정 불가(원시값 0x{raw:02X})"
    return None, UNKNOWN, f"차종별 오프셋 다름(원시값 0x{raw:02X}) — 차종 확인 필요"


def self_checks(values: dict, cell: dict | None, pack: dict | None = None) -> dict:
    """파싱 자기검증과 보조 지표. 값이 없으면 넣지 않는다."""
    out: dict = {}
    if pack and pack["grade"] == CONFIRMED and values.get("cum_discharge_kwh"):
        # 등가 완전 사이클 = 누적 방전 에너지 ÷ 공칭 용량(공식 수치가 확인된 팩만)
        out["equivalent_cycles"] = round(values["cum_discharge_kwh"] / pack["kwh"], 1)
    if cell and values.get("pack_voltage"):
        out["cell_sum_vs_pack_pct"] = round((cell["sum_v"] - values["pack_voltage"]) / values["pack_voltage"] * 100, 2)
    if values.get("cum_charge_ah") and values.get("cum_charge_kwh"):
        out["charge_kwh_per_ah_v"] = round(values["cum_charge_kwh"] * 1000 / values["cum_charge_ah"], 1)
    if values.get("cum_charge_kwh") and values.get("cum_discharge_kwh"):
        out["efficiency_pct"] = round(values["cum_discharge_kwh"] / values["cum_charge_kwh"] * 100, 1)
    if "max_cell_v" in values and "min_cell_v" in values:
        out["cell_spread_mv"] = round((values["max_cell_v"] - values["min_cell_v"]) * 1000)
    return out
