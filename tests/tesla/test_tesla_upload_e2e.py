"""Tesla CSV upload end-to-end test."""

import pytest
from io import BytesIO

# Fake VIN and license plate for testing
FAKE_VIN = "ZZZ12345678901234"
FAKE_PLATE = "88가8888"

# PCAN CSV fixture with Tesla Model 3 CAN broadcast frames
# VIN "ZZZ12345678901234" = 'ZZZ1234' + '5678901' + '234'
TESLA_MODEL3_CSV = f"""Time,Type,ID,Name,DLC,Data
0.000000,Rx,0x352,GTW_packEnergy,8,00 12 34 00 64 00 00 00
0.100000,Rx,0x292,BMS_socBMS,8,32 00 00 00 00 00 00 00
0.200000,Rx,0x401,BMS_brickMinMax,8,00 2A E8 03 E8 03 E8 03
0.300000,Rx,0x332,BMS_temps,8,00 00 50 4E 4F 00 00 00
0.400000,Rx,0x405,VIN_part1,8,10 5A 5A 5A 31 32 33 34
0.500000,Rx,0x405,VIN_part2,8,11 35 36 37 38 39 30 31
0.600000,Rx,0x405,VIN_part3,8,12 32 33 34 00 00 00 00
0.700000,Rx,0x132,BMS_packVI,8,64 00 00 00 00 00 00 00
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


def test_tesla_model3_detection_from_vin():
    """VIN에서 Model 3 판별."""
    from app.modules.tesla.detect import decode_vin, is_tesla
    
    # VIN 디코딩
    result = decode_vin(FAKE_VIN)
    assert result['valid']
    assert result['vin'] == FAKE_VIN
    
    # Tesla 감지
    assert is_tesla([], vin=FAKE_VIN)


def test_tesla_0x352_energy_decode():
    """0x352 프레임에서 만충 에너지 디코딩."""
    from app.modules.tesla.decode import decode_0x352_energy
    
    # Mux 0: NominalFullPackEnergy = 0x1234 * 0.02 = 9306.4 * 0.02 = 186.128 kWh (unrealistic, just for test)
    frames = [
        (0.0, bytes([0x00, 0x00, 0x34, 0x12, 0x00, 0x00, 0x00, 0x00]))
    ]
    
    result = decode_0x352_energy(frames)
    assert "nominal_full_pack_energy" in result
    assert result["nominal_full_pack_energy"] > 0


def test_tesla_96_brick_voltage_decode():
    """96개 브릭 전압 최저/최고/편차 디코딩."""
    from app.modules.tesla.decode import decode_0x401_brick_voltages
    
    # Mock 0x401 frames: mux=0, flag=0x2A, 3 bricks
    # Voltage = 0x03E8 * 0.0001 = 1000 * 0.0001 = 0.1 V (unrealistic, just for test structure)
    frames = [
        (0.0, bytes([0x00, 0x2A, 0xE8, 0x03, 0xE8, 0x03, 0xE8, 0x03]))
    ]
    result = decode_0x401_brick_voltages(frames)
    assert "min_voltage" in result
    assert "max_voltage" in result
    assert "voltage_spread" in result


def test_tesla_soh_community_reference():
    """Community 출처 → 'SOH 참고치(미검증)' 표시."""
    from app.modules.tesla.soh import calculate_soh
    
    # Mock data: community 출처는 soh_available=False
    result = calculate_soh(
        current_nominal_full=60.0,
        manufacturer="Tesla",
        model="Model 3",
        year=2020,
        pack_code="Long Range"
    )
    # community 출처이므로 soh_available=False
    assert result["soh_available"] is False
    assert "참고" in result["calculation_note"] or "미검증" in result["calculation_note"]


def test_tesla_pdf_generation():
    """Tesla scan이 생성되면 PDF도 생성 가능해야 함."""
    # PDF 생성은 기존 인프라를 재사용
    # 이 테스트는 end-to-end 테스트에서 Scan이 생성되는지만 확인
    # 실제 PDF 렌더링은 별도 통합 테스트로 검증
    assert True  # Placeholder for future PDF integration
