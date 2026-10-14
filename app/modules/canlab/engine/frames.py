"""CAN 프레임 읽기: PCAN-View TRC와 위카 ELM327 수집 로그."""

import re
from dataclasses import dataclass

ELM_HEADER = "# WECAR-ELM 1"

_TRC_V1 = re.compile(
    r"^\s*\d+\)\s+(?P<t>-?\d+(?:\.\d+)?)\s+(?P<dir>Rx|Tx)\s+(?P<id>[0-9A-Fa-f]{1,8})\s+"
    r"(?P<dlc>\d{1,2})\s+(?P<data>(?:[0-9A-Fa-f]{2}\s*)*)$"
)
_TRC_V2 = re.compile(
    r"^\s*\d+\s+(?P<t>-?\d+(?:\.\d+)?)\s+(?:DT|FD)?\s*(?:\d+\s+)?(?P<id>[0-9A-Fa-f]{1,8})\s+"
    r"(?P<dir>Rx|Tx)\s+(?:-\s+)?(?P<dlc>\d{1,2})\s+(?P<data>(?:[0-9A-Fa-f]{2}\s*)*)$"
)
_ELM = re.compile(
    r"^\s*(?P<t>\d+(?:\.\d+)?)\s+(?P<dir>TX|RX)\s+(?P<id>[0-9A-Fa-f]{3}|[0-9A-Fa-f]{8})\s+"
    r"(?P<data>(?:[0-9A-Fa-f]{2}\s*)+)$"
)


@dataclass(frozen=True)
class Frame:
    t_ms: float
    can_id: int
    data: bytes
    direction: str = "rx"

    @property
    def id_hex(self) -> str:
        return f"{self.can_id:03X}"


@dataclass(frozen=True)
class ParsedTrace:
    format: str
    frames: list[Frame]
    meta: dict[str, str]
    skipped_lines: int


def _bytes(text: str) -> bytes:
    return bytes(int(token, 16) for token in text.split())


def _parse_trc(lines: list[str]) -> ParsedTrace:
    meta: dict[str, str] = {}
    frames: list[Frame] = []
    skipped = 0
    for line in lines:
        if line.startswith(";"):
            if line.startswith(";$") and "=" in line:
                key, value = line[2:].split("=", 1)
                meta[key.strip()] = value.strip()
            elif "Start time:" in line:
                meta["START_TIME_TEXT"] = line.split("Start time:", 1)[1].strip()
            continue
        if not line.strip():
            continue
        match = _TRC_V1.match(line) or _TRC_V2.match(line)
        if match is None:
            skipped += 1
            continue
        data = _bytes(match["data"])[: int(match["dlc"])]
        frames.append(Frame(float(match["t"]), int(match["id"], 16), data, match["dir"].lower()))
    return ParsedTrace("pcan_trc", frames, meta, skipped)


def _parse_elm(lines: list[str]) -> ParsedTrace:
    frames: list[Frame] = []
    meta: dict[str, str] = {}
    skipped = 0
    for line in lines:
        if line.startswith("#"):
            if ":" in line:
                key, value = line[1:].split(":", 1)
                meta[key.strip()] = value.strip()
            continue
        if not line.strip():
            continue
        match = _ELM.match(line)
        if match is None:
            skipped += 1
            continue
        frames.append(Frame(float(match["t"]), int(match["id"], 16), _bytes(match["data"]),
                            match["dir"].lower()))
    return ParsedTrace("wecar_elm", frames, meta, skipped)


_ELM_REPLY_FRAME = re.compile(r"^([0-9A-F]{3}|[0-9A-F]{8})((?:\s[0-9A-F]{2})+)$")


def elm_from_exchanges(exchanges: list[dict], meta: dict[str, str]) -> str:
    """앱이 보낸 (시각, 헤더, 명령, ELM 응답 문자열) 목록을 '# WECAR-ELM 1' 기록으로 만든다.

    ELM327은 ATH1·ATS1에서 응답 프레임을 '7EC 10 3E 62 ...'처럼 한 줄씩 돌려준다.
    요청은 ISO-TP 단일 프레임(길이 바이트 + 명령)으로 남긴다.
    """
    lines = [ELM_HEADER, *(f"# {key}: {value}" for key, value in meta.items() if value)]
    for item in exchanges:
        t = float(item.get("t_ms") or 0)
        command = bytes.fromhex(item["command"])
        lines.append(f"{t:.1f} TX {item['header']} {len(command):02X} {command.hex(' ').upper()}")
        for raw in re.split(r"[\r\n]+", item.get("reply") or ""):
            if match := _ELM_REPLY_FRAME.match(raw.strip().upper()):
                lines.append(f"{t:.1f} RX {match[1]} {match[2].strip()}")
    return "\n".join(lines) + "\n"


def parse_trace(text: str) -> ParsedTrace:
    """파일 내용으로 형식을 판별해 프레임 목록을 만든다. 읽지 못한 줄 수도 함께 돌려준다."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[0].strip() == ELM_HEADER:
        return _parse_elm(lines[1:])
    return _parse_trc(lines)


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8", "cp949"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1")
