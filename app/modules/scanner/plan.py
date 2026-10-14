"""차량별 스캔 계획: 진단기에 보낼 명령 목록.

- 공통: SAE J1979(ISO 15031-5) 모드 01·02(프리즈 프레임)·03·06·07·09·0A. 모든 OBD2 차량(CAN, K-Line, J1850)에 쓴다.
- UDS(ISO 14229): 기능 주소로 19 02 09·19 02 04·19 15(위카 앱과 같음), ECU 주소마다 VIN(22 F190),
  고장코드(19 02 FF), 고장 당시 데이터(19 04), 부품번호(22 F187), 소프트웨어 버전(22 F195).
  진단 세션 변경(10)·보안 접근(27)·쓰기(2E)·루틴(31)은 보내지 않는다(기본 세션에서 읽기만).
- 제조사별: 현대·기아·제네시스 전기·하이브리드 BMS(7E4) 22 0101/0105와 구형 KWP 21 01/05,
  OBDb 정의가 있는 차종은 셀 전압 DID도 읽는다.
- CAN 분석에서 적용한 규칙의 요청도 함께 보낸다.

단계 조건(when)은 클라이언트(웹·앱·LTE)가 같은 규칙으로 평가한다.
- pid / pid02 / info09 / mid: 모드 01·02·09·06 지원 비트맵에 그 번호가 있을 때만(비트맵을 못 읽었으면 보냄)
- dtc: 저장된 고장코드가 있을 때만(01 01의 개수)
- bus='can' 단계는 CAN 차량에서만. header29가 있으면 29비트 CAN 차량에서 그 주소를 쓴다.
expand(웹·앱만): pids는 지원 PID를 CAN에서 6개씩 묶어 한 요청으로, mids는 지원 MID마다 06 xx,
dtcs는 같은 ECU의 19 02 응답 중 확정 고장코드마다 19 04 <DTC> FF(최대 limit개)로 펼친다.

이더넷 진단(DoIP, ISO 13400)은 OBD2 단자의 이더넷 핀과 전용 장비가 필요해 ELM327 계열로는 보낼 수 없다.
"""

from app.modules.canlab.engine import obdb
from app.modules.canlab.service import capture_requests
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
INFO09 = (("02", "차대번호(VIN)"), ("04", "소프트웨어 보정 ID"), ("06", "보정 검증 번호(CVN)"),
          ("0A", "ECU 이름"), ("08", "주행 중 진단 실행 비율(가솔린)"), ("0B", "주행 중 진단 실행 비율(디젤)"))


def _maker(car: dict | None) -> str:
    return str((car or {}).get("diag_company") or "").upper()


def _is_hkmc(car: dict | None) -> bool:
    return any(m.upper() in _maker(car) for m in HKMC)


def _is_hkmc_electrified(car: dict | None) -> bool:
    fuel = str((car or {}).get("diag_fuel") or "").upper()
    return _is_hkmc(car) and any(f.upper() in fuel for f in ELECTRIFIED)


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

    planned = {(s["header"], s["command"]) for s in steps}
    for request in capture_requests():
        if (request["header"], request["command"]) not in planned:
            add("rule", f"적용 규칙 요청 {request['header']} {request['command']}", request["command"],
                header=request["header"], timeout=UDS_TIMEOUT_MS, optional=True, bus="can")

    return {"steps": steps, "notes": [DOIP_NOTE]}
