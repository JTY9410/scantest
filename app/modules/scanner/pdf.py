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
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.time import local_display
from app.modules.scanner import analysis
from app.modules.scanner.obd import SYSTEMS
from app.modules.scans.models import Scan

FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONT, FONT_BOLD = "NanumGothic", "NanumGothic-Bold"
STATUS = {"ok": "정상 완료", "partial": "일부 오류", "failed": "실패"}
INK, MUTED, LINE, DANGER = colors.HexColor("#111827"), colors.HexColor("#6B7280"), colors.HexColor("#E5E7EB"), \
    colors.HexColor("#B91C1C")


def _fonts() -> None:
    if FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT, FONT_DIR / "NanumGothic-Regular.ttf"))
        pdfmetrics.registerFont(TTFont(FONT_BOLD, FONT_DIR / "NanumGothic-Bold.ttf"))


_BODY = ParagraphStyle("body", fontName=FONT, fontSize=8.5, leading=12, textColor=INK, wordWrap="CJK")
_SMALL = ParagraphStyle("small", parent=_BODY, fontSize=7.5, leading=10, textColor=MUTED)
_H1 = ParagraphStyle("h1", parent=_BODY, fontName=FONT_BOLD, fontSize=16, leading=22)
_H2 = ParagraphStyle("h2", parent=_BODY, fontName=FONT_BOLD, fontSize=11, leading=16, spaceBefore=10, spaceAfter=4,
                     keepWithNext=1)
_DANGER = ParagraphStyle("danger", parent=_BODY, textColor=DANGER)


def _p(value, style=_BODY) -> Paragraph:
    # 나눔고딕에는 그리스 문자 Ω(U+03A9)가 없고 옴 기호(U+2126)만 있다.
    text = escape("-" if value in (None, "") else str(value)).replace("\n", "<br/>").replace("Ω", "\u2126")
    return Paragraph(text, style)


def _num(value) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return str(value)
    return f"{value:,}" if isinstance(value, int) or value != int(value) else f"{int(value):,}"


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


def _values(values: list[dict]) -> Table:
    return _table([["항목", "값"]] + [[v["label"], f"{_num(v['value'])} {v.get('unit') or ''}".strip()]
                                     for v in values], [110, 60])


def _analysis(result: dict) -> list:
    summary = analysis.summarize(result)
    readiness = summary["readiness"]
    rows = [
        ("배출 점검(레디니스)", f"{readiness['ignition']} · 완료 {readiness['complete']}/{readiness['total']}"
         + (f" · 미완료: {', '.join(readiness['incomplete'])}" if readiness["incomplete"] else " · 모두 완료")
         if readiness else None),
        ("고장코드", f"{summary['dtc_total']}건 · " + ", ".join(f"{k} {n}" for k, n in summary["dtc_kinds"].items())
         if summary["dtc_total"] else "없음"),
        ("배출 부품 점검(모드 06)", f"{summary['monitor_total']}항목 · "
         + (f"불합격 {len(summary['monitor_failures'])}" if summary["monitor_failures"] else "모두 합격")
         if summary["monitor_total"] else None),
        ("주행 중 진단 실행 비율", ("기준(0.336) 미달: " + ", ".join(m["name"] for m in summary["iumpr_low"])
                             if summary["iumpr_low"] else "기준 이상") if result.get("iumpr") else None),
        *[(item["label"], item["value"] + (f"\nOBDb 정상 범위 {item['range']}" if item["range"] else ""))
          for item in summary["ev"]],
        ("이상값(요약 계산에서 뺌)", "\n".join(summary["outliers"])),
    ]
    story = [_p("분석 요약", _H2), _table([[k, v] for k, v in rows if v], [45, 125], header=False)]
    failures = [[f"{t['name']} ({t['ecu']} MID {t['mid']})", f"{_num(t['value'])} {t['unit']}".strip(),
                 f"{_num(t['min'])} ~ {_num(t['max'])}"] for t in summary["monitor_failures"]]
    if failures:
        story += [Spacer(1, 4), _table([["불합격 점검 항목", "값", "기준"]] + failures, [90, 40, 40])]
    story += [_p(f"· {w}", _DANGER) for w in summary["warnings"]]
    judgments = (result.get("wescan") or {}).get("judgments") or []
    if judgments:
        story += [Spacer(1, 4), _p("기본 보고서 판정", _H2),
                  _table([["항목", "진단 기준", "진단 결과", "판정"]] + [
                      [row["item"], row["standard"], f"{row['value']} {row['unit']}", row["result"]]
                      for row in judgments], [32, 78, 28, 18])]
        story.append(_p("판정은 위스캔 기본 보고서 기준입니다. 읽지 못한 항목은 빠집니다.", _SMALL))
    return story


