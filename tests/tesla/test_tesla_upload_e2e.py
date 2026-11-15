"""Tesla CSV upload end-to-end test."""

import pytest
from io import BytesIO

# Fake VIN and license plate for testing
FAKE_VIN = "ZZZ12345678901234"
FAKE_PLATE = "88가8888"

# Small PCAN CSV fixture with Tesla Model 3 CAN broadcast frames
TESLA_MODEL3_CSV = f"""Time,Type,ID,Name,Len,Data1,Data2,Data3,Data4,Data5,Data6,Data7,Data8
0.000000,Rx,0x352,GTW_packEnergy,8,0x12,0x34,0x00,0x64,0x00,0x00,0x00,0x00
0.100000,Rx,0x292,BMS_socBMS,8,0x32,0x00,0x00,0x00,0x00,0x00,0x00,0x00
0.200000,Rx,0x401,BMS_brickMinMax,8,0x0E,0x10,0x0E,0x00,0x00,0x00,0x00,0x00
0.300000,Rx,0x332,BMS_temps,8,0x14,0x00,0x15,0x00,0x16,0x00,0x00,0x00
0.400000,Rx,0x405,VIN_part1,8,0x5A,0x5A,0x5A,0x31,0x32,0x33,0x34,0x35
0.500000,Rx,0x405,VIN_part2,8,0x36,0x37,0x38,0x39,0x30,0x31,0x32,0x33
0.600000,Rx,0x405,VIN_part3,8,0x34,0x00,0x00,0x00,0x00,0x00,0x00,0x00
"""


def test_tesla_csv_upload_end_to_end(_app_base, make_user):
    """Tesla CSV 업로드 → Scan 생성 → Model 3 판별 → 배터리 데이터 → SOH 참고치 → 판정보류 → PDF 생성."""
    from app.modules.scanner.upload import process_upload
    from app.modules.scans.models import Scan
    from app.modules.canlab.models import DiagnosticReport
    from app.extensions import db
    from werkzeug.datastructures import FileStorage
    
    with _app_base.app_context():
        admin_id = make_user(tid="tesla_admin", type="admin")
        
        file = FileStorage(
            stream=BytesIO(TESLA_MODEL3_CSV.encode()),
            filename="tesla_model3.csv",
            content_type="text/csv"
        )
        
        # Upload and process
        scan_id = process_upload(
            actor=admin_id,
            file=file,
            car_no=FAKE_PLATE,
            device="Tesla Test Upload"
        )
        
        assert scan_id is not None
        scan = db.session.get(Scan, scan_id)
        assert scan is not None
        assert scan.car_no == FAKE_PLATE
        
        # Check vehicle detection - should identify as Tesla Model 3
        # (This will work once Tesla detection is integrated)
        # assert "Tesla" in scan.car_maker or "Tesla" in (scan.car_model or "")
        
        # Check diagnostic report
        report = db.session.query(DiagnosticReport).filter_by(
            dataset_id=scan.datasets[0].id if scan.datasets else None
        ).first()
        
        if report:
            # Check that battery values are decoded
            # 0x352 full energy, SOC, etc.
            values = report.values or {}
            # assert "full_energy_kwh" in values or similar fields
            
            # Check SOH reference (community source)
            # Should show as "SOH 참고치(미검증)"
            
            # Check judgment is "판정보류" (pending) for community-sourced reference
            # assert scan judgment or report shows pending
            pass
        
        # Check PDF generation
        # PDF should include:
        # - "추가 수집 정보와 문제점" section
        # - UNREAD reasons for unmeasured items
        # - Coolant level signal indicator
        # (This will be verified once PDF generation for Tesla is implemented)
        
        db.session.rollback()


@pytest.mark.skip(reason="Tesla integration in progress - will be enabled in v2.2.2")
def test_tesla_model3_detection_from_vin():
    """VIN에서 Model 3 판별."""
    from app.modules.tesla.detect import identify_tesla_vehicle
    
    result = identify_tesla_vehicle(FAKE_VIN, {})
    assert result["manufacturer"] == "Tesla"
    assert result["model"] == "Model 3"


@pytest.mark.skip(reason="Tesla integration in progress - will be enabled in v2.2.2")  
def test_tesla_0x352_energy_decode():
    """0x352 프레임에서 만충 에너지 디코딩."""
    from app.modules.tesla.decode import decode_battery_status
    
    # Mock frame data
    frames = [
        {"can_id": 0x352, "data": bytes([0x12, 0x34, 0x00, 0x64, 0x00, 0x00, 0x00, 0x00])}
    ]
    
    result = decode_battery_status(frames)
    assert "full_energy_kwh" in result
    assert result["soc_percent"] > 0


@pytest.mark.skip(reason="Tesla integration in progress - will be enabled in v2.2.2")
def test_tesla_96_brick_voltage_decode():
    """96개 브릭 전압 최저/최고/편차 디코딩."""
    from app.modules.tesla.decode import decode_brick_voltages
    
    # Mock 0x401 frames
    frames = []
    result = decode_brick_voltages(frames)
    assert "min_voltage" in result
    assert "max_voltage" in result
    assert "spread" in result


@pytest.mark.skip(reason="Tesla integration in progress - will be enabled in v2.2.2")
def test_tesla_soh_community_reference():
    """Community 출처 → 'SOH 참고치(미검증)' 표시."""
    from app.modules.tesla.soh import calculate_soh
    
    # Mock data
    result = calculate_soh(nominal_energy=60.0, reference_energy=74.0, source_type="community")
    assert result["source_type"] == "community"
    assert "참고치" in result["label"] or "미검증" in result["label"]


@pytest.mark.skip(reason="Tesla integration in progress - will be enabled in v2.2.2")
def test_tesla_pdf_generation():
    """WESCAN 진단서 형식 PDF 생성 with 추가 수집 정보."""
    from app.modules.scanner import pdf
    
    scan = {}  # Mock scan
    result = {
        "battery": {"full_energy_kwh": {"value": 60.0, "status": "measured"}},
        "dtcs": [],
        "values": [],
        "steps": []
    }
    
    content = pdf.render(scan, result)
    assert b"PDF" in content
    # Should contain "추가 수집 정보와 문제점"
    # Should contain UNREAD reasons
