"""이더넷 진단(DoIP·J2534) 읽기.

CAN 스캔 계획과 따로다. 테스터 0E00, 기능 주소 E400만 먼저 쓰고,
응답한 논리 주소에만 같은 읽기를 이어 간다. 세션·보안·쓰기·루틴·지우기는 보내지 않는다.
"""

import os
import re
import socket
from collections.abc import Callable

from app.core.errors import ServiceError

TESTER = 0x0E00
FUNCTIONAL = 0xE400
DOIP_PORT = 13400
_VERSION = b"\x02\xFD"
_READS = (
    ("0100", "모드 01 지원", "obd"),
    ("0101", "레디니스", "obd"),
    ("03", "확정 고장코드", "dtc"),
    ("07", "대기 고장코드", "dtc"),
    ("0A", "영구 고장코드", "dtc"),
    ("0902", "차대번호", "info"),
    ("22F190", "제어기 차대번호", "uds"),
    ("1902FF", "고장코드 상태", "uds"),
    ("22F187", "부품번호", "uds"),
    ("22F188", "소프트웨어 번호", "uds"),
    ("22F189", "소프트웨어 버전 번호", "uds"),
    ("22F18A", "공급자", "uds"),
    ("22F18C", "일련번호", "uds"),
    ("22F195", "소프트웨어 버전", "uds"),
)
_BLOCKED = {"10", "27", "2E", "31", "04", "14"}
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
_ELM = re.compile(r"^([0-9A-F]{3}|[0-9A-F]{8})(?:\s[0-9A-F]{2})+$")
Connect = Callable[[str, int, float], socket.socket]


def read_plan() -> list[dict]:
    """기능 주소로 보낼 공개 읽기 단계."""
    return [_step(index, command, FUNCTIONAL, label, group)
            for index, (command, label, group) in enumerate(_READS, 1)]


def vehicle_network_blocked() -> bool:
    """배포 서버는 차량 랜에 닿지 않는다."""
    return os.environ.get("VERCEL") == "1"


def check_gateway(host: str | None, port: int | None) -> tuple[str, int]:
    if vehicle_network_blocked():
        raise ServiceError("이 서버는 차량 이더넷에 연결할 수 없습니다. 차량과 같은 망의 로컬 서버에서 실행하세요.")
    name = (host or "").strip()
    if not _HOST.fullmatch(name) or name == "169.254.169.254":
        raise ServiceError("게이트웨이 주소를 확인하세요.")
    number = DOIP_PORT if port in (None, "") else int(port)
    if not 1 <= number <= 65535:
        raise ServiceError("포트 번호를 확인하세요.")
    return name, number


def iter_doip(host: str, port: int, connect: Connect | None = None, timeout: float = 2.0):
    """라우팅 활성화 뒤 읽기 단계를 진행한다. 연결 실패 시 단계를 만들지 않는다."""
    opener = connect or (lambda name, number, wait: socket.create_connection((name, number), wait))
    try:
        sock = opener(host, port, timeout)
    except OSError as exc:
        raise ServiceError("게이트웨이에 연결하지 못했습니다.") from exc
    steps: list[dict] = []
    ok = fail = 0
    try:
        sock.settimeout(timeout)
        _activate(sock)
        responders: list[int] = []
        targets = [FUNCTIONAL]
        for index, (command, label, group) in enumerate(_READS, 1):
            if not targets:
                break
            for target in list(targets):
                replies = _request(sock, target, bytes.fromhex(command))
                if not replies:
                    fail += 1
                    steps.append(_done(index, command, target, label, group, "NO DATA\r\r>", "timeout"))
                for source, payload in replies:
                    positive = bool(payload) and payload[0] == bytes.fromhex(command)[0] + 0x40
                    if positive and source not in responders:
                        responders.append(source)
                    if positive:
                        ok += 1
                    else:
                        fail += 1
                    steps.append(_done(index, command, source, label, group, _elm(source, payload), None))
                yield {"type": "progress", "label": label, "header": f"{target:08X}", "command": command,
                       "ok": ok, "fail": fail, "total": len(_READS)}
            if targets == [FUNCTIONAL]:
                targets = responders
                if not targets:
                    for rest_index, (rest_command, rest_label, rest_group) in enumerate(_READS[index:], index + 1):
                        fail += 1
                        steps.append(_done(rest_index, rest_command, FUNCTIONAL, rest_label, rest_group,
                                           "NO DATA\r\r>", "timeout"))
                    break
        yield {"type": "steps", "steps": steps}
    finally:
        sock.close()


