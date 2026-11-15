"""Test WESCAN official report format adoption.

사용자 요구사항:
- WESCAN 공식 진단서 양식을 기본으로
- 추가 수집 정보 섹션 (맨 마지막)
- 문제점 섹션 (추가 정보 다음)
- 출처 없는 수치는 NULL/미확인
- 차량번호와 VIN 마스킹
"""
import pytest
from app.modules.scanner.report import basic_report, _collect_additional_info, _collect_issues
from datetime import datetime


def test_basic_report_includes_additional_info_and_issues():
    """Test that basic_report includes additional_info and issues sections."""
    # Minimal fake data
    car = {
        "diag_company": "현대",
        "diag_model": "아이오닉5",
        "diag_fuel": "전기",
    }
    
    result = {
        "status": "ok",
        "vin": None,
        "values": [],
        "battery": {},
        "dtcs": [],
        "errors": [],
        "steps": [{"command": "ATZ", "reply": "OK"}],
    }
    
    report = basic_report(
        scan_id=1,
        diagnosed_at=datetime(2026, 11, 15, 0, 0, 0),
        car_no="88가8888",
        car=car,
        result=result,
        report_id=1,
        pdf_url="/test.pdf",
    )
    
    # Verify WESCAN standard fields exist
    assert "diagnosis_info" in report
    assert "vehicle" in report
    assert "report" in report
    assert "dtc" in report
    assert "sensor" in report
    assert "judgments" in report
    
    # Verify additional_info and issues sections exist
    assert "additional_info" in report, "additional_info section must exist"
    assert "issues" in report, "issues section must exist"
    
    # Verify structure
    assert isinstance(report["additional_info"], dict)
    assert isinstance(report["issues"], dict)


def test_additional_info_collection():
    """Test that additional info is collected correctly."""
    # Result with various additional data
    result = {
        "status": "ok",
        "freeze": [{"dtc": "P0420", "value": 100}],
        "monitors": [{"mid": "01", "value": 0}],
        "values": [{"key": "coolant_temp", "value": 80}],
        "battery": {
            "soc": {"value": 75},
        },
        "diagnosis": {
            "ecus": [
                {"ecu": "7E4", "snapshots": [{"did": "0105"}]}
            ]
        }
    }
    
    is_ev = True
    info = _collect_additional_info(result, is_ev)
    
    # Verify freeze frame detected
    assert "freeze_frame" in info
    assert info["freeze_frame"]["count"] == 1
    assert info["freeze_frame"]["available"] is True
    
    # Verify realtime values detected
    assert "realtime_values" in info
    assert info["realtime_values"]["count"] == 1
    
    # Verify emission monitors detected
    assert "emission_monitors" in info
    assert info["emission_monitors"]["count"] == 1
    
    # Verify UDS snapshots detected
    assert "uds_snapshots" in info
    assert info["uds_snapshots"]["count"] == 1


def test_issues_collection_with_errors():
    """Test that issues are collected correctly when errors exist."""
    car = {"diag_company": "현대"}
    
    result = {
        "status": "partial",
        "errors": [
            {"label": "VIN 조회 실패", "status": "fail"},
            {"label": "BMS 통신 실패", "status": "fail"},
        ],
        "battery": {},
    }
    
    kind = {"type": "ev"}
    
    issues = _collect_issues(result, car, kind)
    
    # Verify errors detected
    assert "errors" in issues
    assert issues["errors"]["count"] == 2
    assert len(issues["errors"]["summary"]) == 2
    
    # Verify scan status
    assert "scan_status" in issues
    assert issues["scan_status"]["status"] == "partial"


def test_issues_collection_with_missing_critical_values():
    """Test that missing critical values are detected."""
    car = {"diag_company": "현대"}
    
    result = {
        "status": "ok",
        "errors": [],
        "battery": {},  # No SOC, no SOH
    }
    
    kind = {"type": "ev"}
    
    issues = _collect_issues(result, car, kind)
    
    # Verify missing critical values detected
    assert "missing_critical_values" in issues
    assert issues["missing_critical_values"]["count"] >= 1
    assert "SOC" in " ".join(issues["missing_critical_values"]["list"])


def test_no_additional_info_when_data_absent():
    """Test that additional_info is empty when no extra data exists."""
    result = {
        "status": "ok",
        "errors": [],
        "battery": {},
        "values": [],
    }
    
    is_ev = False
    info = _collect_additional_info(result, is_ev)
    
    # Should be empty dict or only have unavailable items
    assert isinstance(info, dict)
    # No freeze, no monitors, no values -> empty
    assert len(info) == 0


def test_no_issues_when_scan_successful():
    """Test that issues is empty when scan is successful."""
    car = {"diag_company": "현대"}
    
    result = {
        "status": "ok",
        "errors": [],
        "battery": {
            "soc": {"value": 75},
            "soh": {"value": 85},
        },
    }
    
    kind = {"type": "ev"}
    
    issues = _collect_issues(result, car, kind)
    
    # Should not have errors or scan_status issues
    assert "errors" not in issues or issues["errors"]["count"] == 0
    # Should not have missing critical values (SOC and SOH present)
    assert "missing_critical_values" not in issues
