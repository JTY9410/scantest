"""차량별 스캔 계획: 진단기에 보낼 명령 목록.

- 공통: SAE J1979(ISO 15031-5) 모드 01·02(프리즈 프레임)·03·06·07·09·0A. 모든 OBD2 차량(CAN, K-Line, J1850)에 쓴다.
- UDS(ISO 14229): 기능 주소로 19 02 09·19 02 04·19 15(위카 앱과 같음), ECU 주소마다 VIN(22 F190),
  고장코드(19 02 FF), 고장 당시 데이터(19 04), 부품번호(22 F187), 소프트웨어 번호·버전(22 F188·F189·F195),
  공급자(22 F18A), 일련번호(22 F18C).
  진단 세션 변경(10)·보안 접근(27)·쓰기(2E)·루틴(31)은 보내지 않는다(기본 세션에서 읽기만).
- 제어기 순회(기본 스캔, 2026-10-18 대표 결정): 위카 앱 dev의 ECU 목록(공통 35쌍, 전동차·연료 미상은 32쌍 추가) 중
  위에서 보내지 않은 주소마다 19 02 FF 한 번(응답 없으면 바로 다음 주소). 짧은 대기(ATST19≈100ms)와 1초 시간 제한.
- 실주행거리(누적, 2026-10-18 대표 결정): 표준 01 A6이 기본, 현대·기아는 계기판 7C6 22 B002·B004·B001·B003,
  전동차는 7E5 22 1050도 읽는다(위카 앱 dev getClusterRange와 같은 명령, 해석은 obd.maker_odometer).
- 고장코드 지우기는 읽기 계획에 넣지 않는다. scanner/clear.py의 별도 계획(권한·확인·감사기록)으로만 보낸다.
- 제조사별: 현대·기아·제네시스 전기·하이브리드 BMS(7E4) 22 0101/0105와 구형 KWP 21 01/05,
  OBDb 정의가 있는 차종은 셀 전압 DID도 읽는다.
- CAN 분석에서 적용한 스캔 로직의 명령과 규칙의 요청도 함께 보낸다.

단계 조건(when)은 클라이언트(웹·앱·LTE)가 같은 규칙으로 평가한다.
- pid / pid02 / info09 / mid: 모드 01·02·09·06 지원 비트맵에 그 번호가 있을 때만(비트맵을 못 읽었으면 보냄)
- dtc: 저장된 고장코드가 있을 때만(01 01의 개수)
- bus='can' 단계는 CAN 차량에서만. header29가 있으면 29비트 CAN 차량에서 그 주소를 쓴다.
expand(웹·앱만): pids는 지원 PID를 CAN에서 6개씩 묶어 한 요청으로, mids는 지원 MID마다 06 xx,
dtcs는 같은 ECU의 19 02 응답 중 확정 고장코드마다 19 04 <DTC> FF(최대 limit개)로 펼친다.

이더넷 진단(DoIP, ISO 13400)은 OBD2 단자의 이더넷 핀과 전용 장비가 필요해 ELM327 계열로는 보낼 수 없다.
"""

import re

from app.modules.canlab.engine import obdb
from app.modules.canlab.service import capture_requests, logic_commands
from app.modules.scanner.obd import ECU_IDENT_DIDS, FREEZE_PIDS, MODE06_RANGES, PIDS, SUPPORT_PIDS

HKMC = ("현대", "기아", "제네시스", "HYUNDAI", "KIA", "GENESIS")
ELECTRIFIED = ("전기", "하이브리드", "수소", "EV", "HEV")

# ISO 15765-4 물리 주소: 11비트 7E0 엔진·7E1 변속기, 29비트는 18DA<대상>F1(엔진 10, 변속기 18).
# 나머지는 제조사마다 달라 11비트만 쓴다.
UDS_ECUS = {"7E0": ("엔진(ECM)", "18DA10F1"), "7E1": ("변속기(TCM)", "18DA18F1"), "7E2": ("ECU 7E2", None),
            "7E3": ("ECU 7E3", None), "7E4": ("ECU 7E4", None), "7E5": ("ECU 7E5", None),
            "7E6": ("ECU 7E6", None), "7E7": ("ECU 7E7", None)}
