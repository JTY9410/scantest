"""OBDb(https://github.com/OBDb) 현대·기아·제네시스 전동화 차종의 BMS(7E4) 신호 정의를 가져온다.

OBDb 데이터는 CC BY-SA 4.0이다. 가져온 파일(app/modules/canlab/engine/obdb/*.json)도 같은 라이선스로 두고
obdb/NOTICE에 출처·변경 내용을 남긴다. 실행: python scripts/import_obdb.py (인터넷 필요, 결과는 커밋한다)
"""

import json
import re
import subprocess
import sys
import urllib.request
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app/modules/canlab/engine/obdb"
RAW = "https://raw.githubusercontent.com/OBDb/{repo}/{sha}/signalsets/v3/default.json"
GIT = "https://github.com/OBDb/{repo}.git"
REQUEST_ID = "7E4"

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

# OBDb 신호 ID 뒷부분 → 위스캔 신호 키(app/modules/canlab/engine/signals.py). 차종마다 이름 짓는 방식이 달라
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


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def _layout(fmt: dict) -> dict | None:
    """바이트 단위로 맞는 신호만 쓴다. 값 = 원시값 × mul / div + add. min·max는 OBDb의 정상 범위(min 기본 0)."""
    bix, length = fmt.get("bix", 0), fmt.get("len", 0)
    if bix % 8 or length % 8 or length // 8 not in (1, 2, 4) or fmt.get("blsb") or "map" in fmt:
        return None
    layout = {"start": bix // 8, "width": length // 8, "signed": bool(fmt.get("sign")),
              "scale": round(fmt.get("mul", 1) / fmt.get("div", 1), 9), "offset": fmt.get("add", 0)}
    if "max" in fmt:
        layout.update(min=fmt.get("min", 0), max=fmt["max"])
    return layout


def convert(repo: str, sha: str, data: dict) -> dict | None:
    signals, cells, dids = [], [], []
    for command in data.get("commands", []):
        did = (command.get("cmd") or {}).get("22")
        if command.get("hdr") != REQUEST_ID or not did:
            continue
        for signal in command.get("signals", []):
            layout = _layout(signal.get("fmt") or {})
            if layout is None:
                continue
            suffix = re.sub(r"_7E4$", "", signal["id"].split("_", 1)[-1])
            if cell := CELL.search(signal["id"]):
                cells.append({"no": int(cell[1]), "did": did, **layout})
                continue
            for pattern, key in KEYS:
                if match := re.fullmatch(pattern, suffix):
                    number = next((g for g in match.groups() if g), "")
                    signals.append({"key": key.format(number), "id": signal["id"], "did": did, **layout})
                    break
        if did not in dids and (signals and signals[-1]["did"] == did or cells and cells[-1]["did"] == did):
            dids.append(did)
    if not signals and not cells:
        return None
    return {"repo": repo, "url": f"https://github.com/OBDb/{repo}", "commit": sha, "license": "CC-BY-SA-4.0",
            "fetched": date.today().isoformat(), "match": MODELS[repo], "request_id": REQUEST_ID, "dids": dids,
            "signals": signals, "cells": sorted({c["no"]: c for c in reversed(cells)}.values(), key=lambda c: c["no"])}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for repo in MODELS:
        sha = subprocess.run(["git", "ls-remote", GIT.format(repo=repo), "HEAD"], capture_output=True, text=True,
                             check=True, timeout=60).stdout.split()[0]
        result = convert(repo, sha, json.loads(_get(RAW.format(repo=repo, sha=sha))))
        if result is None:
            print(f"{repo}: BMS(7E4) 신호 없음, 건너뜀")
            continue
        (OUT / f"{repo}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        written.append(f"- {repo} @ {sha[:12]}: 신호 {len(result['signals'])}개, 셀 {len(result['cells'])}개")
        print(written[-1])
    license_text = _get("https://raw.githubusercontent.com/OBDb/Hyundai-Kona-Electric/main/LICENSE").decode()
    (OUT / "LICENSE").write_text(license_text, encoding="utf-8")
    (OUT / "NOTICE").write_text(
        "이 폴더의 차종별 JSON은 OBDb(https://github.com/OBDb) 신호 정의에서 만든 2차 저작물이며\n"
        "원본과 같은 Creative Commons Attribution-ShareAlike 4.0(CC BY-SA 4.0, LICENSE)을 따릅니다.\n\n"
        "변경 내용: BMS(7E4) 22 DID 신호 중 바이트 단위 신호만 골라 위스캔 신호 키·바이트 배치(start·width·scale)·정상 범위(min·max)로\n"
        "바꾸고, 차량정보 모델명 매칭 키워드를 더했습니다. 원본 저장소와 커밋은 각 파일의 repo·commit에 있습니다.\n\n"
        + "\n".join(written) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
