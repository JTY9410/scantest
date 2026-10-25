"""이더넷 진단(DoIP·J2534) 읽기.

이 모듈은 하위 호환을 위해 유지되며, 실제 구현은 transport/doip.py를 사용합니다.
"""

import os
import re
import socket
from collections.abc import Callable, Generator
from typing import Any

from app.core.errors import ServiceError
from app.modules.scanner.transport.doip import DoIPAdapter

TESTER = 0x0E00
FUNCTIONAL = 0xE400
DOIP_PORT = 13400
_VERSION = b"\x02\xFD"

# 타입 정의
Connect = Callable[[str, int, float], socket.socket]
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


def iter_doip(host: str, port: int, connect=None, timeout: float = 2.0):
    """라우팅 활성화 뒤 읽기 단계를 진행한다. 
    
    transport/doip.py를 사용하여 구현됩니다.
    """
    adapter = DoIPAdapter()
    
    try:
        # 연결
        adapter.connect({"host": host, "port": port, "timeout": timeout})
        
        steps: list[dict] = []
        ok = fail = 0
        responders: list[int] = []
        targets = [FUNCTIONAL]
        
        for index, (command, label, group) in enumerate(_READS, 1):
            if not targets:
                break
                
            for target in list(targets):
                # 명령 전송
                header = f"{target:08X}"
                result = adapter.send_command(command, header=header, timeout_ms=int(timeout * 1000))
                
                if result.error or not result.reply:
                    fail += 1
                    steps.append(_done(index, command, target, label, group, "NO DATA\r\r>", result.error or "timeout"))
                else:
                    # 응답 파싱
                    from app.modules.scanner.obd import messages
                    found, _ = messages(result.reply, "can")
                    
                    if found:
                        for source in found.keys():
                            if source not in responders:
                                responders.append(source)
                        ok += 1
                        steps.append(_done(index, command, target, label, group, result.reply, None))
                    else:
                        fail += 1
                        steps.append(_done(index, command, target, label, group, "NO DATA\r\r>", "no_data"))
                
                yield {"type": "progress", "label": label, "header": header, "command": command,
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
        adapter.disconnect()


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