HKMC_ECUS = {"7E4": ("배터리 관리(BMS)", None), "7C6": ("계기판(CLU)", None), "7D1": ("제동(ABS/ESC)", None),
             "7D4": ("조향(MDPS)", None)}

DEFAULT_TIMEOUT_MS = 2000
SEARCH_TIMEOUT_MS = 30000
UDS_TIMEOUT_MS = 3000
SNAPSHOT_LIMIT = 3
DOIP_NOTE = "이더넷 진단(DoIP, ISO 13400)은 전용 장비가 필요해 이 스캔에서는 조회하지 않습니다."

# 제조사별 제한사항 안내 (2026-10-24 연구 결과)
RESTRICTED_MANUFACTURERS = {
    "TESLA": "Tesla 차량은 CAN 게이트웨이 보호로 인해 OBD2 포트를 통한 제한적인 진단만 가능합니다. "
             "표준 OBD2 명령어(모드 01, 03, 07, 09 일부)만 응답하며, 배터리 BMS 데이터는 접근할 수 없습니다. "
             "Tesla API를 통한 클라우드 기반 데이터 수집을 권장합니다.",
    "BYD": "BYD 차량(2020년 이후)은 강화된 게이트웨이 보안으로 인해 표준 OBD2 명령어 외에는 제한적입니다. "
           "BMS 데이터 접근이 어려우며, BYD 전용 진단 장비가 필요할 수 있습니다. "
           "LFP 배터리 특성상 SOC/SOH 추정이 더 어렵습니다.",
    "POLESTAR": "Polestar 차량은 Volvo 플랫폼 기반으로 강화된 보안이 적용되어 있습니다. "
                "서비스 모드 진입이 필요하며, 표준 OBD2 명령어 외의 제조사 전용 명령어는 제한됩니다.",
    "VOLVO": "Volvo 전기차(XC40/C40 Recharge)는 VIDA 전용 진단 시스템이 필요합니다. "
             "OBD2 표준 명령어 외에는 접근이 제한되며, BMS 데이터는 제한적으로만 조회 가능합니다."
}
INFO09 = (("02", "차대번호(VIN)"), ("04", "소프트웨어 보정 ID"), ("06", "보정 검증 번호(CVN)"),
          ("0A", "ECU 이름"), ("08", "주행 중 진단 실행 비율(가솔린)"), ("0B", "주행 중 진단 실행 비율(디젤)"))
# 위카 앱 main(793889c) 콘솔 프리셋(ATSH7DF~7E8, 1902FFFFFF)은 넣지 않는다.
# - ATSH 단독 단계: 드라이버가 단계마다 주소를 정하므로 응답이 없고, 드라이버가 기억한 주소와 실제 주소가 어긋난다.
#   ATSH7E8은 엔진의 '응답' 주소라 요청 주소로 쓰면 안 된다.
# - 1902FFFFFF: 19 02의 인자는 상태 마스크 1바이트라 길이 오류(NRC 13)다. 같은 내용은 190209·1902FF로 이미 읽는다.

