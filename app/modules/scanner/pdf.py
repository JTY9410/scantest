"""스캔 결과 PDF(A4). 글꼴은 fonts/의 나눔고딕(SIL OFL 1.1, fonts/OFL.txt)."""

from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle

from app.core.time import local_display
from app.modules.scans.models import Scan

FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONT, FONT_BOLD = "NanumGothic", "NanumGothic-Bold"
INK, MUTED, LINE = colors.HexColor("#111827"), colors.HexColor("#6B7280"), colors.HexColor("#E5E7EB")


def _fonts() -> None:
    if FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT, FONT_DIR / "NanumGothic-Regular.ttf"))
        pdfmetrics.registerFont(TTFont(FONT_BOLD, FONT_DIR / "NanumGothic-Bold.ttf"))


_BODY = ParagraphStyle("body", fontName=FONT, fontSize=8.5, leading=12, textColor=INK, wordWrap="CJK")
_SMALL = ParagraphStyle("small", parent=_BODY, fontSize=7.5, leading=10, textColor=MUTED)
_H1 = ParagraphStyle("h1", parent=_BODY, fontName=FONT_BOLD, fontSize=16, leading=22)
_H2 = ParagraphStyle("h2", parent=_BODY, fontName=FONT_BOLD, fontSize=11, leading=16, spaceBefore=10, spaceAfter=4,
                     keepWithNext=1)


def _p(value, style=_BODY) -> Paragraph:
    # 나눔고딕에는 그리스 문자 Ω(U+03A9)가 없고 옴 기호(U+2126)만 있다.
    text = escape("-" if value in (None, "") else str(value)).replace("\n", "<br/>").replace("Ω", "\u2126")
    return Paragraph(text, style)


