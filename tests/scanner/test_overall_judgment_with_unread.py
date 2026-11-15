"""Test overall judgment with unmeasurable items (UNREAD).

Bug fix 2026-11-15: 측정불가 항목이 하나라도 있으면 종합 판정은 '판정보류'여야 함.
"""

from app.modules.scanner.report import overall, UNREAD


def test_overall_judgment_good_when_all_measured():
    """모든 항목이 측정되고 양호하면 '양호'."""
    rows = [
        {"item": "배터리 수명 (SOH)", "result": "양호"},
        {"item": "절연 저항", "result": "양호"},
        {"item": "셀 전압 편차", "result": "양호"},
        {"item": "모듈 온도 편차", "result": "양호"},
    ]
    assert overall(rows, dtc_count=0, dtc_read=True) == "양호"


def test_overall_judgment_pending_when_any_unread():
    """측정불가 항목이 하나라도 있으면 '판정보류'."""
    # Case 1: Core items good, but LDC/inlet temps unread
    rows = [
        {"item": "배터리 수명 (SOH)", "result": "양호"},
        {"item": "절연 저항", "result": "양호"},
        {"item": "셀 전압 편차", "result": "양호"},
        {"item": "모듈 온도 편차", "result": "양호"},
        {"item": "LDC 출력전압", "result": UNREAD},
        {"item": "LDC vs 12V", "result": UNREAD},
        {"item": "입구온도편차", "result": UNREAD},
    ]
    assert overall(rows, dtc_count=0, dtc_read=True) == "판정보류"
    
    # Case 2: Some core items unread
    rows = [
        {"item": "배터리 수명 (SOH)", "result": "양호"},
        {"item": "절연 저항", "result": UNREAD},
        {"item": "셀 전압 편차", "result": "양호"},
    ]
    assert overall(rows, dtc_count=0, dtc_read=True) == "판정보류"


def test_overall_judgment_pending_when_dtc_not_read():
    """고장코드를 읽지 못했으면 '판정보류'."""
    rows = [
        {"item": "배터리 수명 (SOH)", "result": "양호"},
        {"item": "절연 저항", "result": "양호"},
    ]
    assert overall(rows, dtc_count=0, dtc_read=False) == "판정보류"


def test_overall_judgment_caution_when_any_issue():
    """주의 항목이나 고장코드가 있으면 '점검요'."""
    rows = [
        {"item": "배터리 수명 (SOH)", "result": "양호"},
        {"item": "절연 저항", "result": "주의"},
    ]
    assert overall(rows, dtc_count=0, dtc_read=True) == "점검요"
    
    rows = [
        {"item": "배터리 수명 (SOH)", "result": "양호"},
        {"item": "절연 저항", "result": "양호"},
    ]
    assert overall(rows, dtc_count=1, dtc_read=True) == "점검요"