# 제어기 순회 목록: 위카 앱 dev(ble_connect_service.dart, e118ae4) commonPairs·evExtraPairs 그대로.
# 응답 주소는 요청+8, 717만 71D(obd-plan.js REPLY_OVERRIDE). 벤츠 목록은 앱에서도 꺼져 있어 넣지 않는다.
SWEEP_COMMON = (
    "7A0", "7A1", "7A2", "7A3", "7A4", "7A5", "7A6", "7A7",
    "7B0", "7B1", "7B2", "7B3", "7B4", "7B5", "7B6", "7B7",
    "7C0", "7C1", "7C2", "7C3", "7C4", "7C5", "7C6",
    "7D0", "7D1", "7D2", "7D3", "7D4", "7D5", "7D6", "7D7",
    "7E0", "7E1", "7E2", "7E4",
)
SWEEP_EV = (
    "7E3", "7E5", "7E6", "7E7", "5E0", "5E2", "5A6",
    "700", "701", "703", "705", "706", "707", "717", "725",
    "730", "731", "733", "735", "736", "741", "743", "744",
    "760", "761", "762", "766", "770", "777", "781", "795", "797",
)
SWEEP_TIMEOUT_MS = 1000
SWEEP_ST = "19"  # ELM327 ATST 단위 4ms → 0x19 = 100ms. 응답 없는 제어기를 빨리 넘긴다.
# 실주행거리(누적) DID. 위카 앱 dev getClusterRange 순서.
CLUSTER_ODO_DIDS = ("B002", "B004", "B001", "B003")
BMS_ODO_DID = "1050"
_BLOCKED = {"10", "27", "2E", "31"}
_FOREIGN_OBDB = {"TESLA", "AUDI", "BMW", "LEXUS"}


def _blocked(command: str) -> bool:
    compact = re.sub(r"\s+", "", command or "").upper()
    return len(compact) >= 2 and not compact.startswith("AT") and compact[:2] in _BLOCKED


def _maker(car: dict | None) -> str:
    return str((car or {}).get("diag_company") or "").upper()


def _is_hkmc(car: dict | None) -> bool:
    return any(m.upper() in _maker(car) for m in HKMC)


def _is_hkmc_electrified(car: dict | None) -> bool:
    fuel = str((car or {}).get("diag_fuel") or "").upper()
    return _is_hkmc(car) and any(f.upper() in fuel for f in ELECTRIFIED)


def _is_electrified(car: dict | None) -> bool:
    """전기·하이브리드·수소. 연료를 모르면(조회 실패 등) 전동차일 수 있다고 본다."""
    fuel = str((car or {}).get("diag_fuel") or "").upper()
    return not fuel or any(f.upper() in fuel for f in ELECTRIFIED)


def sweep_headers(car: dict | None, skip: set[str] | None = None, learned: list[dict] | None = None) -> list[str]:
    """제어기 순회 주소. 이전 스캔에서 응답한 주소(learned)를 앞에 두고, 이미 계획한 주소(skip)는 뺀다."""
    headers = list(SWEEP_COMMON) + (list(SWEEP_EV) if _is_electrified(car) else [])
    headers = [h for h in dict.fromkeys(headers) if h not in (skip or set())]
    hits: dict[str, int] = {}
    for item in learned or []:
        if item.get("header") in headers:
            hits[item["header"]] = max(hits.get(item["header"], 0), int(item.get("hits") or 0))
    return sorted(headers, key=lambda h: (-hits.get(h, 0), headers.index(h)))


