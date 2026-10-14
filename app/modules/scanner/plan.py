"""차량별 스캔 계획: 진단기에 보낼 명령 목록.

- 공통: SAE J1979(ISO 15031-5) 모드 01·02(프리즈 프레임)·03·07·09·0A. 모든 OBD2 차량(CAN, K-Line, J1850)에 쓴다.
  브라우저는 01 00·20·40… 지원 비트맵에 없는 PID와, 저장된 고장코드가 없을 때의 프리즈 프레임을 보내지 않는다.
- UDS(ISO 14229): 기능 주소로 19 02 09·19 02 04·19 15(위카 앱과 같음), ECU 주소마다 VIN(22 F190),
  고장코드(19 02 FF), 부품번호(22 F187), 소프트웨어 버전(22 F195).
- 제조사별: 현대·기아·제네시스 전기·하이브리드 BMS(7E4) 22 0101/0105와 구형 KWP 21 01/05.
  공개 자료(JejuSoul/OBD-PIDs-for-HKMC-EVs) 기준이고, 값은 적용 규칙 또는 참고 해석으로 읽는다.
- CAN 분석에서 적용한 규칙의 요청도 함께 보낸다.

이더넷 진단(DoIP, ISO 13400)은 OBD2 단자의 이더넷 핀과 전용 장비가 필요해 ELM327 계열로는 보낼 수 없다.
"""

from app.modules.canlab.service import capture_requests
from app.modules.scanner.obd import ECU_IDENT_DIDS, FREEZE_PIDS, PIDS, SUPPORT_PIDS

HKMC = ("현대", "기아", "제네시스", "HYUNDAI", "KIA", "GENESIS")
ELECTRIFIED = ("전기", "하이브리드", "수소", "EV", "HEV")

# ISO 15765-4 물리 주소 관례: 7E0 엔진, 7E1 변속기. 나머지는 제조사마다 다르다.
UDS_ECUS = {"7E0": "엔진(ECM)", "7E1": "변속기(TCM)", "7E2": "ECU 7E2", "7E3": "ECU 7E3",
            "7E4": "ECU 7E4", "7E5": "ECU 7E5", "7E6": "ECU 7E6", "7E7": "ECU 7E7"}
HKMC_ECUS = {"7E4": "배터리 관리(BMS)", "7C6": "계기판(CLU)", "7D1": "제동(ABS/ESC)", "7D4": "조향(MDPS)"}

DEFAULT_TIMEOUT_MS = 2000
SEARCH_TIMEOUT_MS = 12000
UDS_TIMEOUT_MS = 3000
DOIP_NOTE = "이더넷 진단(DoIP, ISO 13400)은 전용 장비가 필요해 이 스캔에서는 조회하지 않습니다."


def _is_hkmc_electrified(car: dict | None) -> bool:
    if not car:
        return False
    maker = str(car.get("diag_company") or "").upper()
    fuel = str(car.get("diag_fuel") or "").upper()
    return any(m.upper() in maker for m in HKMC) and any(f.upper() in fuel for f in ELECTRIFIED)


def _is_hkmc(car: dict | None) -> bool:
    maker = str((car or {}).get("diag_company") or "").upper()
    return any(m.upper() in maker for m in HKMC)


def build_plan(car: dict | None = None) -> dict:
    """steps: {id, group, label, header, command, timeout, optional, probe, bus}

    header가 없으면 OBD 기본 주소(브로드캐스트)로 보낸다. probe는 그 ECU의 첫 명령이고,
    응답이 없으면 같은 header의 나머지 명령을 건너뛴다. optional은 지원하지 않아도 오류로 보지 않는다.
    bus='can'은 CAN 차량에서만 보낸다.
    """
    steps: list[dict] = []

    def add(group: str, label: str, command: str, *, header: str | None = None,
            timeout: int = DEFAULT_TIMEOUT_MS, optional: bool = False, probe: bool = False,
            bus: str | None = None) -> None:
        steps.append({"id": len(steps) + 1, "group": group, "label": label, "header": header,
                      "command": command, "timeout": timeout, "optional": optional, "probe": probe,
                      "bus": bus})

    add("device", "배터리 전압(단말기 측정)", "ATRV")
    add("pid", "지원 항목 01–20 (통신 방식 찾기)", "0100", timeout=SEARCH_TIMEOUT_MS)
    add("device", "통신 방식", "ATDPN")
    for base in SUPPORT_PIDS[1:]:
        add("pid", f"지원 항목 {base + 1:02X}–{base + 0x20:02X}", f"01{base:02X}", optional=True)
    add("pid", "경고등·고장코드 수", "0101")
    for pid, info in PIDS.items():
        add("pid", info.label, f"01{pid:02X}", optional=True)

    add("vehicle", "차대번호(VIN)", "0902", optional=True)
    add("vehicle", "소프트웨어 보정 ID", "0904", optional=True)
    add("vehicle", "ECU 이름", "090A", optional=True)
    add("vehicle", "보정 검증 번호(CVN)", "0906", optional=True)

    add("dtc", "확정 고장코드", "03")
    add("dtc", "대기(미확정) 고장코드", "07", optional=True)
    add("dtc", "영구 고장코드", "0A", optional=True)
    add("freeze", "고장 당시 값: 원인 고장코드", "020200", optional=True)
    for pid in FREEZE_PIDS:
        add("freeze", f"고장 당시 값: {PIDS[pid].label}", f"02{pid:02X}00", optional=True)

    # 위카 앱과 같은 UDS 고장코드 조회(기능 주소로 모든 제어기에)
    add("uds", "전체 제어기 확정 고장코드(19 02 09)", "190209", timeout=UDS_TIMEOUT_MS, optional=True, bus="can")
    add("uds", "전체 제어기 대기 고장코드(19 02 04)", "190204", timeout=UDS_TIMEOUT_MS, optional=True, bus="can")
    add("uds", "전체 제어기 영구 고장코드(19 15)", "1915", timeout=UDS_TIMEOUT_MS, optional=True, bus="can")

    ecus = dict(UDS_ECUS)
    if _is_hkmc(car):
        ecus.update(HKMC_ECUS)
    for header, name in ecus.items():
        add("uds", f"{name} 차대번호(22 F190)", "22F190", header=header, timeout=UDS_TIMEOUT_MS,
            optional=True, probe=True, bus="can")
        add("uds", f"{name} 고장코드(19 02)", "1902FF", header=header, timeout=UDS_TIMEOUT_MS,
            optional=True, bus="can")
        for did, (_, label) in ECU_IDENT_DIDS.items():
            add("uds", f"{name} {label}(22 {did})", f"22{did}", header=header, timeout=UDS_TIMEOUT_MS,
                optional=True, bus="can")

    if _is_hkmc_electrified(car):
        for did in ("0101", "0105"):
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
