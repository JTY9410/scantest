"""OBD2(SAE J1979)·UDS(ISO 14229) 응답 해석.

요청 하나의 ELM327 응답 문자열을 ECU별 메시지로 나누고, 긍정·부정 응답과 단말기 오류를 가린 뒤
서비스별로 값을 읽는다. CAN(ISO 15765-4)은 ISO-TP로 합치고, K-Line(ISO 9141-2·14230-4)과
J1850은 3바이트 헤더와 체크섬을 뗀다.

공식 출처(공개): SAE J1979/ISO 15031-5 요약(위키백과 'OBD-II PIDs'), ELM327 데이터시트의 오류 문구.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from app.modules.canlab.engine.frames import Frame, reply_frames
from app.modules.canlab.engine.isotp import reassemble
from app.modules.canlab.engine.uds import NEGATIVE_CODES, RESPONSE_PENDING, format_dtc

# ATDPN 응답(앞의 A는 자동 선택) → (이름, 버스)
PROTOCOLS = {
    "1": ("SAE J1850 PWM (41.6 kbaud)", "serial"),
    "2": ("SAE J1850 VPW (10.4 kbaud)", "serial"),
    "3": ("ISO 9141-2 (K-Line)", "serial"),
    "4": ("ISO 14230-4 KWP (5 baud 초기화)", "serial"),
    "5": ("ISO 14230-4 KWP (빠른 초기화)", "serial"),
    "6": ("ISO 15765-4 CAN (11비트, 500 kbaud)", "can11"),
    "7": ("ISO 15765-4 CAN (29비트, 500 kbaud)", "can29"),
    "8": ("ISO 15765-4 CAN (11비트, 250 kbaud)", "can11"),
    "9": ("ISO 15765-4 CAN (29비트, 250 kbaud)", "can29"),
    "A": ("SAE J1939 CAN (29비트, 250 kbaud)", "can29"),
    "B": ("사용자 정의 CAN 1", "can11"),
    "C": ("사용자 정의 CAN 2", "can11"),
}

# ELM327 오류 문구 → (상태, 안내). 위에서부터 먼저 맞는 것을 쓴다.
ELM_ERRORS: tuple[tuple[str, str, str], ...] = (
    ("NO DATA", "no_data", "응답 없음: 이 차량·ECU가 지원하지 않거나 시동(ON)이 꺼져 있습니다."),
    ("UNABLE TO CONNECT", "device_error", "차량 통신 방식을 찾지 못했습니다(UNABLE TO CONNECT). 시동을 ON으로 두고 단자 연결을 확인하세요."),
    ("BUS INIT", "device_error", "K-Line 초기화 실패(BUS INIT ERROR). 시동 ON 상태에서 다시 시도하세요."),
    ("CAN ERROR", "device_error", "CAN 통신 오류(CAN ERROR): 통신 속도가 맞지 않거나 시동이 꺼져 있습니다."),
    ("BUS BUSY", "device_error", "차량 통신선이 너무 바쁩니다(BUS BUSY). 잠시 뒤 다시 시도하세요."),
    ("BUS ERROR", "device_error", "통신선 오류(BUS ERROR): 배선 단락 또는 단말기 문제입니다."),
    ("FB ERROR", "device_error", "신호 되읽기 오류(FB ERROR): 배선 또는 단말기 문제입니다."),
    ("DATA ERROR", "device_error", "응답 데이터 오류(DATA ERROR): 체크섬·형식이 맞지 않습니다."),
    ("BUFFER FULL", "device_error", "단말기 버퍼가 가득 찼습니다(BUFFER FULL). 응답이 너무 깁니다."),
    ("RX ERROR", "device_error", "수신 오류(RX ERROR): 응답을 끝까지 받지 못했습니다."),
    ("STOPPED", "device_error", "단말기가 명령을 중단했습니다(STOPPED). 응답 중에 다음 입력이 들어왔습니다."),
    ("LV RESET", "device_error", "전압 저하로 단말기가 재시작했습니다(LV RESET). 12V 배터리를 확인하세요."),
    ("ACT ALERT", "device_error", "통신이 없어 단말기가 절전 대기에 들어갔습니다(ACT ALERT)."),
)
_ERR_CODE = re.compile(r"^ERR\d+$")
_NOISE = re.compile(r"^(SEARCHING\.*|BUS INIT:?\s*\.*\s*OK|OK|>)$")

STATUS_LABELS = {
    "ok": "성공", "no_data": "응답 없음", "unsupported": "지원 안 함", "negative": "부정 응답",
    "timeout": "시간 초과", "device_error": "단말기 오류", "parse_error": "해석 오류",
    "server_error": "서버 오류", "skipped": "건너뜀", "disconnected": "연결 끊김",
    "lookup_error": "조회 실패", "client_error": "화면 오류", "pdf_error": "PDF 오류", "pending": "응답 지연",
    "logic_error": "로직 문제",
}
# 이 ECU가 그 요청을 지원하지 않는다는 뜻의 NRC(지원 안 함 서비스·하위기능·DID, 기본 세션에서 지원 안 함)
UNSUPPORTED_NRC = {0x11, 0x12, 0x31, 0x7E, 0x7F}


def protocol_of(reply: str | None) -> tuple[str | None, str, str | None]:
    """ATDPN 응답 → (코드, 이름, 버스). 'A6'은 자동 선택된 6번이다."""
    for token in reversed(re.split(r"[\s>]+", (reply or "").upper())):
        if re.fullmatch(r"A?[1-9A-C]", token):
            code = token[-1]
            name, bus = PROTOCOLS[code]
            return code, name, bus
    return None, "알 수 없음", None


def elm_error(reply: str | None) -> tuple[str, str] | None:
    lines = [line.strip().upper() for line in re.split(r"[\r\n>]+", reply or "") if line.strip()]
    for line in lines:
        if line == "?":
            return "device_error", "단말기가 명령을 이해하지 못했습니다(?). 지원하지 않는 명령입니다."
        if _ERR_CODE.match(line):
            return "device_error", f"단말기 내부 오류({line})."
        for pattern, status, message in ELM_ERRORS:
            if pattern in line:
                return status, message
    return None


def messages(reply: str | None, bus: str | None) -> tuple[dict[int, list[bytes]], int]:
    """ECU(응답 주소)별 메시지 목록과 끝까지 받지 못한 메시지 수."""
    frames = reply_frames(reply or "", bus)
    result: dict[int, list[bytes]] = {}
    incomplete = 0
    can = [Frame(float(i), f.source, f.data) for i, f in enumerate(frames) if f.bus == "can"]
    for message in reassemble(can):
        if message.complete:
            result.setdefault(message.can_id, []).append(message.payload)
        else:
            incomplete += 1
    for frame in frames:
        if frame.bus == "serial" and frame.data:
            result.setdefault(frame.source, []).append(frame.data)
    return result, incomplete


@dataclass
class Outcome:
    status: str
    message: str
    positive: dict[int, list[bytes]] = field(default_factory=dict)
    negative: dict[int, int] = field(default_factory=dict)


def _echo(command: bytes) -> bytes:
    """긍정 응답이 되풀이하는 요청 바이트(서비스 다음). 모드 03·07·0A는 없다."""
    service = command[0]
    if service in (0x01, 0x06, 0x09, 0x21, 0x19):
        return command[1:2]
    if service in (0x02, 0x22):
        return command[1:3]
    return b""


def _answers(command: bytes, payload: bytes) -> bool:
    if payload[:1] != bytes([command[0] + 0x40]):
        return False
    if command[0] == 0x01 and len(command) > 2:
        return len(payload) > 1 and payload[1] in command[1:]
    echo = _echo(command)
    return payload[1 : 1 + len(echo)] == echo


def evaluate(command_hex: str, reply: str | None, bus: str | None, client_error: str | None = None) -> Outcome:
    """요청 하나의 결과. client_error는 브라우저·앱이 남긴 오류(timeout, disconnected, write 등)."""
    if client_error == "disconnected":
        return Outcome("disconnected", "진단기 연결이 끊겨 이 명령을 보내지 못했습니다.")
    if client_error == "timeout" or (reply is None and client_error is None):
        return Outcome("timeout", "응답 시간 초과: 단말기가 정해진 시간 안에 답하지 않았습니다.")
    if client_error:
        return Outcome("device_error", f"전송 실패: {client_error}")

    command = bytes.fromhex(command_hex)
    service = command[0]
    found, incomplete = messages(reply, bus)
    outcome = Outcome("no_data", "")
    pending = False
    for ecu, payloads in found.items():
        for payload in payloads:
            if _answers(command, payload):
                outcome.positive.setdefault(ecu, []).append(payload)
            elif len(payload) >= 3 and payload[0] == 0x7F and payload[1] == service:
                if payload[2] == RESPONSE_PENDING:
                    pending = True
                else:
                    outcome.negative[ecu] = payload[2]

    if outcome.positive:
        outcome.status, outcome.message = "ok", f"{len(outcome.positive)}개 ECU 응답"
    elif outcome.negative:
        outcome.status = "unsupported" if set(outcome.negative.values()) <= UNSUPPORTED_NRC else "negative"
        outcome.message = ", ".join(
            f"{_ecu(ecu)} NRC {code:02X} {NEGATIVE_CODES.get(code, '기타 거부')}"
            for ecu, code in outcome.negative.items())
    elif pending:
        outcome.status = "pending"
        outcome.message = "ECU가 '응답 대기(NRC 78)'만 보내고 정해진 시간 안에 최종 응답을 주지 않았습니다."
    elif error := elm_error(reply):
        outcome.status, outcome.message = error
    elif incomplete:
        outcome.status, outcome.message = "parse_error", f"여러 프레임 응답 {incomplete}건을 끝까지 받지 못했습니다."
    else:
        text = re.sub(r"\s+", " ", reply or "").strip()
        outcome.message = f"해석할 수 있는 응답이 없습니다: {text[:60]}" if text else "빈 응답"
    return outcome


def _ecu(address: int) -> str:
    return f"{address:03X}" if address > 0xFF else f"{address:02X}"


# ---- 모드 01 현재 데이터 -----------------------------------------------------

@dataclass(frozen=True)
class Pid:
    key: str
    label: str
    unit: str
    size: int
    decode: Callable[[bytes], float | str]


def _u16(d: bytes) -> int:
    return (d[0] << 8) | d[1]


FUEL_TYPES = {1: "휘발유", 2: "메탄올", 3: "에탄올", 4: "경유", 5: "LPG", 6: "CNG", 7: "프로판", 8: "전기",
              9: "바이퓨얼(휘발유)", 17: "하이브리드(휘발유)", 18: "하이브리드(에탄올)", 19: "하이브리드(경유)",
              20: "하이브리드(전기)", 21: "하이브리드(혼합)", 22: "하이브리드(회생)"}

FUEL_SYSTEM = {1: "개회로(엔진 온도 부족)", 2: "폐회로(산소센서 사용)", 4: "개회로(부하·감속)",
               8: "개회로(시스템 고장)", 16: "폐회로(피드백 이상)"}
OBD_STANDARDS = {1: "OBD-II(CARB)", 2: "OBD(EPA)", 3: "OBD, OBD-II", 4: "OBD-I", 5: "OBD 미적용", 6: "EOBD",
                 7: "EOBD, OBD-II", 8: "EOBD, OBD", 9: "EOBD, OBD, OBD-II", 10: "JOBD", 11: "JOBD, OBD-II",
                 12: "JOBD, EOBD", 13: "JOBD, EOBD, OBD-II", 17: "EMD", 18: "EMD+", 19: "HD OBD-C",
                 20: "HD OBD", 21: "WWH OBD", 23: "HD EOBD-I", 24: "HD EOBD-I N", 25: "HD EOBD-II",
                 26: "HD EOBD-II N", 28: "OBDBr-1", 29: "OBDBr-2", 30: "KOBD(한국)", 31: "IOBD I", 32: "IOBD II",
                 33: "HD EOBD-IV"}


def _pct(d: bytes) -> float:
    return round(d[0] * 100 / 255, 1)


def _trim(d: bytes) -> float:
    return round((d[0] - 128) * 100 / 128, 1)


def _o2(name: str) -> Pid:
    return Pid(f"o2_{name.lower()}", f"산소센서 {name} 전압", "V", 2, lambda d: round(d[0] / 200, 3))


def _cat(name: str) -> Pid:
    return Pid(f"catalyst_temp_{name.lower()}", f"촉매 온도 {name}", "°C", 2, lambda d: round(_u16(d) / 10 - 40, 1))


# SAE J1979 모드 01 공식(공개 요약: 위키백과 'OBD-II PIDs'). size는 데이터 바이트 수.
PIDS: dict[int, Pid] = {
    0x03: Pid("fuel_system", "연료 계통 상태", "", 2, lambda d: FUEL_SYSTEM.get(d[0], f"코드 {d[0]}")),
    0x04: Pid("engine_load", "엔진 부하", "%", 1, _pct),
    0x05: Pid("coolant_temp", "냉각수 온도", "°C", 1, lambda d: d[0] - 40),
    0x06: Pid("stft_b1", "단기 연료 보정(뱅크1)", "%", 1, _trim),
    0x07: Pid("ltft_b1", "장기 연료 보정(뱅크1)", "%", 1, _trim),
    0x08: Pid("stft_b2", "단기 연료 보정(뱅크2)", "%", 1, _trim),
    0x09: Pid("ltft_b2", "장기 연료 보정(뱅크2)", "%", 1, _trim),
    0x0A: Pid("fuel_pressure", "연료 압력", "kPa", 1, lambda d: d[0] * 3),
    0x0B: Pid("map", "흡기 매니폴드 압력", "kPa", 1, lambda d: d[0]),
    0x0C: Pid("rpm", "엔진 회전수", "rpm", 2, lambda d: _u16(d) / 4),
    0x0D: Pid("speed", "차속", "km/h", 1, lambda d: d[0]),
    0x0E: Pid("timing_advance", "점화 진각", "°", 1, lambda d: d[0] / 2 - 64),
    0x0F: Pid("intake_temp", "흡기 온도", "°C", 1, lambda d: d[0] - 40),
    0x10: Pid("maf", "흡입 공기량(MAF)", "g/s", 2, lambda d: round(_u16(d) / 100, 2)),
    0x11: Pid("throttle", "스로틀 개도", "%", 1, _pct),
    0x14: _o2("B1S1"), 0x15: _o2("B1S2"), 0x16: _o2("B1S3"), 0x17: _o2("B1S4"),
    0x18: _o2("B2S1"), 0x19: _o2("B2S2"), 0x1A: _o2("B2S3"), 0x1B: _o2("B2S4"),
    0x1C: Pid("obd_standard", "OBD 규격", "", 1, lambda d: OBD_STANDARDS.get(d[0], f"코드 {d[0]}")),
    0x1F: Pid("run_time", "시동 후 경과 시간", "s", 2, _u16),
    0x21: Pid("distance_mil", "경고등 켜진 뒤 주행거리", "km", 2, _u16),
    0x22: Pid("fuel_rail_pressure", "연료 레일 압력(진공 기준)", "kPa", 2, lambda d: round(_u16(d) * 0.079, 1)),
    0x23: Pid("fuel_rail_gauge", "연료 레일 압력(게이지)", "kPa", 2, lambda d: _u16(d) * 10),
    0x2C: Pid("egr_commanded", "EGR 목표 개도", "%", 1, _pct),
    0x2D: Pid("egr_error", "EGR 오차", "%", 1, _trim),
    0x2E: Pid("evap_purge", "증발가스 퍼지 목표", "%", 1, _pct),
    0x2F: Pid("fuel_level", "연료 잔량", "%", 1, _pct),
    0x30: Pid("warmups_cleared", "고장코드 삭제 후 워밍업 횟수", "회", 1, lambda d: d[0]),
    0x31: Pid("distance_cleared", "고장코드 삭제 후 주행거리", "km", 2, _u16),
    0x33: Pid("baro", "대기압", "kPa", 1, lambda d: d[0]),
    0x3C: _cat("B1S1"), 0x3D: _cat("B2S1"), 0x3E: _cat("B1S2"), 0x3F: _cat("B2S2"),
    0x42: Pid("module_voltage", "제어 모듈 전압", "V", 2, lambda d: round(_u16(d) / 1000, 2)),
    0x43: Pid("absolute_load", "절대 부하", "%", 2, lambda d: round(_u16(d) * 100 / 255, 1)),
    0x44: Pid("commanded_lambda", "목표 공연비(람다)", "λ", 2, lambda d: round(_u16(d) * 2 / 65536, 3)),
    0x45: Pid("relative_throttle", "상대 스로틀 개도", "%", 1, _pct),
    0x46: Pid("ambient_temp", "외기 온도", "°C", 1, lambda d: d[0] - 40),
    0x47: Pid("throttle_b", "스로틀 개도 B", "%", 1, _pct),
    0x49: Pid("pedal_d", "가속 페달 D", "%", 1, _pct),
    0x4A: Pid("pedal_e", "가속 페달 E", "%", 1, _pct),
    0x4C: Pid("throttle_actuator", "스로틀 액추에이터 목표", "%", 1, _pct),
    0x4D: Pid("time_mil", "경고등 켜진 시간", "분", 2, _u16),
    0x4E: Pid("time_cleared", "고장코드 삭제 후 시간", "분", 2, _u16),
    0x51: Pid("fuel_type", "연료 종류", "", 1, lambda d: FUEL_TYPES.get(d[0], f"코드 {d[0]}")),
    0x52: Pid("ethanol", "에탄올 비율", "%", 1, _pct),
    0x59: Pid("fuel_rail_absolute", "연료 레일 절대 압력", "kPa", 2, lambda d: _u16(d) * 10),
    0x5B: Pid("hybrid_battery", "하이브리드 배터리 잔량", "%", 1, _pct),
    0x5C: Pid("oil_temp", "엔진오일 온도", "°C", 1, lambda d: d[0] - 40),
    0x5D: Pid("injection_timing", "연료 분사 시기", "°", 2, lambda d: round(_u16(d) / 128 - 210, 2)),
    0x5E: Pid("fuel_rate", "연료 소비율", "L/h", 2, lambda d: round(_u16(d) / 20, 2)),
    0x61: Pid("torque_demand", "운전자 요구 토크", "%", 1, lambda d: d[0] - 125),
    0x62: Pid("torque_actual", "실제 엔진 토크", "%", 1, lambda d: d[0] - 125),
    0x63: Pid("torque_reference", "기준 엔진 토크", "Nm", 2, _u16),
    0x8E: Pid("torque_friction", "엔진 마찰 토크", "%", 1, lambda d: d[0] - 125),
    0xA6: Pid("odometer", "누적 주행거리", "km", 4, lambda d: int.from_bytes(d[:4], "big") / 10),
}
# 고장코드가 저장될 때 함께 남는 값(모드 02 프리즈 프레임)으로 읽을 PID
FREEZE_PIDS = (0x04, 0x05, 0x06, 0x07, 0x0B, 0x0C, 0x0D, 0x0F, 0x11)
SUPPORT_PIDS = (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0)
# 모드 06 지원 MID 비트맵 요청(06 00·20·…·E0)
MODE06_RANGES = (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0)


def supported_pids(payloads: list[bytes]) -> set[int]:
    """01 00·20·40… 응답의 비트맵. 비트 하나가 다음 PID 하나의 지원 여부다."""
    pids: set[int] = set()
    for payload in payloads:
        if len(payload) < 6:
            continue
        base = payload[1]
        bits = int.from_bytes(payload[2:6], "big")
        pids |= {base + i + 1 for i in range(32) if bits & (1 << (31 - i))}
    return pids


def mode01(payload: bytes) -> dict | None:
    pid = PIDS.get(payload[1]) if len(payload) >= 2 else None
    data = payload[2:]
    if pid is None or len(data) < pid.size:
        return None
    return {"key": pid.key, "label": pid.label, "unit": pid.unit, "value": pid.decode(data)}


# PIDS에 없지만 묶음 응답을 나눌 때 길이를 알아야 하는 PID
_PID_SIZES = {pid: 4 for pid in SUPPORT_PIDS} | {0x01: 4, 0x41: 4}


def mode01_values(payload: bytes) -> list[dict]:
    """'41 PID 데이터 [PID 데이터…]'. CAN 묶음 요청(최대 6개)의 응답은 PID와 데이터가 이어서 온다."""
    values = []
    i = 1
    while i < len(payload):
        pid = payload[i]
        size = PIDS[pid].size if pid in PIDS else _PID_SIZES.get(pid)
        if size is None or i + 1 + size > len(payload):
            break
        if value := mode01(b"\x41" + payload[i : i + 1 + size]):
            values.append(value)
        i += 1 + size
    return values


# 01 01·01 41 배출 점검(레디니스). 바이트 B 아래 3비트는 공통, C(지원)·D(미완료)는 점화 방식마다 다르다.
_COMMON_MONITORS = ("실화", "연료 계통", "종합 부품")
_SPARK_MONITORS = ("촉매", "가열 촉매", "증발가스", "2차 공기", "에어컨 냉매", "산소센서", "산소센서 히터", "EGR·VVT")
_COMPRESSION_MONITORS = ("NMHC 촉매", "NOx·SCR 후처리", None, "과급 압력", None, "배기가스 센서", "PM 필터", "EGR·VVT")


def readiness(payload: bytes) -> dict | None:
    """'41 01 A B C D'. A: 경고등·고장코드 수, B bit3: 압축 착화(디젤), 지원 비트가 1이고 미완료 비트가 0이면 완료."""
    if len(payload) < 6:
        return None
    a, b, c, d = payload[2:6]
    compression = bool(b & 0x08)
    tests = [{"name": name, "complete": not b & (1 << (i + 4))}
             for i, name in enumerate(_COMMON_MONITORS) if b & (1 << i)]
    tests += [{"name": name, "complete": not d & (1 << i)}
              for i, name in enumerate(_COMPRESSION_MONITORS if compression else _SPARK_MONITORS)
              if name and c & (1 << i)]
    return {"mil": bool(a & 0x80), "dtc_count": a & 0x7F,
            "ignition": "압축 착화(디젤)" if compression else "불꽃 점화(가솔린)", "tests": tests}


# ---- 모드 06 배출 부품 점검 결과(CAN) -----------------------------------------

# SAE J1979 부록 E 단위·배율(UAS): ID → (배율, 오프셋, 단위). 0x80 이상은 부호 있는 값이다.
UAS = {
    0x01: (1, 0, ""), 0x02: (0.1, 0, ""), 0x03: (0.01, 0, ""), 0x04: (0.001, 0, ""),
    0x05: (0.0000305, 0, ""), 0x06: (0.000305, 0, ""), 0x07: (0.25, 0, "rpm"), 0x08: (0.01, 0, "km/h"),
    0x09: (1, 0, "km/h"), 0x0A: (0.122, 0, "mV"), 0x0B: (0.001, 0, "V"), 0x0C: (0.01, 0, "V"),
    0x0D: (0.00390625, 0, "mA"), 0x0E: (0.001, 0, "A"), 0x0F: (0.01, 0, "A"), 0x10: (1, 0, "ms"),
    0x11: (100, 0, "ms"), 0x12: (1, 0, "s"), 0x13: (1, 0, "mΩ"), 0x14: (1, 0, "Ω"), 0x15: (1, 0, "kΩ"),
    0x16: (0.1, -40, "°C"), 0x17: (0.01, 0, "kPa"), 0x18: (0.0117, 0, "kPa"), 0x19: (0.079, 0, "kPa"),
    0x1A: (1, 0, "kPa"), 0x1B: (10, 0, "kPa"), 0x1C: (0.01, 0, "°"), 0x1D: (0.5, 0, "°"),
    0x1E: (0.0000305, 0, "λ"), 0x1F: (0.05, 0, ""), 0x20: (0.0039062, 0, ""), 0x21: (1, 0, "mHz"),
    0x22: (1, 0, "Hz"), 0x23: (1, 0, "kHz"), 0x24: (1, 0, "회"), 0x25: (1, 0, "km"), 0x26: (0.1, 0, "mV/ms"),
    0x27: (0.01, 0, "g/s"), 0x28: (1, 0, "g/s"), 0x29: (0.25, 0, "Pa/s"), 0x2A: (0.001, 0, "kg/h"),
    0x2B: (1, 0, "회"), 0x2C: (0.01, 0, "g/cyl"), 0x2D: (0.01, 0, "mg/stroke"), 0x2E: (1, 0, ""),
    0x2F: (0.01, 0, "%"), 0x30: (0.001526, 0, "%"), 0x31: (0.001, 0, "L"), 0x34: (1, 0, "분"),
    0x35: (10, 0, "ms"), 0x36: (0.01, 0, "g"), 0x37: (0.1, 0, "g"), 0x38: (1, 0, "g"),
    0x39: (0.01, -327.68, "%"), 0x3C: (0.1, 0, "µs"), 0x3D: (0.01, 0, "mA"), 0x3F: (0.01, 0, "L"),
    0x40: (1, 0, "ppm"), 0x41: (0.01, 0, "µA"),
    0x81: (1, 0, ""), 0x82: (0.1, 0, ""), 0x83: (0.01, 0, ""), 0x84: (0.001, 0, ""), 0x85: (0.0000305, 0, ""),
    0x86: (0.000305, 0, ""), 0x8A: (0.122, 0, "mV"), 0x8B: (0.001, 0, "V"), 0x8C: (0.01, 0, "V"),
    0x8D: (0.00390625, 0, "mA"), 0x8E: (0.001, 0, "A"), 0x90: (1, 0, "ms"), 0x96: (0.1, 0, "°C"),
    0x9C: (0.01, 0, "°"), 0x9D: (0.5, 0, "°"), 0xA8: (1, 0, "g/s"), 0xA9: (0.25, 0, "Pa/s"),
    0xAD: (0.01, 0, "mg/stroke"), 0xAE: (0.1, 0, "mg/stroke"), 0xAF: (0.01, 0, "%"), 0xB0: (0.003052, 0, "%"),
    0xB1: (2, 0, "mV/s"), 0xFC: (0.01, 0, "kPa"), 0xFD: (0.001, 0, "kPa"), 0xFE: (0.25, 0, "Pa"),
}
_O2 = ("B1S1", "B1S2", "B1S3", "B1S4", "B2S1", "B2S2", "B2S3", "B2S4")
# 점검 항목(MID). 없는 번호는 'MID xx'로 표시한다.
MIDS = ({0x01 + i: f"산소센서 {s}" for i, s in enumerate(_O2)}
        | {0x41 + i: f"산소센서 히터 {s}" for i, s in enumerate(_O2)}
        | {0x21: "촉매 뱅크1", 0x22: "촉매 뱅크2", 0x31: "EGR", 0x35: "VVT 뱅크1", 0x36: "VVT 뱅크2",
           0x39: "증발가스 누설(0.150\")", 0x3A: "증발가스 누설(0.090\")", 0x3B: "증발가스 누설(0.040\")",
           0x3C: "증발가스 누설(0.020\")", 0x3D: "퍼지 흐름", 0x61: "가열 촉매 뱅크1", 0x62: "가열 촉매 뱅크2",
           0x71: "2차 공기 1", 0x72: "2차 공기 2", 0x81: "연료 계통 뱅크1", 0x82: "연료 계통 뱅크2",
           0x85: "과급 압력 뱅크1", 0x86: "과급 압력 뱅크2", 0x90: "NOx 흡착 뱅크1", 0x91: "NOx 흡착 뱅크2",
           0x98: "NOx 촉매 뱅크1", 0x99: "NOx 촉매 뱅크2", 0xA1: "실화(전체)", 0xB0: "PM 필터 뱅크1",
           0xB1: "PM 필터 뱅크2"}
        | {0xA2 + i: f"실화 {i + 1}번 실린더" for i in range(12)})


def mode06_tests(payload: bytes) -> list[dict]:
    """'46 [MID TID UAS 값(2) 최소(2) 최대(2)]…'. 최소 ≤ 값 ≤ 최대이면 합격."""
    records = payload[1:]
    tests = []
    for i in range(0, len(records) - 8, 9):
        mid, tid, uas = records[i : i + 3]
        if mid % 0x20 == 0:
            continue
        scale, offset, unit = UAS.get(uas, (1, 0, ""))
        raw = [int.from_bytes(records[i + 3 + 2 * k : i + 5 + 2 * k], "big", signed=uas >= 0x80) for k in range(3)]
        value, low, high = (round(r * scale + offset, 4) for r in raw)
        tests.append({"mid": f"{mid:02X}", "name": MIDS.get(mid, f"MID {mid:02X}"), "tid": f"{tid:02X}",
                      "value": value, "min": low, "max": high, "unit": unit, "passed": low <= value <= high})
    return tests


def freeze_value(payload: bytes) -> dict | None:
    """모드 02 응답 '42 PID 프레임 데이터…'. 데이터 공식은 모드 01과 같다."""
    return mode01(payload[:2] + payload[3:]) if len(payload) >= 4 else None


def freeze_dtc(payload: bytes) -> str | None:
    """02 02 00: 프리즈 프레임을 남긴 고장코드."""
    if len(payload) < 5 or not (payload[3] or payload[4]):
        return None
    return _two_byte_dtc(payload[3], payload[4])


def monitor_status(payload: bytes) -> dict | None:
    """01 01: 경고등(MIL) 상태와 저장된 고장코드 수."""
    if len(payload) < 3:
        return None
    return {"mil": bool(payload[2] & 0x80), "dtc_count": payload[2] & 0x7F}


# ---- 고장코드 --------------------------------------------------------------

def _two_byte_dtc(a: int, b: int) -> str:
    return f"{'PCBU'[a >> 6]}{(a >> 4) & 0x03}{a & 0x0F:X}{b:02X}"


def obd_dtcs(payloads: list[bytes], bus: str | None) -> list[str]:
    """모드 03(확정)·07(대기)·0A(영구) 응답. CAN은 개수 바이트가 앞에 있고, K-Line은 00 00으로 채운다."""
    codes: list[str] = []
    for payload in payloads:
        data = payload[1:]
        if bus and bus.startswith("can") and data:
            data = data[1 : 1 + 2 * data[0]]
        for i in range(0, len(data) - 1, 2):
            a, b = data[i], data[i + 1]
            if a or b:
                code = _two_byte_dtc(a, b)
                if code not in codes:
                    codes.append(code)
    return codes


def uds_dtcs(payload: bytes) -> list[dict]:
    """19 02(상태 마스크)·19 15(영구) 응답: 3바이트 DTC + 상태 바이트. 상태 bit0=현재, bit3=확정."""
    if len(payload) < 3 or payload[1] not in (0x02, 0x15):
        return []
    records = payload[3:]
    result = []
    for i in range(0, len(records) - 3, 4):
        b1, b2, b3, status = records[i : i + 4]
        result.append({"code": format_dtc(b1, b2, b3), "status": status,
                       "confirmed": bool(status & 0x08), "active": bool(status & 0x01)})
    return result


def uds_snapshot(payload: bytes) -> dict | None:
    """19 04 응답 '59 04 DTC(3) 상태 [기록번호 식별자수 DID(2) 데이터…]'. DID별 길이는 제조사 정의라 원값으로 둔다."""
    if len(payload) < 6 or payload[1] != 0x04:
        return None
    rest = payload[6:]
    snapshot = {"code": format_dtc(*payload[2:5]), "status": payload[5], "record": None, "did": None, "raw": ""}
    if len(rest) >= 4:
        snapshot |= {"record": rest[0], "did": rest[2:4].hex().upper(), "raw": rest[4:].hex(" ").upper()[:180]}
    return snapshot


SYSTEMS = {"engine": "엔진", "transmission": "변속기", "chassis": "섀시", "network": "통신", "body": "바디"}


def dtc_system(code: str) -> str:
    """위카 앱(dtc_classifier)과 같은 분류. 바디(B)도 버리지 않고 따로 센다."""
    head = code[:1]
    if head == "P":
        return "transmission" if code[1:3] in ("07", "08", "09") else "engine"
    return {"C": "chassis", "U": "network", "B": "body"}.get(head, "engine")


# ---- 차량 정보 -------------------------------------------------------------

def _ascii(raw: bytes) -> str:
    return "".join(chr(b) for b in raw if 0x20 < b < 0x7F)


def _mode09_data(payloads: list[bytes]) -> bytes:
    """CAN은 한 메시지(49 xx 개수 데이터), K-Line은 '49 xx 순번 4바이트' 여러 메시지."""
    if len(payloads) == 1:
        return payloads[0][3:]
    ordered = sorted(payloads, key=lambda p: p[2] if len(p) > 2 else 0)
    return b"".join(p[3:] for p in ordered)


def vin_from(command_hex: str, payloads: list[bytes]) -> str | None:
    if not payloads:
        return None
    raw = payloads[0][3:] if command_hex.upper() == "22F190" else _mode09_data(payloads)
    text = re.sub(r"[^A-HJ-NPR-Z0-9]", "", _ascii(raw).upper())
    return text[-17:] if len(text) >= 17 else None


def calibration_ids(payloads: list[bytes]) -> list[str]:
    data = _mode09_data(payloads)
    return [text for i in range(0, len(data), 16) if (text := _ascii(data[i : i + 16]))]


def ecu_name(payloads: list[bytes]) -> str | None:
    return _ascii(_mode09_data(payloads)).replace("-", " ").strip() or None


def cvns(payloads: list[bytes]) -> list[str]:
    """09 06: 보정 검증 번호(CVN) 4바이트씩."""
    data = _mode09_data(payloads)
    return [data[i : i + 4].hex().upper() for i in range(0, len(data) - 3, 4)]


# 09 08(가솔린)·09 0B(디젤) 주행 중 진단 실행 비율(IUMPR): 진단 조건 횟수, 시동 횟수 다음에 (완료, 조건) 짝
_IUMPR = {"08": ("촉매 뱅크1", "촉매 뱅크2", "산소센서 뱅크1", "산소센서 뱅크2", "EGR·VVT", "2차 공기", "증발가스",
                 "후방 산소센서 뱅크1", "후방 산소센서 뱅크2"),
          "0B": ("NMHC 촉매", "NOx 촉매", "NOx 흡착", "PM 필터", "배기가스 센서", "EGR·VVT", "과급 압력", "연료 계통")}


def iumpr(info: str, payloads: list[bytes]) -> dict | None:
    data = _mode09_data(payloads)
    counts = [int.from_bytes(data[i : i + 2], "big") for i in range(0, len(data) - 1, 2)]
    if len(counts) < 2 or info not in _IUMPR:
        return None
    monitors = []
    for k, name in enumerate(_IUMPR[info]):
        pair = counts[2 + 2 * k : 4 + 2 * k]
        if len(pair) < 2:
            break
        done, conditions = pair
        monitors.append({"name": name, "completed": done, "conditions": conditions,
                         "ratio": round(done / conditions, 3) if conditions else None})
    return {"conditions": counts[0], "ignitions": counts[1], "monitors": monitors}


# UDS 22 제어기 식별 DID(ISO 14229 부록 C)
ECU_IDENT_DIDS = {"F187": ("part_no", "부품번호"), "F195": ("sw_version", "소프트웨어 버전")}


def ecu_ident(payload: bytes) -> str | None:
    """62 F1 xx 문자열. 글자가 없으면 None."""
    return _ascii(payload[3:]) or None