def build_plan(car: dict | None = None, *, expand: bool = False) -> dict:
    """steps: {id, group, label, header, header29, command, timeout, optional, probe, bus, when, expand…}

    header가 없으면 OBD 기본 주소(브로드캐스트)로 보낸다. probe는 그 ECU의 첫 명령이고,
    응답이 없으면 같은 header의 나머지 명령을 건너뛴다. optional은 지원하지 않아도 오류로 보지 않는다.
    expand=False(LTE 단말기)는 펼치기 단계 없이 PID마다 한 단계씩 준다.
    """
    steps: list[dict] = []

    def add(group: str, label: str, command: str, *, header: str | None = None, header29: str | None = None,
            timeout: int = DEFAULT_TIMEOUT_MS, optional: bool = False, probe: bool = False,
            bus: str | None = None, when: dict | None = None, **extra) -> None:
        step = {"id": len(steps) + 1, "group": group, "label": label, "header": header, "command": command,
                "timeout": timeout, "optional": optional, "probe": probe, "bus": bus}
        if header29:
            step["header29"] = header29
        if when:
            step["when"] = when
        steps.append(step | extra)

    add("device", "배터리 전압(단말기 측정)", "ATRV")
    add("pid", "지원 항목 01–20 (통신 방식 찾기)", "0100", timeout=SEARCH_TIMEOUT_MS)
    add("device", "통신 방식", "ATDPN")
    for base in SUPPORT_PIDS[1:]:
        add("pid", f"지원 항목 {base + 1:02X}–{base + 0x20:02X}", f"01{base:02X}", optional=True,
            when={"pid": f"{base:02X}"})
    add("pid", "경고등·고장코드 수·배출 점검 상태", "0101")
    add("pid", "이번 주행 배출 점검 상태", "0141", optional=True, when={"pid": "41"})
    live = [pid for pid in PIDS if pid != 0x41]
    if expand:
        add("pid", "실시간 데이터", "01", optional=True, expand="pids", pids=[f"{pid:02X}" for pid in live])
    else:
        for pid in live:
            add("pid", PIDS[pid].label, f"01{pid:02X}", optional=True, when={"pid": f"{pid:02X}"})

    add("vehicle", "지원 차량 정보 항목", "0900", optional=True)
    for info, label in INFO09:
        add("vehicle", label, f"09{info}", optional=True, when={"info09": info})

    add("dtc", "확정 고장코드", "03")
    add("dtc", "대기(미확정) 고장코드", "07", optional=True)
    add("dtc", "영구 고장코드", "0A", optional=True)
    add("freeze", "고장 당시 값: 지원 항목", "020000", optional=True, when={"dtc": True})
    add("freeze", "고장 당시 값: 원인 고장코드", "020200", optional=True, when={"dtc": True})
    for pid in FREEZE_PIDS:
        add("freeze", f"고장 당시 값: {PIDS[pid].label}", f"02{pid:02X}00", optional=True,
            when={"dtc": True, "pid02": f"{pid:02X}"})

    if expand:
        add("monitor", "배출 부품 점검 결과: 지원 항목", "0600", optional=True, bus="can")
        for base in MODE06_RANGES[1:]:
            add("monitor", f"배출 부품 점검 결과: 지원 항목 {base + 1:02X}–{base + 0x20:02X}", f"06{base:02X}",
                optional=True, bus="can", when={"mid": f"{base:02X}"})
        add("monitor", "배출 부품 점검 결과", "06", optional=True, bus="can", expand="mids")

    add("uds", "전체 제어기 확정 고장코드(19 02 09)", "190209", timeout=UDS_TIMEOUT_MS, optional=True, bus="can")
    add("uds", "전체 제어기 대기 고장코드(19 02 04)", "190204", timeout=UDS_TIMEOUT_MS, optional=True, bus="can")
    add("uds", "전체 제어기 영구 고장코드(19 15)", "1915", timeout=UDS_TIMEOUT_MS, optional=True, bus="can")

    if _is_hkmc(car):
        # 실주행거리. 7C6의 22F190(응답 확인) 단계보다 먼저 보내 F190에 답하지 않는 계기판도 읽는다.
        for did in CLUSTER_ODO_DIDS:
            add("maker", f"계기판(CLU) 실주행거리(22 {did})", f"22{did}", header="7C6",
                timeout=UDS_TIMEOUT_MS, optional=True, bus="can")
        if _is_electrified(car):
            add("maker", f"모터·BMS 실주행거리(22 {BMS_ODO_DID})", f"22{BMS_ODO_DID}", header="7E5",
                timeout=UDS_TIMEOUT_MS, optional=True, bus="can")

    ecus = dict(UDS_ECUS)
    if _is_hkmc(car):
        ecus.update(HKMC_ECUS)
    for header, (name, header29) in ecus.items():
        common = {"header": header, "header29": header29, "timeout": UDS_TIMEOUT_MS, "optional": True,
                  "bus": "can"}
        add("uds", f"{name} 차대번호(22 F190)", "22F190", probe=True, **common)
        add("uds", f"{name} 고장코드(19 02)", "1902FF", **common)
        if expand:
            add("uds", f"{name} 고장 당시 데이터(19 04)", "1904", expand="dtcs", limit=SNAPSHOT_LIMIT, **common)
        for did, (_, label) in ECU_IDENT_DIDS.items():
            add("uds", f"{name} {label}(22 {did})", f"22{did}", **common)

    if _is_hkmc_electrified(car):
        for did in obdb.plan_dids(car):
            add("maker", f"BMS 배터리 데이터(22 {did})", f"22{did}", header="7E4",
                timeout=UDS_TIMEOUT_MS, optional=True, bus="can")
        for local_id in ("01", "05"):
            add("maker", f"BMS 배터리 데이터(구형 21 {local_id})", f"21{local_id}", header="7E4",
                timeout=UDS_TIMEOUT_MS, optional=True, bus="can")

    matched = obdb.match(car)
    repo = str((matched or {}).get("repo") or "")
    if repo.split("-", 1)[0].upper() in _FOREIGN_OBDB:
        header = matched.get("request_id") or "7E4"
        for did in matched.get("dids") or []:
            add("maker", f"OBDb {repo} (22 {did})", f"22{did}", header=header,
                timeout=UDS_TIMEOUT_MS, optional=True, bus="can")

    from app.modules.scanner.learn import learned_requests

    learned = learned_requests(car)
    for header in sweep_headers(car, {s["header"] for s in steps if s["header"]}, learned):
        common = {"header": header, "timeout": SWEEP_TIMEOUT_MS, "optional": True, "bus": "can",
                  "sweep": True, "st": SWEEP_ST}
        add("uds", f"제어기 {header} 고장코드(19 02)", "1902FF", probe=True, **common)
        if expand:
            add("uds", f"제어기 {header} 고장 당시 데이터(19 04)", "1904", expand="dtcs", limit=SNAPSHOT_LIMIT,
                **common)

    planned = {(s["header"], s["command"]) for s in steps}
    from flask import has_app_context

    from app.modules.knowledge.service import scan_commands

    maker_name = str((car or {}).get("diag_company") or "").strip() or None
    knowledge = scan_commands(maker_name) if has_app_context() else []
    for request in knowledge:
        header = request["header"]
        if _blocked(request["command"]) or (header, request["command"]) in planned:
            continue
        planned.add((header, request["command"]))
        add("knowledge", f"검증된 명령 {request['label']}", request["command"],
            header=header, timeout=UDS_TIMEOUT_MS, optional=True, bus="can" if header else None)
    for request in learned:
        header = request["header"]
        if _blocked(request["command"]) or (header, request["command"]) in planned:
            continue
        planned.add((header, request["command"]))
        add("learned", f"이전 스캔에서 응답한 명령 {request['command']}", request["command"],
            header=header, timeout=UDS_TIMEOUT_MS, optional=True, bus="can" if header else None)
    logic = {(c["header"], c["command"]): c for c in logic_commands(car or None)}
    for request in capture_requests(car or None):
        # 기능 주소(7DF) 요청은 계획의 기본 주소(header 없음)와 같다.
        header = None if request["header"] == "7DF" else request["header"]
        if _blocked(request["command"]) or (header, request["command"]) in planned:
            continue
        planned.add((header, request["command"]))
        command = logic.get((request["header"], request["command"]))
        label = (f"스캔 로직: {command['label']}" if command
                 else f"적용 규칙 요청 {request['header']} {request['command']}")
        add("rule", label, request["command"], header=header, timeout=UDS_TIMEOUT_MS, optional=True,
            bus="can" if header else None)

    # 제조사별 제한사항 체크
    notes = [DOIP_NOTE]
    maker_name = str((car or {}).get("diag_company") or "").upper()
    for restricted_maker, warning in RESTRICTED_MANUFACTURERS.items():
        if restricted_maker in maker_name or maker_name in restricted_maker:
            notes.append(f"[{restricted_maker} 제한사항] {warning}")
            break
    
    return {"steps": steps, "notes": notes}