def parse_j2534(text: str) -> list[dict]:
    """패스스루가 남긴 '주소 명령 응답' 줄을 스캔 단계로 읽는다."""
    steps = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            raise ServiceError("단계 기록은 주소, 명령, 응답 순서입니다.")
        header = _address(parts[0])
        command = re.sub(r"\s+", "", parts[1]).upper()
        if _blocked(command):
            raise ServiceError("세션 변경·보안·쓰기·지우기 명령은 받지 않습니다.")
        reply_text = " ".join(parts[2:]).upper()
        reply = reply_text + "\r\r>" if _ELM.match(reply_text) else _elm(int(header, 16), bytes.fromhex(reply_text))
        steps.append(_done(len(steps) + 1, command, int(header, 16), command, "j2534", reply, None))
    if not steps:
        raise ServiceError("단계 기록이 없습니다.")
    return steps


def _blocked(command: str) -> bool:
    compact = re.sub(r"\s+", "", command or "").upper()
    return compact[:2] in _BLOCKED or compact in {"04", "14FFFFFF"}


def _address(value: str) -> str:
    try:
        return f"{int(value, 16):08X}"
    except ValueError as exc:
        raise ServiceError("논리 주소가 올바르지 않습니다.") from exc


def _step(index: int, command: str, target: int, label: str, group: str) -> dict:
    return {"id": index, "command": command, "header": f"{target:08X}", "label": label, "group": group,
            "bus": "can", "optional": True}


def _done(index, command, source, label, group, reply, error) -> dict:
    step = _step(index, command, source, label, group)
    step["reply"] = reply
    step["error"] = error
    return step


def _packet(kind: int, payload: bytes) -> bytes:
    return _VERSION + kind.to_bytes(2, "big") + len(payload).to_bytes(4, "big") + payload


def _recv_exact(sock, size: int) -> bytes:
    buf = b""
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise ServiceError("게이트웨이 연결이 끊겼습니다.")
        buf += chunk
    return buf


def _read_packet(sock) -> tuple[int, bytes]:
    head = _recv_exact(sock, 8)
    if (head[0] ^ head[1]) != 0xFF:
        raise ServiceError("DoIP 헤더가 아닙니다.")
    length = int.from_bytes(head[4:8], "big")
    if length > 4096:
        raise ServiceError("DoIP 응답이 너무 깁니다.")
    return int.from_bytes(head[2:4], "big"), _recv_exact(sock, length) if length else b""


def _activate(sock) -> None:
    sock.sendall(_packet(0x0005, TESTER.to_bytes(2, "big") + b"\x00\x00\x00\x00\x00"))
    kind, payload = _read_packet(sock)
    if kind != 0x0006 or len(payload) < 5 or payload[4] != 0x10:
        raise ServiceError("DoIP 라우팅 활성화에 실패했습니다.")


def _request(sock, target: int, uds: bytes) -> list[tuple[int, bytes]]:
    sock.sendall(_packet(0x8001, TESTER.to_bytes(2, "big") + target.to_bytes(2, "big") + uds))
    found = []
    for _ in range(8):
        try:
            kind, payload = _read_packet(sock)
        except (TimeoutError, socket.timeout):
            break
        if kind == 0x8001 and len(payload) >= 4:
            found.append((int.from_bytes(payload[:2], "big"), payload[4:]))
            sock.settimeout(0.2)
        elif kind == 0x8003:
            break
    return found


def _elm(source: int, payload: bytes) -> str:
    """재조립된 UDS를 해석기가 읽는 ELM 한 줄로 바꾼다."""
    if not payload:
        return "NO DATA\r\r>"
    if len(payload) <= 7:
        frames = [bytes([len(payload)]) + payload]
    else:
        frames = [bytes([0x10 | (len(payload) >> 8), len(payload) & 0xFF]) + payload[:6]]
        rest, seq = payload[6:], 1
        while rest:
            chunk, rest = rest[:7], rest[7:]
            frames.append(bytes([0x20 | seq]) + chunk)
            seq = (seq + 1) % 16
    can_id = f"{source:08X}"
    lines = [can_id + " " + " ".join(f"{byte:02X}" for byte in frame) for frame in frames]
    return "\r".join(lines) + "\r>"
