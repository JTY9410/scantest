"""OBDb(https://github.com/OBDb) 차종별 BMS 신호 정의. 데이터는 CC BY-SA 4.0(obdb/LICENSE, obdb/NOTICE).

scripts/import_obdb.py가 만든 obdb/*.json을 읽어 차량정보 모델명으로 차종을 고른다.
"""

import json
import re
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