def render(scan: Scan, result: dict) -> bytes:
    from app.modules.scanner.service import TRANSPORTS

    _fonts()
    car = result.get("car") or {}
    monitor = result.get("monitor") or {}
    counts = result.get("counts") or {}
    story = [
        _p(f"위스캔 진단 결과 · {scan.car_no}", _H1),
        _p(f"{local_display(scan.created_at)} · {TRANSPORTS.get(result.get('transport'), result.get('transport'))}"
           f" · {STATUS.get(result.get('status'), result.get('status'))}", _SMALL),
        _p("차량 정보", _H2),
        _pairs([
            ("차량번호", scan.car_no), ("제조사·모델", " ".join(x for x in (scan.car_maker, scan.car_model,
                                                                         scan.car_submodel) if x)),
            ("연식", scan.car_year), ("연료", scan.car_fuel),
            ("배기량", f"{scan.car_cc:,} cc" if scan.car_cc is not None else None),
            ("주행거리", f"{scan.car_distance:,} km" if scan.car_distance is not None else None),
            ("차대번호(조회)", car.get("diag_car_id")), ("차대번호(차량)", result.get("vin") or "읽지 못함"),
        ]),
        _p("검사 정보", _H2),
        _pairs([
            ("검사자", scan.tester.name if scan.tester else None), ("단말기", result.get("device")),
            ("통신 방식", (result.get("protocol") or {}).get("name") or "알 수 없음"),
            ("차량 전압", f"{result['voltage']:.1f} V" if result.get("voltage") is not None else None),
            ("경고등(MIL)", ("켜짐" if monitor.get("mil") else "꺼짐") + f" · 저장 고장코드 {monitor.get('dtc_count', 0)}개"
             if monitor else None),
            ("응답한 제어기", f"{len(result.get('ecus') or [])}곳"),
            ("단계", f"성공 {counts.get('ok', 0)} · 지원 안 함 {counts.get('unsupported', 0)} · "
                    f"오류 {counts.get('errors', 0)} / 전체 {counts.get('total', 0)}"),
        ]),
        _p("진단 요약", _H2),
        _table([[label for label in SYSTEMS.values()],
                [f"고장 {n}건" if (n := (result.get("systems") or {}).get(k, 0)) else "정상" for k in SYSTEMS]],
               [170 / len(SYSTEMS)] * len(SYSTEMS)),
    ]
    story += _analysis(result)

    dtcs = result.get("dtcs") or []
    story.append(_p(f"고장코드 상세 {len(dtcs)}건", _H2))
    if dtcs:
        rows = [["코드", "시스템", "상태", "제어기", "설명·원인"]]
        for d in dtcs:
            note = d.get("desc") or "고장코드 마스터에 설명이 없습니다."
            if d.get("root_cause"):
                note += f"\n원인: {d['root_cause']}"
            rows.append([d["code"], SYSTEMS.get(d.get("system"), d.get("system")), ", ".join(d.get("kinds") or [d.get("kind")]),
                         f"{d.get('ecu') or ''} {', '.join(d.get('sources') or [d.get('source') or ''])}".strip(), note])
        story.append(_table(rows, [20, 22, 14, 34, 80]))
    else:
        story.append(_p("읽은 고장코드가 없습니다." if counts.get("ok") else "고장코드를 읽지 못했습니다. 오류 기록을 확인하세요."))

    if freeze := result.get("freeze_frame"):
        story.append(_p(f"고장 당시 값(프리즈 프레임) {freeze.get('dtc') or ''}".strip(), _H2))
        story.append(_values(freeze.get("values") or []) if freeze.get("values") else _p("당시 값은 읽지 못했습니다."))

    if snapshots := result.get("snapshots"):
        story.append(_p("제어기 고장 당시 데이터(UDS 19 04, 원값)", _H2))
        story.append(_table([["고장코드", "제어기", "기록·DID", "원값"]] + [
            [s["code"], s.get("ecu"), f"{s.get('record') if s.get('record') is not None else '-'} · {s.get('did') or '-'}",
             s.get("raw") or "-"] for s in snapshots], [24, 22, 24, 100]))

    if battery := result.get("battery"):
        story.append(_p("고전압 배터리", _H2))
        story.append(_table([["항목", "값", "근거"]] + [
            [v["label"], f"{_num(v['value'])} {v.get('unit') or ''}".strip() + (" (이상값)" if v.get("outlier") else ""),
             ("참고 해석(미검증)" if v.get("reference") else "적용 규칙")
             + (f"\n{v['origin']}" if v.get("origin") else "")] for v in battery.values()], [80, 40, 50]))
        if cells := result.get("cells"):
            story.append(_p(f"셀 {cells['count']}개 · 최저 {cells['min']} V · 최고 {cells['max']} V · 편차 "
                            f"{cells['spread_mv']} mV · 합 {cells['sum']} V"
                            + (f" · 이상값 {len(cells['outliers'])}개 제외" if cells.get("outliers") else "")
                            + f" ({cells['origin']}, CC BY-SA 4.0)", _SMALL))

    if result.get("values"):
        story.append(_p("실시간 데이터", _H2))
        story.append(_values(result["values"]))
    for group in result.get("ecu_values") or []:
        story.append(_p(f"실시간 데이터 · 다른 제어기 {group['ecu']}", _H2))
        story.append(_values(group["values"]))

    if ecus := result.get("ecus"):
        story.append(_p("응답한 제어기", _H2))
        story.append(_table([["주소", "제어기", "부품번호·소프트웨어", "응답한 서비스"]] + [
            [e.get("address"), e.get("label"), " · ".join(x for x in (e.get("part_no"), e.get("sw_version")) if x),
             ", ".join(e.get("services") or [])] for e in ecus], [20, 50, 55, 45]))
    extra = [(k, ", ".join(result.get(f) or [])) for k, f in
             (("ECU 이름", "ecu_names"), ("소프트웨어 보정 ID", "calibration_ids"), ("보정 검증 번호(CVN)", "cvns"))]
    if any(v for _, v in extra):
        story.append(Spacer(1, 4))
        story.append(_table([[k, v] for k, v in extra if v], [40, 130], header=False))

    errors = result.get("errors") or []
    story.append(_p(f"오류 기록 {len(errors)}건", _H2))
    if errors:
        story.append(_table([["단계", "명령", "상태", "내용"]] + [
            [e.get("label"), f"{e.get('header') or ''} {e.get('command') or '-'}".strip(),
             _p(e.get("status_label"), _DANGER), e.get("message")]
            for e in errors], [40, 28, 20, 82]))
    else:
        story.append(_p("오류 없이 완료했습니다."))
    for note in result.get("notes") or []:
        story.append(_p(f"· {note}", _SMALL))

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"위스캔 진단 결과 {scan.car_no}", author="WecarScan")

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(FONT, 7)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"위스캔 · 스캔 #{scan.id} · {document.page}쪽")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def filename(scan: Scan) -> str:
    stamp = local_display(scan.created_at).replace("-", "").replace(":", "").replace(" ", "-")
    return f"위스캔-{scan.car_no}-{stamp}.pdf"
