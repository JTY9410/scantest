"""OBDb(https://github.com/OBDb) 차종별 BMS 신호 정의. 데이터는 CC BY-SA 4.0(obdb/LICENSE, obdb/NOTICE).

scripts/import_obdb.py가 만든 obdb/*.json을 읽어 차량정보 모델명으로 차종을 고른다.
"""

import json
import re
from datetime import date
from functools import cache
from pathlib import Path

from app.modules.canlab.engine.search import Layout

DIR = Path(__file__).with_name("obdb")
BASE_DIDS = ("0101", "0105")
ATTRIBUTION = "OBDb(github.com/OBDb), CC BY-SA 4.0"


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "").upper()


@cache
def models() -> tuple[dict, ...]:
    return tuple(json.loads(path.read_text(encoding="utf-8")) for path in sorted(DIR.glob("*.json")))


def match(car: dict | None) -> dict | None:
    """모델명·세부모델명에 가장 길게 맞는 키워드의 차종. '니로 EV'는 니로(하이브리드)보다 니로 EV를 고른다."""
    name = _norm(f"{(car or {}).get('diag_model') or ''}{(car or {}).get('diag_submodel') or ''}")
    best, best_len = None, 0
    for model in models():
        for keyword in model["match"]:
            key = _norm(keyword)
            if key in name and len(key) > best_len:
                best, best_len = model, len(key)
    return best


def plan_dids(car: dict | None) -> list[str]:
    """현대·기아 BMS(7E4)에 보낼 22 DID. 차종 정의가 있으면 셀 전압 DID 등을 더한다."""
    model = match(car)
    extra = [did for did in (model or {}).get("dids", []) if did not in BASE_DIDS]
    return [*BASE_DIDS, *extra]


def _layout(model: dict, item: dict) -> Layout:
    return Layout(int(model["request_id"], 16), int(item["did"], 16), item["start"], item["width"], "big",
                  item["signed"], item["scale"], item["offset"])


def _range(item: dict) -> tuple[float, float] | None:
    return (item["min"], item["max"]) if "max" in item else None


def signal_layouts(model: dict) -> list[tuple[str, Layout, tuple[float, float] | None]]:
    """(신호 키, 배치, OBDb 정상 범위)."""
    return [(item["key"], _layout(model, item), _range(item)) for item in model["signals"]]


def cell_layouts(model: dict) -> list[tuple[int, Layout, tuple[float, float] | None]]:
    return [(item["no"], _layout(model, item), _range(item)) for item in model["cells"]]


# ── OBDb 원본(signalsets/v3/default.json) 변환. scripts/import_obdb.py와 참고자료 DB 동기화가 같이 쓴다. ──

RAW_URL = "https://raw.githubusercontent.com/OBDb/{repo}/{ref}/signalsets/v3/default.json"
REPO_URL = "https://github.com/OBDb/{repo}"
REQUEST_ID = "7E4"
LICENSE = "CC-BY-SA-4.0"

# OBDb 저장소 → 차량정보 조회 결과(모델명)에서 찾을 이름. 공백은 무시하고 비교한다.
MODELS = {
    "Hyundai-Kona-Electric": ["코나일렉트릭", "코나EV", "KONAELECTRIC", "KONAEV"],
    "Hyundai-IONIQ-Electric": ["아이오닉일렉트릭", "아이오닉EV", "IONIQELECTRIC", "IONIQEV"],
    "Hyundai-IONIQ-PlugIn-Hybrid": ["아이오닉플러그인", "아이오닉PHEV", "IONIQPHEV"],
    "Hyundai-IONIQ-5": ["아이오닉5", "IONIQ5"],
    "Hyundai-IONIQ-6": ["아이오닉6", "IONIQ6"],
    "Hyundai-IONIQ-9": ["아이오닉9", "IONIQ9"],
    "Hyundai-Santa-Fe-Hybrid": ["싼타페하이브리드", "싼타페HEV", "SANTAFEHYBRID"],
    "Hyundai-Tucson-Hybrid": ["투싼하이브리드", "투싼HEV", "TUCSONHYBRID"],
    "Kia-Niro-EV": ["니로EV", "니로플러스", "E-NIRO", "NIROEV"],
    "Kia-Niro": ["니로"],
    "Kia-Soul-EV": ["쏘울EV", "쏘울부스터EV", "SOULEV"],
    "Kia-Sportage-HEV": ["스포티지하이브리드", "스포티지HEV", "SPORTAGEHYBRID"],
    "Kia-EV3": ["EV3"],
    "Kia-EV6": ["EV6"],
    "Kia-EV9": ["EV9"],
    "Genesis-GV60": ["GV60"],
}
MAKERS = {"Hyundai": "현대", "Kia": "기아", "Genesis": "제네시스"}

