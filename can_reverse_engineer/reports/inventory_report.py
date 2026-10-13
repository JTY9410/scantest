"""REQ-01 산출물(file_inventory.json, file_analysis.md)을 쓴다."""

import json
from pathlib import Path
from typing import Any


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |" for row in rows]
    return lines


def _files(inventory: dict[str, Any]) -> list[str]:
    rows = [[f["path"], f["extension"], f"{f['size']:,}", f["encoding"], f["purpose"],
             f["purpose_basis"], f["sha256"][:12]] for f in inventory["files"]]
    return _table(["파일", "확장자", "크기(B)", "인코딩", "예상 용도", "근거", "SHA-256"], rows)


def _trc(trc: dict[str, Any]) -> list[str]:
    lines = [f"### {trc['path']}", ""]
    lines += [f"- header {trc['header_line_count']}줄, 메시지 줄 {trc['data_line_count']:,}개, "
              f"header 뒤 주석 줄 {trc['comment_lines_after_header']}개"]
    lines += [f"- `{k}`: {v}" for k, v in trc["header_fields"].items()]
    lines += [f"- 범례 열: {' / '.join(trc['column_legend']) or '없음'}",
              f"- 앞 {trc['sample_size']}줄의 토큰 수 분포: {trc['token_count_distribution']}", ""]
    rows = [[p["column"], p["present_in"], p["distinct"], p["kinds"], ", ".join(p["examples"])]
            for p in trc["column_profiles"]]
    lines += _table(["토큰 위치", "있는 줄", "고유값", "모양", "예"], rows)
    lines += ["", "<details><summary>앞부분 메시지 원문</summary>", "", "```text",
              *trc["sample_lines"], "```", "", "</details>", ""]
    return lines


def _pdf(pdf: dict[str, Any]) -> list[str]:
    lines = [f"### {pdf['path']}", "",
             f"- {pdf['page_count']}쪽, 텍스트 레이어 {pdf['text_layer']}, "
             f"producer `{pdf['producer']}`, creator `{pdf['creator']}`, 생성 `{pdf['created']}`", ""]
    rows = [[p["page"], f"{p['width_mm']}×{p['height_mm']}", p["text_chars"], p["image_count"]]
            for p in pdf["pages"]]
    return lines + _table(["쪽", "크기(mm)", "텍스트 글자 수", "이미지 수"], rows) + [""]


def render_markdown(inventory: dict[str, Any]) -> str:
    source = inventory["source_code"]
    lines = ["# REQ-01 입력 데이터 Inventory", "",
             f"- 입력: `{inventory['input_dir']}`", f"- 생성: {inventory['generated_at']}",
             f"- 파일 {inventory['file_count']}개", "",
             "## [FILES FOUND]", "", *_files(inventory), "",
             "## [TRC STRUCTURE]", ""]
    for trc in inventory["trc"]:
        lines += _trc(trc)
    if not inventory["trc"]:
        lines += ["TRC 파일이 없습니다.", ""]
    lines += ["## [PDF STRUCTURE]", ""]
    for pdf in inventory["pdf"]:
        lines += _pdf(pdf)
    if not inventory["pdf"]:
        lines += ["PDF 파일이 없습니다.", ""]
    lines += ["## [SOURCE CODE FOUND]", ""]
    if source["found"]:
        lines += [f"- {source['file_count']}개 파일, 언어별 {source['languages']}"]
        lines += [f"- `{d or '.'}/`: {', '.join(names)}" for d, names in source["directories"].items()]
    else:
        lines += ["없음 (REQ-11~13 SKIPPED 예정)"]
    lines += ["", "## [ISSUES]", ""]
    lines += [f"- **{i['level']}** {('`' + i['file'] + '` ') if i['file'] else ''}{i['message']}"
              for i in inventory["issues"]] or ["없음"]
    lines += ["", "## [NEXT STEP]", "",
              "REQ-02 범용 TRC Parser. 사용자 승인 후 진행합니다.", ""]
    return "\n".join(lines)


def write_outputs(inventory: dict[str, Any], out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "file_inventory.json"
    md_path = out_dir / "file_analysis.md"
    json_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2, default=str),
                         encoding="utf-8")
    md_path.write_text(render_markdown(inventory), encoding="utf-8")
    return [json_path, md_path]
