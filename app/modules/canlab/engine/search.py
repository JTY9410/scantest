"""G-Scan 정답값을 DID 응답 바이트에서 역으로 찾는 탐색기.

모든 (DID, 시작 바이트, 길이, 엔디언, 부호) 조합의 원시값에 (배율, 오프셋)을 적용해
정답값과 표시 자릿수 반올림 오차 안에서 맞는 후보를 모으고 점수를 매긴다.
"""

import bisect
import json
import math
import struct
from collections import Counter
from dataclasses import dataclass, field, replace
from functools import cache
from pathlib import Path

from app.modules.canlab.engine import signals

WIDTHS = (1, 2, 4)
# (비트 길이, 시작 비트, 차지하는 바이트). 4비트는 상위·하위 니블만 본다.
BIT_FIELDS = ((4, 0, 1), (4, 4, 1), (10, 0, 2), (12, 0, 2))
SCALES = {1: 1.0, 0.1: 0.95, 0.5: 0.9, 0.02: 0.9, 0.01: 0.85, 0.001: 0.8, 0.25: 0.7, 0.2: 0.7, 10: 0.6}
TEMPERATURE_OFFSETS = (0, -40)
MAX_CANDIDATES = 8
AMBIGUITY_MARGIN = 0.02

Samples = dict[tuple[int, int], list[tuple[float, bytes]]]


@dataclass(frozen=True)
class Layout:
    request_id: int
    did: int
    start: int
    width: int
    endian: str = "big"
    signed: bool = False
    scale: float = 1.0
    offset: float = 0.0
    bit_offset: int = 0
    bit_length: int = 0
    encoding: str = "int"

    def raw(self, data: bytes) -> int | None:
        if self.encoding == "float32":
            return None
        if self.bit_length:
            return self._bit_raw(data)
        end = self.start + self.width
        if end > len(data):
            return None
        return int.from_bytes(data[self.start : end], self.endian, signed=self.signed)

    def _bit_raw(self, data: bytes) -> int | None:
        """앞 바이트의 높은 비트부터 bit_offset만큼 건너뛴 뒤 bit_length개를 읽는다."""
        length = self.bit_length
        if not 1 <= length <= 32 or not 0 <= self.bit_offset <= 7:
            return None
        span = (self.bit_offset + length + 7) // 8
        if self.start + span > len(data):
            return None
        chunk = int.from_bytes(data[self.start : self.start + span], "big")
        shift = span * 8 - self.bit_offset - length
        raw = (chunk >> shift) & ((1 << length) - 1)
        if self.signed and raw >= (1 << (length - 1)):
            raw -= 1 << length
        return raw

    def value(self, data: bytes) -> float | None:
        if self.encoding == "float32":
            if self.start + 4 > len(data):
                return None
            fmt = ">f" if self.endian == "big" else "<f"
            number = struct.unpack(fmt, data[self.start : self.start + 4])[0]
            return round(number, 6) if math.isfinite(number) else None
        raw = self.raw(data)
        return None if raw is None else round(raw * self.scale + self.offset, 6)

    @property
    def byte_range(self) -> tuple[int, int, int, int]:
        return (self.request_id, self.did, self.start, self.start + self.width)

    def formula(self) -> str:
        if self.encoding == "float32":
            order = "빅엔디언" if self.endian == "big" else "리틀엔디언"
            return f"b{self.start}~b{self.start + 3}(부동소수 32비트 {order})"
        if self.bit_length:
            kind = ("부호" if self.signed else "무부호") + f" {self.bit_length}비트"
            if self.bit_length == 4 and self.bit_offset == 0:
                source = f"b{self.start} 상위 니블"
            elif self.bit_length == 4 and self.bit_offset == 4:
                source = f"b{self.start} 하위 니블"
            elif self.bit_offset:
                source = f"b{self.start} 비트{self.bit_offset}부터"
            else:
                source = f"b{self.start}"
            text = f"{source}({kind})"
        else:
            last = self.start + self.width - 1
            kind = ("부호" if self.signed else "무부호") + f" {self.width * 8}비트"
            if self.width > 1:
                kind += " " + ("빅엔디언" if self.endian == "big" else "리틀엔디언")
            source = f"b{self.start}" if self.width == 1 else f"b{self.start}~b{last}"
            text = f"{source}({kind})"
        if self.scale != 1:
            text += f" × {self.scale:g}"
        if self.offset:
            text += f" {'+' if self.offset > 0 else '−'} {abs(self.offset):g}"
        return text

    def to_dict(self) -> dict:
        data = {
            "request_id": f"{self.request_id:03X}", "did": f"{self.did:04X}", "start": self.start,
            "width": self.width, "endian": self.endian, "signed": self.signed,
            "scale": self.scale, "offset": self.offset,
        }
        if self.bit_offset:
            data["bit_offset"] = self.bit_offset
        if self.bit_length:
            data["bit_length"] = self.bit_length
        if self.encoding != "int":
            data["encoding"] = self.encoding
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Layout":
        return cls(int(data["request_id"], 16), int(data["did"], 16), int(data["start"]),
                   int(data["width"]), data.get("endian", "big"), bool(data.get("signed")),
                   float(data.get("scale", 1)), float(data.get("offset", 0)),
                   int(data.get("bit_offset") or 0), int(data.get("bit_length") or 0),
                   data.get("encoding") or "int")


