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


def _inspection_story(view: dict) -> list:
    vehicle = view["vehicle"]
    story = [
        _p("EV TECHNICAL INSPECTION REPORT", _SMALL),
        _p("EV 기술 진단 보고서", _H1),
        _p("WESCAN 진단 솔루션 기반 · 전기차 고전압 시스템 정밀 진단", _SMALL),
        _pairs([
            ("제조사", vehicle["manufacturer"]), ("모델", vehicle["model"]),
            ("연식", vehicle["year"]), ("연료 형식", vehicle["fuel"]),
            ("차량번호", vehicle["number"]), ("차대번호 (VIN)", vehicle["vin"]),
            ("주행거리", f"{vehicle['mileage']:,.0f} km" if vehicle["mileage"] is not None else "-"),
            ("진단 일시", view["diagnosed_at"]),
        ]),
        _p("STATE OF HEALTH — 배터리 건강 상태", _H2),
        _p(f"{view['soh']:.1f}%" if view["soh"] is not None else "-", _H1),
        _p(view["soh_note"]),
        _p(view["mileage_note"], _SMALL),
        _p(f"OVERALL  {view['overall']}", _H2),
        _p(view["judgment_note"] + (" · 고장코드 미검출" if view["dtc_clear"] else f" · 고장코드 {view['dtc_count']}건")),
        _p("고장 코드 진단 · 8개 계통", _H2),
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
        _p(f"주요 진단 데이터 · {len(view['judgments'])}개 항목", _H2),
    ]
    if view["judgments"]:
        story.append(_table([["항목", "진단 기준", "진단 결과", "판정"]] + [
            [row["item"], row["standard"], f"{row['value']} {row['unit']}", row["result"]]
            for row in view["judgments"]], [40, 78, 28, 24]))
    else:
        story.append(_p(view["judgment_note"]))
    story += [
        PageBreak(),
        _p("고전압 시스템 계통", _H2),
        _p("BMS 센서 데이터", _H2),
        _pairs([(item["label"], _with_unit(item)) for item in view["bms"]]),
        _p("전력 · 충전 · 구동 계통", _H2),
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
        width = 42.5
        rows = [cells[i:i + 4] for i in range(0, len(cells), 4)]
        rows[-1] += [""] * (4 - len(rows[-1]))
        story.append(_table(rows, [width] * 4, header=False))
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
    story.append(_p("본 보고서의 수치는 진단 시점의 차량 상태를 기록한 것으로, 이후 사용 조건에 따라 변동될 수 있습니다.", _SMALL))
    story.append(_p("진단 방식 및 판정 기준 문의: 위카모빌리티(주) 자동차진단기술연구소 · 070-7588-0561", _SMALL))
    return story


def render(scan: Scan, result: dict) -> bytes:
    from app.modules.scanner.report import inspection

    _fonts()
    view = inspection(scan, result)
    story = _inspection_story(view)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm,
                            bottomMargin=16 * mm, title=f"WeSCAN 기본 진단 리포트 {scan.car_no}", author="WecarScan")

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(FONT, 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(16 * mm, 10 * mm, "WECARMOBILITY · BETTERWHY  |  EV TECHNICAL INSPECTION REPORT")
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"{document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def filename(scan: Scan) -> str:
    stamp = local_display(scan.created_at).replace("-", "").replace(":", "").replace(" ", "-")
    return f"위스캔-{scan.car_no}-{stamp}.pdf"