# OBDb 신호 ID 뒷부분 → 위스캔 신호 키(signals.py). 차종마다 이름 짓는 방식이 달라
# (HVBAT_*, BATTERY_*, BAT_*) 모두 적는다. 끝의 '_7E4'는 무시한다.
KEYS = [
    (r"HVBAT_SOC", "soc"), (r"HVBAT_SOC_DISP", "soc_display"), (r"HVBAT_SOH", "soh"),
    (r"HVBAT_CURR|BATTERY_CURRENT|BAT_CURRENT", "pack_current"),
    (r"HVBAT_VDC|BATTERY_DC_VOLTAGE|BAT_DC_V", "pack_voltage"),
    (r"HVBAT_T_MAX|BATTERY_MAX_T|BAT_MAX_T", "max_temp"), (r"HVBAT_T_MIN|BATTERY_MIN_T|BAT_MIN_T", "min_temp"),
    (r"HVBAT_MOD([1-5])_T|BATTERY_PACK_B0([1-5])|BAT_MODULE_0([1-5])_T", "module_temp_{0}"),
    (r"HVBAT_INLET_T|BATTERY_INLET_T|BAT_INLET_T", "inlet_temp"),
    (r"C_V_MAX", "max_cell_v"), (r"C_V_MAX_ID", "max_cell_no"), (r"C_V_MIN", "min_cell_v"),
    (r"C_V_MIN_ID", "min_cell_no"), (r"VPWR|AUXILL?IARY_BATTERY_VOLTAGE|AUXILIARY_BAT_V", "aux_voltage"),
    (r"HVBAT_CHRG_TOT_C|CUMULATIVE_CHARGE_CURRENT|CUM_CHG_CURRENT", "cum_charge_ah"),
    (r"HVBAT_DSCH_TOT_C|CUMULATIVE_DISCHARGE_CURRENT|CUM_DCHG_CURRENT", "cum_discharge_ah"),
    (r"HVBAT_CHRG_TOT_E|CUMULATIVE_ENERGY_CHARGED|CUM_ENERGY_CHARGED", "cum_charge_kwh"),
    (r"HVBAT_DSCH_TOT_E|CUMULATIVE_ENERGY_DISCHARGED", "cum_discharge_kwh"),
    (r"DRIVE_TIME|BATTERY_WORK_TIME_TOTAL_SEC", "operating_time_s"),
    (r"INVRT_CV|INVERTER_CAPACITOR_VOLTAGE|INVERTER_CAPACITOR_V", "inverter_cap_voltage"),
    (r"ISO_R|ISOLATION_RESISTANCE|ISOLATION_RES", "isolation_kohm"),
    (r"HVBAT_CHG_P_AVAIL|AVAILABLE_CHG_POWER", "max_charge_power_kw"),
    (r"HVBAT_DCHG_P_AVAIL|AVAILABLE_DCHG_POWER", "max_discharge_power_kw"),
]
CELL = re.compile(r"HVBAT_CMU(\d+)_VOLT(?:_7E4)?$")


def _fmt_layout(fmt: dict) -> dict | None:
    """바이트 단위로 맞는 신호만 쓴다. 값 = 원시값 × mul / div + add. min·max는 OBDb의 정상 범위(min 기본 0)."""
    bix, length = fmt.get("bix", 0), fmt.get("len", 0)
    if bix % 8 or length % 8 or length // 8 not in (1, 2, 4) or fmt.get("blsb") or "map" in fmt:
        return None
    layout = {"start": bix // 8, "width": length // 8, "signed": bool(fmt.get("sign")),
              "scale": round(fmt.get("mul", 1) / fmt.get("div", 1), 9), "offset": fmt.get("add", 0)}
    if "max" in fmt:
        layout.update(min=fmt.get("min", 0), max=fmt["max"])
    return layout


def convert(repo: str, sha: str, data: dict, keywords: list[str] | None = None) -> dict | None:
    """OBDb 원본을 위스캔 신호 키·바이트 배치로 바꾼다. BMS(7E4) 22 DID 신호만 쓴다."""
    found, cells, dids = [], [], []
    for command in data.get("commands", []):
        did = (command.get("cmd") or {}).get("22")
        if command.get("hdr") != REQUEST_ID or not did:
            continue
        for signal in command.get("signals", []):
            layout = _fmt_layout(signal.get("fmt") or {})
            if layout is None:
                continue
            suffix = re.sub(r"_7E4$", "", signal["id"].split("_", 1)[-1])
            if cell := CELL.search(signal["id"]):
                cells.append({"no": int(cell[1]), "did": did, **layout})
                continue
            for pattern, key in KEYS:
                if match := re.fullmatch(pattern, suffix):
                    number = next((g for g in match.groups() if g), "")
                    found.append({"key": key.format(number), "id": signal["id"], "did": did, **layout})
                    break
        if did not in dids and (found and found[-1]["did"] == did or cells and cells[-1]["did"] == did):
            dids.append(did)
    if not found and not cells:
        return None
    return {"repo": repo, "url": REPO_URL.format(repo=repo), "commit": sha, "license": LICENSE,
            "fetched": date.today().isoformat(), "match": keywords if keywords is not None else MODELS[repo],
            "request_id": REQUEST_ID, "dids": dids, "signals": found,
            "cells": sorted({c["no"]: c for c in reversed(cells)}.values(), key=lambda c: c["no"])}
