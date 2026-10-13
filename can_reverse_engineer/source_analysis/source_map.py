"""입력에 포함된 소스코드의 디렉터리 구조를 기록한다 (REQ-01). 분석은 REQ-11부터."""

from collections import Counter
from pathlib import Path
from typing import Any


def map_sources(root: Path, paths: list[Path]) -> dict[str, Any]:
    files = []
    directories: dict[str, list[str]] = {}
    for path in paths:
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        files.append({"path": relative, "lines": len(text.splitlines())})
        directories.setdefault(path.parent.relative_to(root).as_posix(), []).append(path.name)
    return {
        "found": bool(files),
        "file_count": len(files),
        "languages": dict(Counter(p.suffix.lower() for p in paths)),
        "directories": directories,
        "files": files,
    }