@dataclass(frozen=True)
class GroundTruth:
    signal_key: str
    value: float
    decimals: int = 0

    @property
    def tolerance(self) -> float:
        return signals.tolerance(self.signal_key, self.decimals)


@dataclass
class Candidate:
    signal_key: str
    layout: Layout
    error: float
    matched: int
    total: int
    decoded: float
    references: list[str] = field(default_factory=list)
    score: float = 0.0
    rivals: int = 0
    # 다른 신호가 먼저 차지한 바이트와 겹친다
    conflict: bool = False

    @property
    def support(self) -> float:
        return self.matched / self.total if self.total else 0.0

    def evidence(self, truth: GroundTruth) -> dict:
        return {
            "truth": truth.value, "decoded": self.decoded, "error": round(self.error, 6),
            "tolerance": round(truth.tolerance, 6), "matched_samples": self.matched,
            "total_samples": self.total, "references": self.references,
            "rivals": self.rivals, "conflict": self.conflict, "formula": self.layout.formula(),
        }


@cache
def load_references() -> dict:
    return json.loads(Path(__file__).with_name("references.json").read_text(encoding="utf-8"))


def reference_index() -> dict[tuple[str, Layout], list[str]]:
    index = {}
    for item in load_references()["hypotheses"]:
        index[(item["signal"], Layout.from_dict(item))] = item["sources"]
    return index


def _raw_vectors(samples: Samples):
    """(요청 ID, DID)마다 가능한 모든 바이트 묶음의 원시값 목록을 미리 계산한다."""
    for (request_id, did), rows in samples.items():
        lengths = Counter(len(data) for _, data in rows)
        length = lengths.most_common(1)[0][0]
        payloads = [data for _, data in rows if len(data) == length]
        for start in range(length):
            for width in WIDTHS:
                if start + width > length:
                    continue
                for endian in (("big", "little") if width > 1 else ("big",)):
                    unsigned = [int.from_bytes(p[start : start + width], endian) for p in payloads]
                    signed = [int.from_bytes(p[start : start + width], endian, signed=True) for p in payloads]
                    yield Layout(request_id, did, start, width, endian, False), unsigned
                    if signed != unsigned:
                        yield Layout(request_id, did, start, width, endian, True), signed
                    if width == 4:
                        fmt = ">f" if endian == "big" else "<f"
                        floats = [struct.unpack(fmt, p[start : start + width])[0] for p in payloads]
                        if all(math.isfinite(value) for value in floats):
                            yield Layout(request_id, did, start, width, endian, encoding="float32"), floats
            for bit_length, bit_offset, width in BIT_FIELDS:
                if start + width > length:
                    continue
                base = Layout(request_id, did, start, width, bit_offset=bit_offset, bit_length=bit_length)
                unsigned = [base.raw(p) for p in payloads]
                if any(value is None for value in unsigned):
                    continue
                yield base, unsigned
                signed_layout = replace(base, signed=True)
                signed = [signed_layout.raw(p) for p in payloads]
                if signed != unsigned:
                    yield signed_layout, signed


def _simplicity(layout: Layout) -> float:
    value = SCALES.get(layout.scale, 0.5)
    if layout.offset:
        value *= 0.9
    if layout.endian == "little":
        value *= 0.85
    return value


def _score(candidate: Candidate, drifting: bool, tolerance: float) -> float:
    precision = 1 - min(candidate.error / tolerance, 1)
    support = 1.0 if drifting else candidate.support
    reference = 1.0 if candidate.references else 0.0
    return round(0.45 * precision + 0.25 * support + 0.15 * _simplicity(candidate.layout)
                 + 0.15 * reference, 4)


