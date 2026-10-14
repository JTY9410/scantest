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
# K-Line·J1850 프레임은 'K<주소>'로 남긴다(CAN ID가 없다).
_ELM = re.compile(
    r"^\s*(?P<t>\d+(?:\.\d+)?)\s+(?P<dir>TX|RX)\s+(?P<id>[0-9A-Fa-f]{3}|[0-9A-Fa-f]{8}|K[0-9A-Fa-f]{2})\s+"
    r"(?P<data>(?:[0-9A-Fa-f]{2}\s*)+)$"
)


@dataclass(frozen=True)
class Frame:
    t_ms: float
    can_id: int
    data: bytes
    direction: str = "rx"


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
        ident = match["id"].upper()
        if ident.startswith("K"):
            frames.append(Frame(float(match["t"]), int(ident[1:], 16), _bytes(match["data"]), "serial"))
            continue
        frames.append(Frame(float(match["t"]), int(ident, 16), _bytes(match["data"]),
                            match["dir"].lower()))
    return ParsedTrace("wecar_elm", frames, meta, skipped)


_ELM_REPLY_FRAME = re.compile(r"^([0-9A-F]{3}|[0-9A-F]{8})((?:\s[0-9A-F]{2})+)$")
_BYTES_LINE = re.compile(r"^[0-9A-F]{2}(?:\s[0-9A-F]{2})+$")


@dataclass(frozen=True)
class ReplyFrame:
    """ELM327(ATH1) 응답 한 줄. bus는 'can' 또는 'serial'(K-Line·J1850)."""
    bus: str
    source: int
    data: bytes


def reply_frames(reply: str, bus: str | None = None) -> list[ReplyFrame]:
    """응답 문자열을 프레임으로 나눈다.

    - CAN 11비트: '7E8 06 41 0C 1A F8', 29비트: '18DAF110 ...' 또는 ATS1에서 '18 DA F1 10 ...'
    - K-Line(ISO 9141·14230)·J1850: '48 6B 10 41 0C 1A F8 C5' = 3바이트 헤더(셋째가 보낸 ECU) + 데이터 + 체크섬
    bus는 'can11'·'can29'·'serial'·None(모름: 줄 모양으로 판단).
    """
    frames = []
    for raw in re.split(r"[\r\n>]+", reply or ""):
        line = raw.strip().upper()
        if match := _ELM_REPLY_FRAME.match(line):
            frames.append(ReplyFrame("can", int(match[1], 16), _bytes(match[2])))
        elif _BYTES_LINE.match(line):
            data = _bytes(line)
            if bus == "can29" and len(data) > 4:
                frames.append(ReplyFrame("can", int.from_bytes(data[:4], "big"), data[4:]))
            elif bus != "can11" and len(data) >= 5:
                frames.append(ReplyFrame("serial", data[2], data[3:-1]))
    return frames


def elm_from_exchanges(exchanges: list[dict], meta: dict[str, str], bus: str | None = None) -> str:
    """앱이 보낸 (시각, 헤더, 명령, ELM 응답 문자열) 목록을 '# WECAR-ELM 1' 기록으로 만든다.

    ELM327은 ATH1·ATS1에서 응답 프레임을 '7EC 10 3E 62 ...'처럼 한 줄씩 돌려준다.
    요청은 ISO-TP 단일 프레임(길이 바이트 + 명령)으로 남긴다. K-Line·J1850은 'K<주소>'로 남긴다.
    """
    lines = [ELM_HEADER, *(f"# {key}: {value}" for key, value in meta.items() if value)]
    for item in exchanges:
        t = float(item.get("t_ms") or 0)
        command = bytes.fromhex(item["command"])
        if bus == "serial":
            lines.append(f"{t:.1f} TX K33 {command.hex(' ').upper()}")
        else:
            lines.append(f"{t:.1f} TX {item['header']} {len(command):02X} {command.hex(' ').upper()}")
        for frame in reply_frames(item.get("reply") or "", bus):
            ident = f"K{frame.source:02X}" if frame.bus == "serial" else (
                f"{frame.source:03X}" if frame.source <= 0x7FF else f"{frame.source:08X}")
            if frame.data:
                lines.append(f"{t:.1f} RX {ident} {frame.data.hex(' ').upper()}")
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
