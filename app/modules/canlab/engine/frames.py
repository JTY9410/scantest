"""CAN 프레임 읽기: PCAN-View TRC, PCAN 계열 CSV, 위카 ELM327 수집 로그.

형식은 TRACE_FORMATS 레지스트리에 (이름, 판별 함수, 파서) 순으로 등록한다. 새 형식(ASC·BLF 등)은
판별 함수와 파서를 만들어 레지스트리에 넣으면 이후 단계(ISO-TP·UDS·디코딩·방송 분석)를 그대로 쓴다.
"""

import csv
import io
import re
from collections.abc import Callable
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


def _spaced(line: str, bus: str | None) -> str:
    """ATS0(공백 없음) 응답 '7E8064100983B8013'을 ATS1 모양으로 바꾼다. 11비트는 길이가 홀수다."""
    if not re.fullmatch(r"[0-9A-F]{6,}", line):
        return line
    if len(line) % 2:
        head, body = line[:3], line[3:]
    elif bus == "can29":
        head, body = line[:8], line[8:]
    else:
        head, body = "", line
    return " ".join(([head] if head else []) + re.findall("..", body))


def reply_frames(reply: str, bus: str | None = None) -> list[ReplyFrame]:
    """응답 문자열을 프레임으로 나눈다.

    - CAN 11비트: '7E8 06 41 0C 1A F8', 29비트: '18DAF110 ...' 또는 ATS1에서 '18 DA F1 10 ...'
    - K-Line(ISO 9141·14230)·J1850: '48 6B 10 41 0C 1A F8 C5' = 3바이트 헤더(셋째가 보낸 ECU) + 데이터 + 체크섬
    bus는 'can11'·'can29'·'serial'·None(모름: 줄 모양으로 판단).
    """
    frames = []
    for raw in re.split(r"[\r\n>]+", reply or ""):
        line = _spaced(raw.strip().upper(), bus)
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


# ── PCAN 계열 CSV ──────────────────────────────────────────────────────
# 위스캔·지스캔 수집 CSV(2026-11 실측): Timestamp(초),Channel,CAN_ID(hex),DLC,Data(공백 hex),IDType,...,Status1,...
# 방향(Tx/Rx) 열이 없으므로 진단 요청·응답은 이후 단계의 ID 규칙(응답 = 요청 + 8, 7DF → 7E8~7EF)으로 짝짓는다.
# Status1의 최상위 비트(0x80000000)가 켜진 행(CAN_ID 0, DLC 3 등)은 차량 프레임이 아닌 장비 상태 행이라 뺀다.
_CSV_ALIASES = {
    "time": ("timestamp", "time", "time_s", "timestamp_s", "time(s)", "t"),
    "time_ms": ("time_ms", "timestamp_ms", "time(ms)"),
    "id": ("can_id", "id", "canid", "identifier", "arbitration_id", "msgid"),
    "dlc": ("dlc", "len", "length", "datalength"),
    "data": ("data", "payload", "bytes", "data_bytes"),
    "dir": ("direction", "dir", "rx/tx", "type_dir"),
    "status": ("status1", "status"),
}
STATUS_EVENT_BIT = 0x80000000


def _norm_header(cell: str) -> str:
    return cell.strip().strip('"').lstrip("\ufeff").strip().lower().replace(" ", "_")


def _csv_columns(header: list[str]) -> dict[str, int] | None:
    names = [_norm_header(cell) for cell in header]
    columns: dict[str, int] = {}
    for key, aliases in _CSV_ALIASES.items():
        for alias in aliases:
            if alias in names:
                columns[key] = names.index(alias)
                break
    if "id" not in columns or "data" not in columns or not ({"time", "time_ms"} & columns.keys()):
        return None
    return columns


def _sniff_delimiter(first_line: str) -> str:
    counts = {d: first_line.count(d) for d in (",", ";", "\t")}
    return max(counts, key=counts.get)


def _is_pcan_csv(lines: list[str]) -> bool:
    first = next((line for line in lines if line.strip()), "")
    if not first:
        return False
    header = next(csv.reader([first], delimiter=_sniff_delimiter(first)))
    return _csv_columns(header) is not None


def _hex_int(text: str) -> int:
    text = text.strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    return int(text.rstrip("h"), 16)


def _parse_pcan_csv(lines: list[str]) -> ParsedTrace:
    first_index = next(i for i, line in enumerate(lines) if line.strip())
    delimiter = _sniff_delimiter(lines[first_index])
    reader = csv.reader(io.StringIO("\n".join(lines[first_index:])), delimiter=delimiter)
    columns = _csv_columns(next(reader))
    frames: list[Frame] = []
    skipped = 0
    status_rows = 0
    for row in reader:
        if not row or not any(cell.strip() for cell in row):
            continue
        try:
            if "status" in columns and columns["status"] < len(row) and row[columns["status"]].strip():
                if _hex_int(row[columns["status"]]) & STATUS_EVENT_BIT:
                    status_rows += 1
                    continue
            if "time" in columns:
                t_ms = float(row[columns["time"]]) * 1000.0
            else:
                t_ms = float(row[columns["time_ms"]])
            can_id = _hex_int(row[columns["id"]])
            data = _bytes(row[columns["data"]].replace("-", " "))
            if "dlc" in columns and row[columns["dlc"]].strip().isdigit():
                data = data[: int(row[columns["dlc"]])]
        except (ValueError, IndexError):
            skipped += 1
            continue
        direction = "rx"
        if "dir" in columns and columns["dir"] < len(row):
            value = row[columns["dir"]].strip().lower()
            direction = "tx" if value in ("tx", "t", "send") else "rx"
        frames.append(Frame(round(t_ms, 3), can_id, data, direction))
    if frames and "dir" not in columns:
        # 방향 열이 없으면 ID 규칙으로 추정한다(요청 = 7DF 또는 요청+8 응답 ID가 기록에 있는 7xx).
        ids = {frame.can_id for frame in frames}
        frames = [Frame(f.t_ms, f.can_id, f.data,
                        "tx" if f.can_id == 0x7DF or (0x700 <= f.can_id <= 0x7F7 and f.can_id + 8 in ids) else "rx")
                  for f in frames]
    meta = {"STATUS_ROWS": str(status_rows), "DIRECTION": "column" if "dir" in columns else "id_rule"}
    return ParsedTrace("pcan_csv", frames, meta, skipped)


def _is_elm(lines: list[str]) -> bool:
    return bool(lines) and lines[0].strip() == ELM_HEADER


# (형식 이름, 판별 함수, 파서). 앞에서부터 확인하고 아무것도 맞지 않으면 TRC로 읽는다.
TRACE_FORMATS: list[tuple[str, Callable[[list[str]], bool], Callable[[list[str]], ParsedTrace]]] = [
    ("wecar_elm", _is_elm, lambda lines: _parse_elm(lines[1:])),
    ("pcan_csv", _is_pcan_csv, _parse_pcan_csv),
]


def detect_format(text: str) -> str:
    lines = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n", 5)[:5]
    for name, matches, _ in TRACE_FORMATS:
        if matches(lines):
            return name
    return "pcan_trc"


def parse_trace(text: str) -> ParsedTrace:
    """파일 내용으로 형식을 판별해 프레임 목록을 만든다. 읽지 못한 줄 수도 함께 돌려준다."""
    lines = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for _, matches, parser in TRACE_FORMATS:
        if matches(lines[:5]):
            return parser(lines)
    return _parse_trc(lines)


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8", "cp949"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1")
