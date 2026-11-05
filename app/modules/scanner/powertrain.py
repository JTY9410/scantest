"""차량 구동 유형(전기차 ev · 하이브리드 hev · 내연기관 ice) 판별.

근거 우선순위: 수동 지정 > 차량조회 연료 > 모델명 > ECU 응답(MCU·충전기·엔진, OBD 연료 PID) > BMS 데이터.
- 플러그인 하이브리드(PHEV)는 hev + plugin=True(하이브리드 보고서에 충전 항목을 더한다).
- 수소차(FCEV)는 우선 ev + hydrogen=True(연료전지 항목은 아직 없다).
- 마일드 하이브리드(48V)는 고전압 배터리가 없어 ice로 본다.
차량조회 API가 주는 연료 문자열의 전체 목록은 확인되지 않았다. 모르는 문자열은 다음 근거로 넘긴다.
"""

import re
from typing import Any

EV, HEV, ICE = "ev", "hev", "ice"
TYPES = (EV, HEV, ICE)
LABELS = {EV: "전기차", HEV: "하이브리드", ICE: "내연기관"}
SOURCES = {"manual": "수동 지정", "fuel": "차량조회 연료", "model": "모델명", "ecu": "ECU 응답",
           "bms": "BMS 데이터", "default": "근거 없음(기본값)", "reclassified": "일괄 재분류"}

_MILD = ("마일드", "MILD", "MHEV", "48V")
_PLUGIN = ("플러그인", "PLUGIN", "PLUG-IN", "PHEV")
_HYBRID = ("하이브리드", "HYBRID", "HEV")
_HYDROGEN = ("수소", "HYDROGEN", "FCEV", "넥쏘", "NEXO")
_ELECTRIC = ("전기", "ELECTRIC", "일렉트릭", "BEV")
_COMBUSTION = ("휘발유", "가솔린", "GASOLINE", "경유", "디젤", "DIESEL", "엘피지", "LPG", "LPI", "CNG", "LNG",
               "메탄올", "에탄올", "프로판")
_EV_TOKEN = re.compile(r"(?<![A-Z])E-?V\d*(?![A-Z])")
_EV_MODELS = ("아이오닉5", "아이오닉6", "아이오닉9", "IONIQ5", "IONIQ6", "IONIQ9", "GV60", "아이오닉일렉트릭",
              "IONIQELECTRIC", "코나일렉트릭", "KONAELECTRIC", "포터2일렉트릭", "봉고3EV", "캐스퍼일렉트릭")

_MCU = {"7E5", "7ED"}
_CHARGER = {"7E7", "7EF"}
_ENGINE = {"7E0", "7E8"}


def _norm(text: Any) -> str:
    return re.sub(r"[\s_()·/+]", "", str(text or "")).upper()


def _has(text: str, words) -> bool:
    return any(_norm(w) in text for w in words)


def _from_text(text: str) -> dict | None:
    """연료 문자열이나 모델명에서 유형을 읽는다. 모르면 None."""
    if not text:
        return None
    if _has(text, _MILD):
        return {"type": ICE, "plugin": False, "hydrogen": False}
    if _has(text, _PLUGIN):
        return {"type": HEV, "plugin": True, "hydrogen": False}
    if _has(text, _HYBRID):
        return {"type": HEV, "plugin": False, "hydrogen": False}
    if _has(text, _HYDROGEN):
        return {"type": EV, "plugin": False, "hydrogen": True}
    if _has(text, _ELECTRIC):
        return {"type": EV, "plugin": False, "hydrogen": False}
    if _has(text, _COMBUSTION):
        return {"type": ICE, "plugin": False, "hydrogen": False}
    return None


def _from_model(text: str) -> dict | None:
    if not text:
        return None
    found = _from_text(text)
    if found and found["type"] in (HEV, EV) or (found and _has(text, _MILD)):
        return found
    if _has(text, _EV_MODELS) or _EV_TOKEN.search(text):
        return {"type": EV, "plugin": False, "hydrogen": False}
    return None


def _answered(result: dict) -> set[str]:
    out = set()
    for step in result.get("steps") or []:
        if step.get("status") == "ok" and step.get("header"):
            out.add(str(step["header"]).upper())
    for dtc in result.get("dtcs") or []:
        if dtc.get("ecu"):
            out.add(str(dtc["ecu"]).upper())
    return out


def _from_ecu(result: dict) -> tuple[dict | None, str]:
    fuel_pid = next((v.get("value") for v in result.get("values") or [] if v.get("key") == "fuel_type"), None)
    if fuel_pid is not None and (found := _from_text(_norm(fuel_pid))):
        return found, f"OBD 연료 종류 PID(0x51): {fuel_pid}"
    seen = _answered(result)
    mcu, charger, engine = bool(seen & _MCU), bool(seen & _CHARGER), bool(seen & _ENGINE)
    if mcu and engine:
        return {"type": HEV, "plugin": charger, "hydrogen": False}, "모터(MCU)와 엔진이 모두 응답"
    if (mcu or charger) and not engine:
        return {"type": EV, "plugin": False, "hydrogen": False}, "모터·충전기 응답, 엔진 무응답"
    return None, ""


def _from_bms(result: dict, model_hint: str) -> tuple[dict | None, str]:
    battery = result.get("battery") or {}
    if not battery:
        return None, ""
    from app.modules.canlab.engine.bms import platform

    cells = (result.get("cells") or {}).get("count")
    if platform(model_hint, cells) == "hev":
        return {"type": HEV, "plugin": False, "hydrogen": False}, f"BMS 셀 {cells}개(하이브리드 배터리 구성)"
    return {"type": EV, "plugin": False, "hydrogen": False}, "고전압 BMS 응답"


def classify(car: dict | None, result: dict | None = None, *, manual: str | None = None,
             model_hint: str | None = None) -> dict:
    """{'type','label','source','source_label','plugin','hydrogen','reason'}을 돌려준다."""
    car = car or {}
    result = result or {}
    hint = _norm(model_hint or " ".join(str(car.get(k) or "") for k in ("diag_model", "diag_submodel")))

    def done(found: dict, source: str, reason: str) -> dict:
        return {"type": found["type"], "label": LABELS[found["type"]], "source": source,
                "source_label": SOURCES[source], "plugin": bool(found.get("plugin")),
                "hydrogen": bool(found.get("hydrogen")), "reason": reason}

    if manual in TYPES:
        extra = _from_text(_norm(car.get("diag_fuel"))) or _from_model(hint) or {}
        same = extra.get("type") == manual
        return done({"type": manual, "plugin": same and extra.get("plugin"),
                     "hydrogen": same and extra.get("hydrogen")}, "manual", "검사자가 지정")
    fuel = car.get("diag_fuel")
    if found := _from_text(_norm(fuel)):
        named = _from_model(hint)
        if found["type"] == ICE and named and named["type"] != ICE:
            # 하이브리드를 '휘발유'로만 돌려주는 조회 결과가 있을 수 있어 모델명이 전동화면 모델명을 따른다.
            return done(named, "model", f"모델명(차량조회 연료 '{fuel}'보다 우선)")
        return done(found, "fuel", f"차량조회 연료: {fuel}")
    if found := _from_model(hint):
        return done(found, "model", "모델명")
    found, reason = _from_ecu(result)
    if found:
        return done(found, "ecu", reason)
    found, reason = _from_bms(result, hint)
    if found:
        return done(found, "bms", reason)
    return done({"type": ICE}, "default", "전동화 근거 없음")
