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
}


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
    if service in (0x01, 0x09, 0x21, 0x19):
        return command[1:2]
    if service == 0x22:
        return command[1:3]
    return b""


def evaluate(command_hex: str, reply: str | None, bus: str | None, client_error: str | None = None) -> Outcome:
    """요청 하나의 결과. client_error는 브라우저·앱이 남긴 오류(timeout, disconnected, write 등)."""
    if client_error == "disconnected":
        return Outcome("disconnected", "진단기 연결이 끊겨 이 명령을 보내지 못했습니다.")
    if client_error == "timeout" or (reply is None and client_error is None):
        return Outcome("timeout", "응답 시간 초과: 단말기가 정해진 시간 안에 답하지 않았습니다.")
    if client_error:
        return Outcome("device_error", f"전송 실패: {client_error}")

    command = bytes.fromhex(command_hex)
    service, echo = command[0], _echo(command)
    found, incomplete = messages(reply, bus)
    outcome = Outcome("no_data", "")
    for ecu, payloads in found.items():
        for payload in payloads:
            if payload[:1] == bytes([service + 0x40]) and payload[1 : 1 + len(echo)] == echo:
                outcome.positive.setdefault(ecu, []).append(payload)
            elif len(payload) >= 3 and payload[0] == 0x7F and payload[1] == service \
                    and payload[2] != RESPONSE_PENDING:
                outcome.negative[ecu] = payload[2]

    if outcome.positive:
        outcome.status, outcome.message = "ok", f"{len(outcome.positive)}개 ECU 응답"
    elif outcome.negative:
        outcome.status = "negative"
        outcome.message = ", ".join(
            f"{_ecu(ecu)} NRC {code:02X} {NEGATIVE_CODES.get(code, '기타 거부')}"
            for ecu, code in outcome.negative.items())
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

PIDS: dict[int, Pid] = {
    0x04: Pid("engine_load", "엔진 부하", "%", 1, lambda d: round(d[0] * 100 / 255, 1)),
    0x05: Pid("coolant_temp", "냉각수 온도", "°C", 1, lambda d: d[0] - 40),
    0x0C: Pid("rpm", "엔진 회전수", "rpm", 2, lambda d: _u16(d) / 4),
    0x0D: Pid("speed", "차속", "km/h", 1, lambda d: d[0]),
    0x0F: Pid("intake_temp", "흡기 온도", "°C", 1, lambda d: d[0] - 40),
    0x11: Pid("throttle", "스로틀 개도", "%", 1, lambda d: round(d[0] * 100 / 255, 1)),
    0x1F: Pid("run_time", "시동 후 경과 시간", "s", 2, _u16),
    0x21: Pid("distance_mil", "경고등 켜진 뒤 주행거리", "km", 2, _u16),
    0x2F: Pid("fuel_level", "연료 잔량", "%", 1, lambda d: round(d[0] * 100 / 255, 1)),
    0x31: Pid("distance_cleared", "고장코드 삭제 후 주행거리", "km", 2, _u16),
    0x42: Pid("module_voltage", "제어 모듈 전압", "V", 2, lambda d: round(_u16(d) / 1000, 2)),
    0x46: Pid("ambient_temp", "외기 온도", "°C", 1, lambda d: d[0] - 40),
    0x51: Pid("fuel_type", "연료 종류", "", 1, lambda d: FUEL_TYPES.get(d[0], f"코드 {d[0]}")),
    0x5B: Pid("hybrid_battery", "하이브리드 배터리 잔량", "%", 1, lambda d: round(d[0] * 100 / 255, 1)),
    0x5C: Pid("oil_temp", "엔진오일 온도", "°C", 1, lambda d: d[0] - 40),
    0xA6: Pid("odometer", "누적 주행거리", "km", 4, lambda d: int.from_bytes(d[:4], "big") / 10),
}
SUPPORT_PIDS = (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0)


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
    """19 02 응답: 3바이트 DTC + 상태 바이트. 상태 bit0=현재, bit3=확정."""
    if len(payload) < 3 or payload[1] != 0x02:
        return []
    records = payload[3:]
    result = []
    for i in range(0, len(records) - 3, 4):
        b1, b2, b3, status = records[i : i + 4]
        result.append({"code": format_dtc(b1, b2, b3), "status": status,
                       "confirmed": bool(status & 0x08), "active": bool(status & 0x01)})
    return result


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
