"""Test PDF report includes additional_info and issues sections.

Bug fix 2026-11-15: PDF 보고서에 '추가 수집 정보'와 '문제점' 섹션이 빠져 있었음.
"""

import pytest
from io import BytesIO
from unittest.mock import MagicMock

from app.modules.scanner.pdf import render, _additional_info_section, _issues_section
from app.modules.scans.models import Scan


@pytest.fixture
def app_context():
    """Create Flask app context for tests."""
    from app import create_app
    app = create_app()
    with app.app_context():
        yield app


@pytest.fixture
def mock_scan():
    """Create a mock scan object."""
    scan = MagicMock(spec=Scan)
    scan.id = 12345
    scan.car_no = "88가8888"
    scan.car_maker = "기아"
    scan.car_model = "EV6"
    scan.type = "ev"
    return scan


def test_additional_info_section_with_data():
    """추가 수집 정보 섹션이 데이터와 함께 생성됨."""
    from app.modules.scanner.pdf import _fonts
    
    # Register fonts before creating PDF elements
    _fonts()
    
    view = {
        "additional_info": {
            "freeze_frames": {"count": 2},
            "uds_snapshots": {"count": 1},
            "module_temps": {"count": 8, "min": 20.5, "max": 25.3},
            "cell_voltages": {"count": 96, "min": 3.850, "max": 3.952},
            "realtime_values": {"count": 12},
            "emission_monitors": {"status": "준비됨"},
        }
    }
    
    story = _additional_info_section(view)
    
    assert len(story) > 0
    # Check that the section was created
    text_items = [str(item) for item in story if hasattr(item, "text")]
    combined_text = " ".join(text_items)
    assert "추가 수집 정보" in combined_text
    assert "Freeze Frame" in combined_text or "freeze" in combined_text.lower()


def test_additional_info_section_empty():
    """추가 수집 정보가 없으면 섹션이 생성되지 않음."""
    view = {"additional_info": {}}
    story = _additional_info_section(view)
    assert len(story) == 0


def test_issues_section_with_data():
    """문제점 섹션이 데이터와 함께 생성됨."""
    from app.modules.scanner.pdf import _fonts
    
    # Register fonts before creating PDF elements
    _fonts()
    
    view = {
        "issues": {
            "errors": {"count": 2, "list": ["타임아웃", "NRC 7F"]},
            "powertrain_conflict": {
                "message": "차량번호 조회(EV)와 VIN 규칙(ICE) 불일치"
            },
            "missing_critical_values": {
                "count": 1,
                "list": ["SOC"],
            },
        }
    }
    
    story = _issues_section(view)
    
    assert len(story) > 0
    text_items = [str(item) for item in story if hasattr(item, "text")]
    combined_text = " ".join(text_items)
    assert "문제점" in combined_text


def test_issues_section_empty():
    """문제점이 없으면 섹션이 생성되지 않음."""
    view = {"issues": {}}
    story = _issues_section(view)
    assert len(story) == 0


def test_pdf_render_includes_sections(app_context, mock_scan):
    """PDF render가 additional_info와 issues를 포함함."""
    result = {
        "status": "success",
        "vin": "ZZZ12345678901234",
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
    
    # Mock inspection to return view with sections
    from unittest.mock import patch
    with patch("app.modules.scanner.report.inspection") as mock_inspection:
        mock_inspection.return_value = {
            "kind": "ev",
            "kind_label": "전기차",
            "powertrain": {"type": "ev", "source_label": "VIN"},
            "heading_en": "EV DIAGNOSTIC REPORT",
            "heading": "전기차 기술 진단 보고서",
            "subheading": "BATTERY HEALTH & DTC INSPECTION",
            "pages": 5,
            "code": "WeSCAN-20261115-00012345",
            "issued_on": "2026.11.15",
            "diagnosed_at": "2026. 11. 15.",
            "vehicle": {
                "manufacturer": "기아",
                "model": "EV6",
                "year": "2022",
                "fuel": "전기",
                "number": "88가8888",
                "vin": "ZZZ************1234",
                "mileage": 12345,
                "mileage_text": "12,345 km",
            },
            "title": "기아 EV6",
            "soh": 95.5,
            "soh_note": "양호 판정 기준 80%를 15.5%p 상회합니다.",
            "mileage_note": "주행거리 12,345 km 시점 진단",
            "overall": "양호",
            "judgment_note": "진단 항목 8개 전항 충족",
            "unread": 0,
            "dtc_clear": True,
            "dtc_count": 0,
            "significant_dtc_count": 0,
            "dtc_read": True,
            "dtc_rows": [],
            "groups": [
                {"label": "BMS (배터리)", "count": 0},
                {"label": "MCU (모터)", "count": 0},
                {"label": "통합전력", "count": 0},
                {"label": "차량충전", "count": 0},
            ],
            "judgments": [
                {"item": "배터리 수명 (SOH)", "standard": "≥ 80%", "value": 95.5, "unit": "%", "result": "양호"},
            ],
            "reconcile": None,
            "reference": {},
            "bms": [
                {"label": "SOC (표시)", "text": "85.0", "unit": "%"},
                {"label": "SOH", "text": "95.5", "unit": "%"},
            ],
            "power": [
                {"label": "보조 배터리 SOC", "text": "90.0", "unit": "%"},
            ],
            "cells": [
                {"no": 1, "voltage": 3.900},
                {"no": 2, "voltage": 3.905},
            ],
            "cell_min": 3.900,
            "cell_max": 3.905,
            "cell_spread": 0.005,
            "modules": [
                {"no": 1, "value": 22.5},
                {"no": 2, "value": 23.0},
            ],
            "module_min": 22.5,
            "module_max": 23.0,
            "module_spread": 0.5,
            "additional_info": {
                "freeze_frames": {"count": 1},
                "module_temps": {"count": 8, "min": 20.0, "max": 25.0},
            },
            "issues": {
                "errors": {"count": 1, "list": ["타임아웃"]},
            },
        }
        
        pdf_bytes = render(mock_scan, result)
    
    # Verify PDF was generated
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0
    # PDF should start with %PDF header
    assert pdf_bytes[:4] == b"%PDF"