def _table(rows: list[list], widths: list[float], header: bool = True) -> Table:
    table = Table([[c if isinstance(c, Paragraph) else _p(c) for c in row] for row in rows],
                  colWidths=[w * mm for w in widths], repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")))
    table.setStyle(TableStyle(style))
    return table


def _pairs(items: list[tuple[str, object]]) -> Table:
    """좌우 두 칸씩 '항목 값'."""
    cells = [[_p(k, _SMALL), _p(v)] for k, v in items]
    blank = [Paragraph("", _BODY), Paragraph("", _BODY)]
    rows = [cells[i] + (cells[i + 1] if i + 1 < len(cells) else blank) for i in range(0, len(cells), 2)]
    return _table(rows, [26, 59, 26, 59], header=False)


def _with_unit(item: dict) -> str:
    if item["text"] == "-":
        return "-"
    return f"{item['text']} {item['unit']}".strip()


def _cover(view: dict) -> list:
    vehicle = view["vehicle"]
    story = [
        _p(view["heading_en"], _SMALL),
        _p(view["heading"], _H1),
        _p(view["subheading"], _SMALL),
        _pairs([
            ("제조사", vehicle["manufacturer"]), ("모델", vehicle["model"]),
            ("연식", vehicle["year"]), ("연료 형식", vehicle["fuel"]),
            ("차량번호", vehicle["number"]), ("차대번호 (VIN)", vehicle["vin"]),
            ("주행거리", f"{vehicle['mileage']:,.0f} km" if vehicle["mileage"] is not None else "-"),
            ("진단 일시", view["diagnosed_at"]),
        ]),
        _p(f"차량 유형: {view['kind_label']} · 판별 근거: {view['powertrain'].get('source_label', '-')}", _SMALL),
    ]
    if view["kind"] == "ev":
        story += [
            _p("STATE OF HEALTH — 배터리 건강 상태", _H2),
            _p(f"{view['soh']:.1f}%" if view["soh"] is not None else "-", _H1),
            _p(view["soh_note"]),
            _p(view["mileage_note"], _SMALL),
        ]
    elif view["kind"] == "hev":
        story += [_p("HYBRID SYSTEM — 하이브리드 시스템 진단", _H2), _p(view["soh_note"]),
                  _p(view["mileage_note"], _SMALL)]
    else:
        story += [
            _p("DTC SUMMARY — 고장 코드 검출 현황", _H2),
            _p(f"{view['dtc_count']}건", _H1),
            _p("주요 ECU를 스캔한 결과, 검출된 고장 코드가 없습니다." if view["dtc_clear"]
               else f"주요 ECU를 스캔한 결과, 고장 코드 {view['dtc_count']}건이 검출되었습니다."),
            _p(view["mileage_note"], _SMALL),
        ]
    story += [
        _p(f"OVERALL  {view['overall']}", _H2),
        _p(view["judgment_note"] + (" · 고장코드 미검출" if view["dtc_clear"] else f" · 고장코드 {view['dtc_count']}건")),
        _p(f"고장 코드 진단 · {len(view['groups'])}개 계통", _H2),
        _table([[group["label"] for group in view["groups"]],
                [str(group["count"]) for group in view["groups"]]],
               [170 / len(view["groups"])] * len(view["groups"])),
        _p("검출된 고장 코드가 없습니다." if view["dtc_clear"] else f"검출된 고장 코드 {view['dtc_count']}건"),
        _p(f"{view['code']} · 발행일 {view['issued_on']}", _SMALL),
        _p("본 진단보고서는 위카모빌리티(주)와 (주)배터와이가 공동개발한 WESCAN 진단솔루션을 기반으로, "
           "스캔 데이터를 분석하여 산출한 자료입니다.", _SMALL),
        PageBreak(),
        _p(f"{view['title']} · {vehicle['number']}", _SMALL),
        _p(view["code"], _SMALL),
    ]
    return story


def _reconcile_note(view: dict) -> list:
    rc = view.get("reconcile")
    if not rc:
        return []
    grades = ", ".join(f"{g} {n}" for g, n in (rc.get("grades") or {}).items())
    story = [_p(f"대조 근거: 위스캔 통신기록 vs 리버스데이터 · VIN {rc.get('vin')}"
                f"{'(검사자 확인)' if rc.get('vin_manual') else ''} · 신뢰등급 {grades}. 확인됨·유력 값만 판정에 썼습니다.",
                _SMALL)]
    ref = view.get("reference") or {}
    parts = [f"{d['code']}({d['ecu']})" for d in ref.get("reverse_only_dtcs") or []]
    parts += [f"{v['label']} {v['value']}{v['unit']}" for v in ref.get("definition_only") or []]
    if parts:
        story.append(_p("참고(리버스, 판정 제외): " + ", ".join(parts[:30]), _SMALL))
    return story


def _dtc_detail(view: dict) -> list:
    story = [_p(f"고장 코드 상세 · 검출 {view['dtc_count']}건", _H2)]
    if view["dtc_rows"]:
        story.append(_table([["코드", "계통", "제어기", "상태", "설명"]] + [
            [row["code"], row["group"], row["ecu"], row["status"], row["desc"]] for row in view["dtc_rows"]],
            [20, 24, 22, 20, 84]))
    else:
        story.append(_p("검출된 고장 코드가 없습니다." if view["dtc_read"] else "고장 코드를 읽지 못했습니다."))
    return story + _reconcile_note(view)


_CLOSING = ("본 보고서의 수치는 진단 시점의 차량 상태를 기록한 것으로, 이후 사용 조건에 따라 변동될 수 있습니다.",
            "진단 방식 및 판정 기준 문의: 위카모빌리티(주) 자동차진단기술연구소 · 070-7588-0561")


def _judgment_page(view: dict) -> list:
    story = [_p(f"주요 진단 데이터 · {len(view['judgments'])}개 항목", _H2)]
    story.append(_table([["항목", "진단 기준", "진단 결과", "판정"]] + [
        [row["item"], row["standard"],
         f"{row['value']} {row['unit']}".strip() if row["value"] is not None else "-",
         row["result"] + (f" ({row['grade']})" if row.get("grade") else "")]
        for row in view["judgments"]], [40, 78, 28, 24]))
    if view["unread"]:
        story.append(_p(f"측정불가 {view['unread']}개 항목은 이 차량의 스캔에서 값을 읽지 못한 항목입니다. "
                        "측정불가 항목이 있으면 종합판정은 '판정보류'입니다.", _SMALL))
    return story


def _battery_pages(view: dict) -> list:
    story = [
        PageBreak(),
        _p("고전압 시스템 계통", _H2),
        _p("BMS 센서 데이터", _H2),
        _pairs([(item["label"], _with_unit(item)) for item in view["bms"]]),
        _p("전력 · 충전 · 구동 계통" if view["kind"] == "ev" or view["plugin"] else "전력 · 구동 계통", _H2),
        _pairs([(item["label"], _with_unit(item)) for item in view["power"]]),
        PageBreak(),
        _p(f"셀 별 전압 분포 · 총 {len(view['cells'])}개 셀", _H2),
        _pairs([
            ("최저 전압", f"{view['cell_min']:.3f} V" if view["cell_min"] is not None else "-"),
            ("최고 전압", f"{view['cell_max']:.3f} V" if view["cell_max"] is not None else "-"),
            ("편차 (Max−Min)", f"{view['cell_spread']:.3f} V" if view["cell_spread"] is not None else "-"),
        ]),
    ]
    if view["cells"]:
        cells = [f"{cell['no']}  {cell['voltage']:.3f} V" for cell in view["cells"]]
        rows = [cells[i:i + 4] for i in range(0, len(cells), 4)]
        rows[-1] += [""] * (4 - len(rows[-1]))
        story.append(_table(rows, [42.5] * 4, header=False))
    else:
        story.append(_p("셀 전압을 읽지 못했습니다."))
    story += [
        PageBreak(),
        _p(f"모듈 별 온도 분포 · 총 {len(view['modules'])}개 모듈", _H2),
        _pairs([
            ("최저 온도", f"{view['module_min']:.1f} ℃" if view["module_min"] is not None else "-"),
            ("최고 온도", f"{view['module_max']:.1f} ℃" if view["module_max"] is not None else "-"),
            ("편차 (Max−Min)", f"{view['module_spread']:.1f} ℃" if view["module_spread"] is not None else "-"),
        ]),
    ]
    if view["modules"]:
        temps = [f"모듈 {row['no']}  {row['value']:.1f} ℃" for row in view["modules"]]
        rows = [temps[i:i + 3] for i in range(0, len(temps), 3)]
        rows[-1] += [""] * (3 - len(rows[-1]))
        story.append(_table(rows, [56.6] * 3, header=False))
    else:
        story.append(_p("모듈 온도를 읽지 못했습니다."))
    return story


def story_ev(view: dict) -> list:
    """EV 기술 진단 보고서 5쪽: 표지·주요 진단 데이터+고장코드 상세·고전압 계통·셀·모듈."""
    return [*_cover(view), *_judgment_page(view), *_dtc_detail(view), *_battery_pages(view),
            *[_p(text, _SMALL) for text in _CLOSING]]


story_hev = story_ev  # HEV 5쪽: 같은 틀, 판정 항목·계통·구동 칸만 다르다(view가 정한다).


def story_ice(view: dict) -> list:
    """OBD-II DTC 진단 보고서 2쪽: 표지(6개 계통)·고장 코드 상세."""
    return [*_cover(view), *_dtc_detail(view), *[_p(text, _SMALL) for text in _CLOSING]]


_INSPECTION_STORY = {"ev": story_ev, "hev": story_hev, "ice": story_ice}


def _inspection_story(view: dict) -> list:
    return _INSPECTION_STORY[view["kind"]](view)


def _build(scan: Scan, view: dict) -> bytes:
    _fonts()
    story = _inspection_story(view)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm,
                            bottomMargin=16 * mm, title=f"WeSCAN {view['heading']} {scan.car_no}", author="WecarScan")
    label = f"WECARMOBILITY · BETTERWHY  |  {view['heading_en']}"

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(FONT, 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(16 * mm, 10 * mm, label)
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"{document.page:02d} / {view['pages']:02d}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def render_ev(scan: Scan, view: dict) -> bytes:
    return _build(scan, view)


def render_hev(scan: Scan, view: dict) -> bytes:
    return _build(scan, view)


def render_ice(scan: Scan, view: dict) -> bytes:
    return _build(scan, view)


def render(scan: Scan, result: dict) -> bytes:
    """스캔 유형(전기차·하이브리드·내연기관)에 맞는 기본 진단 보고서 PDF."""
    from app.modules.scanner.report import inspection

    view = inspection(scan, result)
    return {"ev": render_ev, "hev": render_hev, "ice": render_ice}[view["kind"]](scan, view)


def filename(scan: Scan) -> str:
    stamp = local_display(scan.created_at).replace("-", "").replace(":", "").replace(" ", "-")
    return f"위스캔-{scan.car_no}-{stamp}.pdf"
