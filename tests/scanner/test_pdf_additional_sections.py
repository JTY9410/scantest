"""Test PDF report includes additional_info and issues sections.

Bug fix 2026-11-15: PDF 보고서에 '추가 수집 정보'와 '문제점' 섹션이 빠져 있었음.
"""

import pytest
from io import BytesIO
from unittest.mock import MagicMock

from app.modules.scanner.pdf import render, _additional_info_and_issues_section
from app.modules.scans.models import Scan


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


def test_additional_info_and_issues_section_with_data():
    """추가 수집 정보와 문제점 통합 섹션이 데이터와 함께 생성됨."""
    from app.modules.scanner.pdf import _fonts
    
    # Register fonts before creating PDF elements
    _fonts()
    
    view = {
        "additional_info": {
            "freeze_frames": {"count": 2},
            "module_temps": {"min": 20.5, "max": 25.3},
        },
        "issues": {
            "errors": {"count": 2, "list": ["타임아웃", "NRC 7F"]},
            "powertrain_conflict": {
                "message": "차량번호 조회(EV)와 VIN 규칙(ICE) 불일치"
            },
        }
    }
    
    story = _additional_info_and_issues_section(view)
    
    assert len(story) > 0
    # Check that the combined section was created
    text_items = [str(item) for item in story if hasattr(item, "text")]
    combined_text = " ".join(text_items)
    assert "추가 수집 정보와 문제점" in combined_text


def test_additional_info_and_issues_section_empty():
    """추가 정보와 문제점이 모두 없으면 섹션이 생성되지 않음."""
    view = {"additional_info": {}, "issues": {}}
    story = _additional_info_and_issues_section(view)
    assert len(story) == 0


def test_pdf_sections_structure():
    """PDF에 추가 수집 정보와 문제점 통합 섹션이 추가되었는지 구조 검증."""
    from app.modules.scanner.pdf import _additional_info_and_issues_section
    
    # Function is callable
    assert callable(_additional_info_and_issues_section)
    
    # Empty view returns empty list
    empty_result = _additional_info_and_issues_section({})
    assert isinstance(empty_result, list)
    assert len(empty_result) == 0