def find_candidates(samples: Samples, truth: GroundTruth,
                    vectors: list[tuple[Layout, list[int]]] | None = None,
                    references: dict[tuple[str, Layout], list[str]] | None = None) -> list[Candidate]:
    """references: (신호, 배치) → 출처. 없으면 기본 참고 해석(references.json)."""
    signal = signals.BY_KEY[truth.signal_key]
    tol = truth.tolerance
    offsets = TEMPERATURE_OFFSETS if signal.unit == "°C" else (0,)
    references = reference_index() if references is None else references
    found: dict[tuple, Candidate] = {}
    for base, raws in vectors if vectors is not None else _raw_vectors(samples):
        if base.encoding == "float32":
            matched = [raw for raw in raws if abs(raw - truth.value) <= tol]
            if not matched:
                continue
            best = min(matched, key=lambda value: abs(value - truth.value))
            layout = base
            sources = references.get((truth.signal_key, layout), [])
            candidate = Candidate(
                truth.signal_key, layout, abs(best - truth.value), len(matched), len(raws),
                round(best, 6), sources,
            )
            candidate.score = _score(candidate, signal.drifting, tol)
            key = (base.request_id, base.did, base.start, tuple(raws), "float32", base.endian)
            kept = found.get(key)
            if kept is None or _prefer(candidate, kept):
                found[key] = candidate
            continue
        distinct = sorted(set(raws))
        for scale in SCALES:
            for offset in offsets:
                low = (truth.value - offset - tol) / scale
                high = (truth.value - offset + tol) / scale
                index = bisect.bisect_left(distinct, low)
                if index >= len(distinct) or distinct[index] > high:
                    continue
                matched = [raw for raw in raws if low <= raw <= high]
                values = [raw * scale + offset for raw in matched]
                best = min(values, key=lambda v: abs(v - truth.value))
                layout = replace(base, scale=scale, offset=offset)
                sources = references.get((truth.signal_key, layout), [])
                if not sources and not base.signed and max(raws) < 1 << (8 * base.width - 1):
                    # 표본이 모두 양수면 부호 해석과 같다. 참고자료가 부호를 말하면 그쪽으로 기록한다.
                    signed_layout = replace(layout, signed=True)
                    sources = references.get((truth.signal_key, signed_layout), [])
                    if sources:
                        layout = signed_layout
                candidate = Candidate(
                    truth.signal_key, layout, abs(best - truth.value), len(matched), len(raws),
                    round(best, 6), sources,
                )
                candidate.score = _score(candidate, signal.drifting, tol)
                series = tuple(raw * scale + offset for raw in raws)
                lowest_byte = base.start + base.width - 1 if base.endian == "big" else base.start
                key = (base.request_id, base.did, lowest_byte, series, base.bit_length, base.bit_offset)
                kept = found.get(key)
                if kept is None or _prefer(candidate, kept):
                    found[key] = candidate
    ranked = sorted(found.values(), key=lambda c: (-c.score, c.layout.width, c.layout.start))
    return ranked[: MAX_CANDIDATES * 4]


def _prefer(new: Candidate, old: Candidate) -> bool:
    """같은 값을 내는 두 해석 중 하나를 고른다. 참고자료와 맞는 쪽, 그다음 더 단순한 쪽."""
    if bool(new.references) != bool(old.references):
        return bool(new.references)
    if new.score != old.score:
        return new.score > old.score
    return new.layout.width < old.layout.width


def search(samples: Samples, truths: list[GroundTruth],
           references: dict[tuple[str, Layout], list[str]] | None = None) -> dict[str, list[Candidate]]:
    """신호마다 후보를 찾고, 점수가 높은 신호부터 바이트를 차지하게 해 겹치는 해석을 걸러 낸다."""
    vectors = list(_raw_vectors(samples))
    per_signal = {truth.signal_key: find_candidates(samples, truth, vectors, references) for truth in truths}
    order = sorted(per_signal, key=lambda key: -(per_signal[key][0].score if per_signal[key] else 0))
    claimed: list[tuple[int, int, int, int]] = []
    result: dict[str, list[Candidate]] = {}
    for key in order:
        free = [c for c in per_signal[key] if not any(_overlaps(c.layout.byte_range, r) for r in claimed)]
        taken = [c for c in per_signal[key] if c not in free]
        for candidate in taken:
            candidate.conflict = True
        ranked = (free + taken)[:MAX_CANDIDATES]
        if free:
            best = free[0]
            best.rivals = sum(
                1 for c in free[1:]
                if c.score >= best.score - AMBIGUITY_MARGIN and c.layout.byte_range != best.layout.byte_range
            )
            claimed.append(best.layout.byte_range)
        result[key] = ranked
    return result


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] == b[0] and a[1] == b[1] and a[2] < b[3] and b[2] < a[3]
