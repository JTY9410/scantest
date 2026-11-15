"""Test VIN masking in reports (HTML and PDF).

Requirement 2026-11-15: VIN은 앞 3자리 + * + 끝 4자리만 표시 (DB 저장은 그대로).

mask_vin() 함수는 report.py의 inspection()에서 호출되어 HTML과 PDF에 마스킹된 VIN을 제공합니다.
inspection() 함수의 동작은 test_learn_report.py 등 다른 테스트에서 검증됩니다.
"""

from app.modules.scanner.report import mask_vin


def test_mask_vin_standard():
    """표준 17자리 VIN 마스킹."""
    assert mask_vin("KMHXX81CBMU123456") == "KMH**********3456"
    assert mask_vin("ZZZ12345678901234") == "ZZZ**********1234"


def test_mask_vin_short():
    """짧은 VIN은 그대로 반환."""
    assert mask_vin("ABC1234") == "ABC1234"
    assert mask_vin("12345") == "12345"


def test_mask_vin_none_or_empty():
    """None이나 빈 문자열은 '-' 반환."""
    assert mask_vin(None) == "-"
    assert mask_vin("") == "-"


def test_mask_vin_exact_7_chars():
    """정확히 7자리는 마스킹 없이 그대로."""
    assert mask_vin("ABCDEFG") == "ABCDEFG"


def test_mask_vin_8_chars():
    """8자리부터 마스킹 시작 (앞3 + * + 끝4)."""
    assert mask_vin("ABCDEFGH") == "ABC*EFGH"
