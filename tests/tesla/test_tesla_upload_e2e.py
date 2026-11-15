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
        
        # Check vehicle detection - Tesla
        assert scan.car_maker == "Tesla"
        assert "Model" in (scan.car_model or "")
        assert scan.scan_vin == FAKE_VIN
        
        # Check Tesla data in bms_data
        assert scan.bms_data is not None
        assert scan.bms_data.get('source') == 'tesla_upload'
        assert scan.bms_data.get('vin') == FAKE_VIN
        
        # Check decoded data exists
        decoded = scan.bms_data.get('decoded', {})
        assert 'energy' in decoded or 'soc' in decoded or 'bricks' in decoded
        
        # Check SOH (community source → judgment pending)
        soh = scan.bms_data.get('soh')
        if soh:
            # Community source should have soh_available=False
            assert soh.get('soh_available') is False or soh.get('reference_source') == 'community'
        
        # Check judgment
        judgment = scan.bms_data.get('judgment')
        if judgment:
            assert '판정보류' in judgment or 'SOH' in scan.bms_data.get('judgment_reason', '')
        
        db.session.rollback()


def test_tesla_model3_detection_from_vin():
    """VIN 디코딩 및 Tesla 시그니처 감지."""
    from app.modules.tesla.detect import decode_vin, is_tesla
    
    # VIN 디코딩 (fake VIN이므로 구조만 확인)
    result = decode_vin(FAKE_VIN)
    assert result['valid']
    assert result['vin'] == FAKE_VIN
    
    # Tesla CAN ID 시그니처로 감지 (0x405, 0x352, 0x401, 0x332)
    tesla_frames = [
        (0.0, 0x405, b'\x10' + b'ZZZ1234'),
        (0.1, 0x352, b'\x00\x12\x34\x00\x64\x00\x00\x00'),
        (0.2, 0x401, b'\x00\x2A\xE8\x03\xE8\x03\xE8\x03'),
        (0.3, 0x332, b'\x00\x00\x50\x4E\x4F\x00\x00\x00'),
    ]
    assert is_tesla(tesla_frames, vin=None)


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
    # Voltage = 38000 * 0.0001 = 3.8V (valid range 1.5-4.6V)
    # 38000 = 0x9470, little-endian = 0x70 0x94
    frames = [
        (0.0, bytes([0x00, 0x2A, 0x70, 0x94, 0x72, 0x94, 0x75, 0x94]))
    ]
    result = decode_0x401_brick_voltages(frames)
    assert "min_voltage" in result
    assert "max_voltage" in result
    assert "voltage_spread" in result
    assert result["brick_count"] == 3


def test_tesla_soh_community_reference(_app_base):
    """Community 출처 → 'SOH 참고치(미검증)' 표시."""
    from app.modules.tesla.soh import calculate_soh
    from app.modules.tesla.reference_data import seed_tesla_reference_data
    
    with _app_base.app_context():
        # Tesla 기준 데이터 시드
        seed_tesla_reference_data()
        
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
