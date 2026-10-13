"""PDF 페이지 구조(쪽 수, 크기, 텍스트 레이어, 이미지 수)를 확인한다 (REQ-01)."""

from pathlib import Path
from typing import Any

from pypdf import PdfReader

_PT_TO_MM = 25.4 / 72


def _image_count(resources, seen: set[int] | None = None) -> int:
    seen = seen if seen is not None else set()
    xobjects = resources.get("/XObject") if resources else None
    if not xobjects:
        return 0
    count = 0
    for ref in xobjects.values():
        obj = ref.get_object()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        if obj.get("/Subtype") == "/Image":
            count += 1
        elif obj.get("/Subtype") == "/Form":
            count += _image_count(obj.get("/Resources"), seen)
    return count


def probe_pdf(path: Path) -> dict[str, Any]:
    reader = PdfReader(path)
    if reader.is_encrypted:
        reader.decrypt("")
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        pages.append({
            "page": number,
            "width_mm": round(float(page.mediabox.width) * _PT_TO_MM, 1),
            "height_mm": round(float(page.mediabox.height) * _PT_TO_MM, 1),
            "text_chars": len(text),
            "image_count": _image_count(page.get("/Resources")),
            "text_preview": text[:200],
        })
    with_text = sum(1 for p in pages if p["text_chars"])
    text_layer = "없음" if with_text == 0 else "있음" if with_text == len(pages) else "일부"
    meta = reader.metadata or {}
    return {
        "page_count": len(pages),
        "text_layer": text_layer,
        "producer": meta.get("/Producer"),
        "creator": meta.get("/Creator"),
        "created": meta.get("/CreationDate"),
        "pages": pages,
    }
