"""번호판 마스킹 보안 테스트."""
from datetime import datetime, timezone
from io import BytesIO

import pypdf
import pytest


def _create_scan_with_plate(user, car_no: str, car_vin: str):
    """번호판과 VIN을 가진 테스트 스캔 생성."""
    from app.modules.scans.models import Scan
    from app.extensions import db
    
    scan = Scan(
        tester_id=user.id,
        device_type="manual",
        device_uid="test-device",
        car_maker="현대",
        car_model="아이오닉5",
        car_year=2023,
        car_fuel="electric",
        car_no=car_no,
        car_vin=car_vin,
        car_distance=50000,
        type="ev",
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(scan)
    db.session.flush()
    return scan


def test_mask_plate_function():
    """mask_plate 함수 동작 검증."""
    from app.modules.scanner.pdf import mask_plate
    
    assert mask_plate("88가8888") == "88가****"
    assert mask_plate("123가1234") == "123가****"
    assert mask_plate("12나3456") == "12나****"
    assert mask_plate("") == ""
    assert mask_plate(None) == None
    # 한글이 없으면 앞 3자 + ****
    assert mask_plate("1234567") == "123****"


def test_pdf_filename_masks_plate(_app_base, make_user):
    """PDF 파일명이 마스킹된 번호판을 포함."""
    from app.modules.scanner.pdf import filename
    from app.modules.accounts.models import User
    from app.extensions import db
    
    user_id = make_user(tid="plate_test_user", type="tester")
    with _app_base.app_context():
        user = db.session.get(User, user_id)
        scan = _create_scan_with_plate(user, "88가8888", "KMHTA12345678901")
        
        fname = filename(scan)
        
        # ASCII filename은 번호판을 포함하지 않음
        assert fname.isascii(), f"Filename should be ASCII-only: {fname}"
        assert fname.startswith("wescan-report-")
        assert fname.endswith(".pdf")
        # 번호판 미포함 (한글, 마스킹 모두 없음)
        assert "88가" not in fname
        assert "8888" not in fname


def test_pdf_text_does_not_contain_full_plate(_app_base, make_user):
    """PDF 본문 텍스트에 전체 번호판이 없음."""
    from app.modules.scanner.pdf import render
    from app.modules.accounts.models import User
    from app.extensions import db
    
    user_id = make_user(tid="pdf_text_user", type="tester")
    
    with _app_base.app_context():
        user = db.session.get(User, user_id)
        scan = _create_scan_with_plate(user, "88가8888", "KMHTA12345678901")
        
        # 최소 진단 결과 구조
        result = {
            "car": {
                "diag_company": "현대",
                "diag_model": "아이오닉5",
                "diag_year": "2023",
                "diag_fuel": "electric",
            },
            "powertrain": {"type": "ev", "source": "battery_data", "plugin": False, "hydrogen": False},
            "battery": {
                "bms_soc": 85.5,
                "bms_soh": 92.3,
                "bms_pack_voltage": 355.2,
                "bms_pack_current": 12.5,
                "bms_battery_temp_max": 28.5,
                "bms_battery_temp_min": 26.8,
            },
            "values": [{"key": "odometer", "value": 50000}],
            "vin": "KMHTA12345678901",
            "dtcs": [],
            "steps": [],
        }
        
        # PDF 생성
        pdf_bytes = render(scan, result)
        
        # PDF 텍스트 추출
        reader = pypdf.PdfReader(BytesIO(pdf_bytes))
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text()
        
        # 검증: 전체 번호판이 없고, 마스킹된 번호판이 있음
        assert "88가8888" not in full_text, "PDF 본문에 전체 번호판이 노출되었습니다"
        assert "88가****" in full_text, "PDF 본문에 마스킹된 번호판이 없습니다"
        
        # VIN은 전체가 있어야 함
        assert "KMHTA12345678901" in full_text, "VIN이 누락되었습니다"


def test_pdf_metadata_does_not_contain_full_plate(_app_base, make_user):
    """PDF 메타데이터(Title)에 전체 번호판이 없음."""
    from app.modules.scanner.pdf import render
    from app.modules.accounts.models import User
    from app.extensions import db
    
    user_id = make_user(tid="pdf_metadata_user", type="tester")
    
    with _app_base.app_context():
        user = db.session.get(User, user_id)
        scan = _create_scan_with_plate(user, "88가8888", "KMHTA12345678901")
        
        result = {
            "car": {"diag_company": "현대", "diag_model": "아이오닉5", "diag_year": "2023", "diag_fuel": "electric"},
            "powertrain": {"type": "ev", "source": "battery_data", "plugin": False, "hydrogen": False},
            "battery": {"bms_soc": 85.5, "bms_soh": 92.3},
            "values": [{"key": "odometer", "value": 50000}],
            "vin": "KMHTA12345678901",
            "dtcs": [],
            "steps": [],
        }
        
        pdf_bytes = render(scan, result)
        reader = pypdf.PdfReader(BytesIO(pdf_bytes))
        
        # PDF 메타데이터 Title 확인
        metadata = reader.metadata
        if metadata and "/Title" in metadata:
            title = metadata["/Title"]
            assert "88가8888" not in title, "PDF 메타데이터 Title에 전체 번호판이 노출되었습니다"
            assert "88가****" in title, "PDF 메타데이터 Title에 마스킹된 번호판이 없습니다"


def test_report_vehicle_number_is_masked(_app_base, make_user):
    """report.inspection이 반환하는 vehicle.number가 마스킹됨."""
    from app.modules.scanner import report as report_module
    from app.modules.accounts.models import User
    from app.extensions import db
    
    user_id = make_user(tid="report_vehicle_user", type="tester")
    
    with _app_base.app_context():
        user = db.session.get(User, user_id)
        scan = _create_scan_with_plate(user, "88가8888", "KMHTA12345678901")
        
        result = {
            "car": {"diag_company": "현대", "diag_model": "아이오닉5"},
            "powertrain": {"type": "ev", "source": "battery_data", "plugin": False, "hydrogen": False},
            "battery": {"bms_soc": 85.5, "bms_soh": 92.3},
            "values": [{"key": "odometer", "value": 50000}],
            "vin": "KMHTA12345678901",
            "dtcs": [],
        }
        
        view = report_module.inspection(scan, result)
        
        assert view["vehicle"]["number"] == "88가****"
        assert view["vehicle"]["vin"] == "KMHTA12345678901"  # VIN은 전체
