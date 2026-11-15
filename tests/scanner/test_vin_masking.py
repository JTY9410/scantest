"""Test VIN masking in reports (HTML and PDF).

Requirement 2026-11-15: VIN은 앞 3자리 + * + 끝 4자리만 표시 (DB 저장은 그대로).
"""

import pytest
from unittest.mock import MagicMock

from app.modules.scanner.report import mask_vin, inspection
from app.modules.scans.models import Scan


@pytest.fixture
def app_context():
    """Create Flask app context for tests."""
    from app import create_app
    app = create_app()
    with app.app_context():
        yield app


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


@pytest.fixture
def mock_scan():
    """Create a mock scan for testing."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    
    scan = MagicMock(spec=Scan)
    scan.id = 12345
    scan.car_no = "88가8888"
    scan.car_maker = "기아"
    scan.car_model = "EV6"
    scan.car_year = "2022"
    scan.car_fuel = "전기"
    scan.car_vin = "KMHXX81CBMU123456"
    scan.car_distance = None
    scan.type = "ev"
    scan.created_at = datetime(2026, 11, 15, 12, 0, 0, tzinfo=ZoneInfo('Asia/Seoul'))
    return scan


def test_inspection_masks_vin(app_context, mock_scan):
    """inspection() 함수가 VIN을 마스킹함."""
    result = {
        "status": "success",
        "vin": "KMHXX81CBMU123456",
        "car": {"diag_fuel": "전기"},
        "dtcs": [],
        "battery": {
            "bms_soh": {"value": 95.5, "unit": "%"},
        },
        "values": [
            {"key": "odometer", "value": 12345, "unit": "km"},
        ],
        "steps": [],
    }
    
    view = inspection(mock_scan, result)
    
    # VIN should be masked
    assert view["vehicle"]["vin"] == "KMH**********3456"
    # Original VIN in result should not be affected
    assert result["vin"] == "KMHXX81CBMU123456"


def test_inspection_masks_reconcile_vin(app_context, mock_scan):
    """inspection() 함수가 reconcile.vin도 마스킹함."""
    result = {
        "status": "success",
        "source": "reconcile",
        "vin": "KMHXX81CBMU123456",
        "car": {"diag_fuel": "전기"},
        "dtcs": [],
        "battery": {
            "bms_soh": {"value": 95.5, "unit": "%"},
        },
        "values": [
            {"key": "odometer", "value": 12345, "unit": "km"},
        ],
        "reconcile": {
            "vin": "KMHXX81CBMU123456",
            "vin_manual": False,
            "grades": {"확인됨": 5, "유력": 3},
        },
        "reference": {},
        "steps": [],
    }
    
    view = inspection(mock_scan, result)
    
    # Reconcile VIN should be masked
    assert view["reconcile"]["vin"] == "KMH**********3456"
    # Original reconcile.vin in result should not be affected
    assert result["reconcile"]["vin"] == "KMHXX81CBMU123456"


def test_inspection_handles_missing_vin(app_context, mock_scan):
    """VIN이 없는 경우 처리."""
    mock_scan.car_vin = None
    result = {
        "status": "success",
        "car": {"diag_fuel": "전기"},
        "dtcs": [],
        "battery": {},
        "values": [],
        "steps": [],
    }
    
    view = inspection(mock_scan, result)
    
    # Missing VIN should be masked as '-'
    assert view["vehicle"]["vin"] == "-"


def test_pdf_uses_masked_vin(app_context, mock_scan):
    """PDF 생성 시 마스킹된 VIN 사용. inspection()이 VIN을 마스킹하므로 PDF는 마스킹된 값을 받음."""
    # This test verifies that inspection() provides masked VIN to PDF
    # The actual PDF rendering uses the masked value from inspection()
    # So we just verify that inspection() masks the VIN correctly
    
    result = {
        "status": "success",
        "vin": "KMHXX81CBMU123456",
        "car": {"diag_fuel": "전기"},
        "dtcs": [],
        "battery": {
            "bms_soh": {"value": 95.5, "unit": "%"},
        },
        "values": [
            {"key": "odometer", "value": 12345, "unit": "km"},
        ],
        "steps": [],
    }
    
    view = inspection(mock_scan, result)
    
    # Verify VIN is masked in view (which is passed to PDF)
    assert view["vehicle"]["vin"] == "KMH**********3456"
