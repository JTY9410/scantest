"""위카 앱(evolsraet/wecar_scan dev)이 전기차에 보내는 읽기 명령.

세션 변경·보안·쓰기·지우기는 넣지 않는다. 앱이 22 0101 바이트로 SOH를 계산하는 식은
최저 셀 번호를 건강 상태로 오해하므로 저장하지 않는다.
"""

from sqlalchemy import select

from app.extensions import db
from app.modules.knowledge.collect import _dtc
from app.modules.knowledge.models import KnowledgeCommand, KnowledgeFormula
from app.modules.knowledge.public_data import DTCS

_SOURCE = "reverse_analysis"
_DETAIL = "wecar_scan dev: obd_commands.dart, ble_connect_service.dart, obd_parser.dart"
_BMS = ("7E4", "7E5", "7E6")
_DTC_COMMANDS = (
    ("190209", "확정 고장코드(19 02 09)"),
    ("190204", "대기 고장코드(19 02 04)"),
    ("1915", "영구 고장코드(19 15)"),
)

# 앱 파서가 실제로 읽는 값. 수식은 앱이 먼저 시도하는 식만 적는다.
_BMS_DATA = (
    ("배터리 충전 상태(BMS)", "A / 2", "%"),
    ("디스플레이 SOC", "(A / 2) - 2.5", "%"),
    ("배터리 팩 전류", "부호 있는 ((A * 256) + B) / 10", "A"),
    ("배터리 팩 전압", "((A * 256) + B) / 10", "V"),
    ("배터리 최대 온도", "A", "°C"),
    ("배터리 최소 온도", "A", "°C"),
    ("최대 셀 전압", "A / 50", "V"),
    ("최소 셀 전압", "A / 50", "V"),
)


def import_wecar_app() -> dict[str, int]:
    """앱의 전기차 읽기 명령과 공개된 전기차 고장코드를 넣는다. 다시 실행해도 한 건이다."""
    counts = {"commands": 0, "formulas": 0, "dtcs": 0}
    for item in _commands():
        if _command(item):
            counts["commands"] += 1
        for label, formula, unit in item.get("data") or ():
            if _formula(item["command"], label, formula, unit):
                counts["formulas"] += 1
    for item in DTCS:
        if item["type"] == "ev" and _dtc(item):
            counts["dtcs"] += 1
    db.session.commit()
    return counts


def _commands() -> list[dict]:
    rows = [
        {"header": "7E4", "command": "220101", "ecu": "BMS", "detail": "BMS 배터리 데이터(22 0101)",
         "description": "현대·기아 전기차 BMS. 충전 상태, 팩 전압·전류, 온도, 셀 전압, 동작시간, 절연저항을 읽는다.",
         "data": _BMS_DATA},
        {"header": "7E5", "command": "220101", "ecu": "BMS", "detail": "BMS 배터리 데이터(22 0101)",
         "description": "앱은 BMS 주소 7E5에도 22 0101을 보낸다. 읽는 값은 7E4와 같다.", "data": _BMS_DATA},
        {"header": "7E6", "command": "220101", "ecu": "고전압 제어", "detail": "고전압 제어 배터리 데이터(22 0101)",
         "description": "앱이 고전압 제어 주소 7E6에 보내는 22 0101.", "data": _BMS_DATA},
        {"header": "7E4", "command": "220105", "ecu": "BMS", "detail": "BMS 확장 데이터(22 0105)",
         "description": "앱은 동작시간과 절연저항을 읽는다. 배터리 건강 상태(SOH)는 이 서버가 22 0105에서 읽으며, 앱의 22 0101 SOH 계산은 쓰지 않는다."},
        {"header": "7E5", "command": "220105", "ecu": "BMS", "detail": "BMS 확장 데이터(22 0105)",
         "description": "앱이 BMS 주소 7E5에 보내는 22 0105."},
        {"header": "7E5", "command": "221050", "ecu": "BMS", "detail": "BMS 주행 가능 거리(22 1050)",
         "description": "앱이 BMS에서 먼저 읽는 주행 가능 거리.",
         "data": (("주행 가능 거리", "(A * 65536) + (B * 256) + C", "km"),)},
        {"header": "7C6", "command": "22B002", "ecu": "계기판", "detail": "계기판 주행거리(22 B002)",
         "description": "앱이 계기판에서 읽는 누적 주행거리. 차종마다 바이트 위치가 달라 3바이트 식을 초안으로 둔다.",
         "data": (("누적 주행거리", "(바이트6 * 65536) + (바이트7 * 256) + 바이트8", "km"),)},
        {"header": "7C6", "command": "22B004", "ecu": "계기판", "detail": "계기판 주행거리(22 B004)",
         "description": "B002로 못 읽을 때 앱이 이어서 보내는 주행거리 명령."},
        {"header": "7C6", "command": "22B001", "ecu": "계기판", "detail": "계기판 주행거리(22 B001)",
         "description": "B004로도 못 읽을 때 앱이 보내는 주행거리 명령."},
        {"header": "7C6", "command": "22B003", "ecu": "계기판", "detail": "계기판 확장 데이터(22 B003)",
         "description": "앱이 주행 가능 거리 대안으로 읽는 계기판 명령."},
    ]
    for header in _BMS:
        for command, label in _DTC_COMMANDS:
            rows.append({
                "header": header, "command": command, "ecu": "BMS" if header != "7E6" else "고전압 제어",
                "detail": f"{label}",
                "description": f"전기차 주소 {header}의 {label}. 제조사 전용 코드 뜻은 앱에 없고, 저장된 진단코드에서 찾는다.",
            })
    return rows


def _command(item: dict) -> bool:
    header, command = item["header"], item["command"]
    row = db.session.scalar(select(KnowledgeCommand).where(
        KnowledgeCommand.command == command,
        KnowledgeCommand.header == header,
        KnowledgeCommand.maker.is_(None),
        KnowledgeCommand.source == _SOURCE,
    ))
    created = row is None
    if created:
        row = KnowledgeCommand(command=command, header=header, source=_SOURCE, maker=None)
        db.session.add(row)
    if created or row.status == "draft":
        row.ecu_name = item["ecu"]
        row.detail_name = item["detail"][:200]
        row.label = item["detail"][:200]
        row.description = item["description"]
        row.source_detail = _DETAIL
        row.status = "draft"
        row.confidence = 0.6
    return created


def _formula(command: str, label: str, formula: str, unit: str) -> bool:
    row = db.session.scalar(select(KnowledgeFormula).where(
        KnowledgeFormula.command == command,
        KnowledgeFormula.label == label,
        KnowledgeFormula.maker.is_(None),
        KnowledgeFormula.source == _SOURCE,
    ))
    created = row is None
    if created:
        row = KnowledgeFormula(command=command, label=label, formula=formula, source=_SOURCE, maker=None)
        db.session.add(row)
    if created or row.status == "draft":
        row.formula = formula
        row.unit = unit
        row.detail_name = label
        row.source_detail = _DETAIL
        row.status = "draft"
        row.confidence = 0.6
    return created
