"""입력 디렉터리를 탐색해 파일을 분류하고 TRC·PDF·소스코드 구조를 기록한다 (REQ-01).

파일명은 코드에 고정하지 않는다. 용도는 확장자와 내용으로 정하고,
파일명 키워드는 '후보'로만 표시한다.
"""

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from can_reverse_engineer.parsers.pdf_probe import probe_pdf
from can_reverse_engineer.parsers.trc_probe import looks_like_trc, probe_trc
from can_reverse_engineer.source_analysis.source_map import map_sources

log = logging.getLogger(__name__)

CATEGORIES = {
    ".trc": "trace",
    ".pdf": "document",
    **dict.fromkeys((".c", ".h", ".cpp", ".hpp", ".py"), "source"),
    **dict.fromkeys((".dbc", ".arxml", ".a2l"), "can_definition"),
    ".xml": "xml",
    **dict.fromkeys((".json", ".yaml", ".yml", ".csv", ".txt"), "data"),
}
PURPOSES = {
    "trace": "CAN 트레이스(TRC)",
    "source": "소스코드",
    "can_definition": "CAN 정의 파일",
    "xml": "XML (CAN 정의 후보)",
    "data": "데이터/설정 파일",
}
_GSCAN_HINT = re.compile(r"g-?scan|지스캔|g스캔|diagnosticreport", re.IGNORECASE)
_SKIP_DIRS = {"__pycache__", ".git", "node_modules"}


def discover(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in CATEGORIES
        and not any(part in _SKIP_DIRS or part.startswith(".") for part in path.relative_to(root).parts)
    )


def detect_encoding(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    if all(byte < 0x80 for byte in data):
        return "ascii"
    for encoding in ("utf-8", "cp949"):
        try:
            data.decode(encoding)
        except UnicodeDecodeError:
            continue
        return encoding
    return "unknown"


def _purpose(path: Path, category: str, is_trc: bool) -> tuple[str, str]:
    if is_trc:
        basis = "확장자 .trc" if path.suffix.lower() == ".trc" else "파일 첫 줄이 ;$FILEVERSION"
        return PURPOSES["trace"], basis
    if category == "trace":
        return PURPOSES["trace"], "확장자 .trc (TRC header 없음)"
    if category == "document":
        if _GSCAN_HINT.search(path.name):
            return "G-Scan 결과 PDF 후보", "파일명 키워드(추정)"
        return "PDF 문서(용도 미확인)", "확장자 .pdf"
    return PURPOSES[category], f"확장자 {path.suffix.lower()}"


def _issue(level: str, message: str, path: str | None = None) -> dict[str, Any]:
    return {"level": level, "file": path, "message": message}


def build_inventory(root: Path, sample_size: int = 50) -> dict[str, Any]:
    root = Path(root).resolve()
    files, traces, pdfs, issues = [], [], [], []
    by_hash: dict[str, list[str]] = {}
    sources: list[Path] = []

    for path in discover(root):
        relative = path.relative_to(root).as_posix()
        log.info("파일 확인: %s", relative)
        raw = path.read_bytes()
        category = CATEGORIES[path.suffix.lower()]
        encoding = "binary" if category == "document" else detect_encoding(raw)
        text = raw.decode(encoding) if encoding not in ("binary", "unknown") else None
        is_trc = text is not None and looks_like_trc(text)
        purpose, basis = _purpose(path, category, is_trc)
        digest = hashlib.sha256(raw).hexdigest()
        by_hash.setdefault(digest, []).append(relative)
        files.append({
            "path": relative,
            "filename": path.name,
            "extension": path.suffix.lower(),
            "size": len(raw),
            "encoding": encoding,
            "sha256": digest,
            "purpose": purpose,
            "purpose_basis": basis,
        })

        if encoding == "unknown":
            issues.append(_issue("WARNING", "문자 인코딩을 판별하지 못했습니다.", relative))
        if category == "trace" and not is_trc:
            issues.append(_issue("WARNING", "확장자는 .trc지만 TRC header가 없습니다. 형식을 확인하세요.",
                                 relative))
        if is_trc:
            result = {"path": relative, **probe_trc(text, sample_size)}
            traces.append(result)
            if len(result["token_count_distribution"]) > 1:
                issues.append(_issue("INFO", "앞부분 메시지의 열 개수가 줄마다 다릅니다(DLC 차이 등). "
                                     "REQ-02에서 확인합니다.", relative))
        elif category == "document":
            try:
                result = {"path": relative, **probe_pdf(path)}
            except Exception as error:  # 손상된 PDF도 목록에는 남기고 계속 진행한다.
                log.exception("PDF 확인 실패: %s", relative)
                issues.append(_issue("ERROR", f"PDF를 열 수 없습니다: {error}", relative))
            else:
                pdfs.append(result)
                if result["text_layer"] != "있음":
                    issues.append(_issue("WARNING", f"텍스트 레이어가 없습니다({result['text_layer']}). "
                                         "REQ-07에서 OCR 또는 수동 입력이 필요합니다.", relative))
        elif category == "source":
            sources.append(path)

    for paths in by_hash.values():
        if len(paths) > 1:
            issues.append(_issue("INFO", f"내용이 같은 파일입니다: {', '.join(paths)}"))
    source_code = map_sources(root, sources)
    if not source_code["found"]:
        issues.append(_issue("INFO", "소스코드가 없습니다. REQ-11~13은 SKIPPED로 기록합니다."))
    if not any(f["extension"] in (".dbc", ".arxml", ".a2l") for f in files):
        issues.append(_issue("INFO", "DBC/ARXML/A2L 정의 파일이 없습니다."))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_dir": str(root),
        "file_count": len(files),
        "files": files,
        "trc": traces,
        "pdf": pdfs,
        "source_code": source_code,
        "issues": issues,
    }
