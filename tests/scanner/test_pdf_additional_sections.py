"""Test PDF report includes additional_info and issues sections.

Bug fix 2026-11-15: PDF 보고서에 '추가 수집 정보'와 '문제점' 섹션이 빠져 있었음.
"""

import pytest
from io import BytesIO
from unittest.mock import MagicMock

from app.modules.scanner.pdf import render, _additional_info_section, _issues_section
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


def test_pdf_sections_structure():
    """PDF에 추가 수집 정보와 문제점 섹션이 추가되었는지 구조 검증.
    
    실제 PDF 생성은 다른 통합 테스트에서 검증됩니다.
    여기서는 섹션 함수가 존재하고 올바른 구조를 반환하는지만 확인합니다.
    """
    # _additional_info_section and _issues_section 함수가 존재하는지 확인
    from app.modules.scanner.pdf import _additional_info_section, _issues_section
    
    # Functions are callable
    assert callable(_additional_info_section)
    assert callable(_issues_section)
    
    # Empty view returns empty list or valid structure
    empty_result = _additional_info_section({})
    assert isinstance(empty_result, list)
    assert len(empty_result) == 0
    
    empty_issues = _issues_section({})
    assert isinstance(empty_issues, list)
    assert len(empty_issues) == 0
