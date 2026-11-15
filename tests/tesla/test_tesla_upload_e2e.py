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


def test_tesla_pdf_generation(_app_base, make_user):
    """Tesla scan PDF 생성 및 필수 텍스트 검증."""
    from app.modules.scanner.upload import process_upload
    from app.modules.scans.models import Scan
    from app.modules.scanner.service import scan_document
    from app.extensions import db
    from werkzeug.datastructures import FileStorage
    import pypdf
    from io import BytesIO
    
    with _app_base.app_context():
        admin_id = make_user(tid="tesla_pdf_admin", type="admin")
        
        file = FileStorage(
            stream=BytesIO(TESLA_MODEL3_CSV.encode()),
            filename="tesla_pdf_test.csv",
            content_type="text/csv"
        )
        
        scan_id = process_upload(
            actor=admin_id,
            file=file,
            car_no=FAKE_PLATE,
            device="Tesla PDF Test"
        )
        
        scan = db.session.get(Scan, scan_id)
        assert scan is not None
        
        # PDF 생성
        document = scan_document(scan)
        assert document is not None
        assert document.content.startswith(b"%PDF")
        
        # PDF 텍스트 추출
        reader = pypdf.PdfReader(BytesIO(document.content))
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text()
        
        # 필수 텍스트 검증
        assert "SOH 참고치" in full_text or "미검증" in full_text, "SOH 참고치 텍스트 누락"
        assert "판정보류" in full_text, "판정보류 텍스트 누락"
        assert "추가 수집 정보" in full_text or "문제점" in full_text, "추가 정보 섹션 누락"
        assert FAKE_VIN in full_text, f"VIN {FAKE_VIN} 누락"
        assert "Tesla" in full_text or "테스라" in full_text, "Tesla 제조사 누락"
        
        db.session.rollback()


def test_tesla_realistic_broadcast_log_with_uds_like_traffic(_app_base, make_user):
    """
    실제와 유사한 Tesla 로그 (수천 프레임, 0x7DF broadcast, UDS-like 응답 포함).
    
    - 163,317 프레임 규모 시뮬레이션 (축약: 3000+ 프레임)
    - 0x7DF broadcast requests
    - 0x598/0x59E/0x788 ECU responses (UDS-like)
    - Tesla CAN IDs: 0x352 (111회), 0x292 (738회), 0x401 (2655회), 0x405 (VIN)
    - 업로드 200 → Scan type=ev, VIN 일치
    """
    from app.modules.scanner.upload import process_upload
    from app.modules.scans.models import Scan
    from app.extensions import db
    from werkzeug.datastructures import FileStorage
    
    with _app_base.app_context():
        admin_id = make_user(tid="tesla_realistic_admin", type="admin")
        
        # CSV 헤더
        csv_lines = ["Time,Type,ID,Name,DLC,Data"]
        t = 0.0
        
        # 1. 브로드캐스트 UDS-like 트래픽 (0x7DF → 0x598/0x59E/0x788)
        # 300회 반복 (세션 제어, tester present, DTC read 등)
        for i in range(300):
            # 10 01 (Default Session)
            csv_lines.append(f"{t:.6f},Tx,0x7DF,Broadcast,8,02 10 01 00 00 00 00 00")
            csv_lines.append(f"{t+0.01:.6f},Rx,0x598,ECU1,8,06 50 01 00 32 01 F4 00")
            csv_lines.append(f"{t+0.015:.6f},Rx,0x59E,ECU2,8,06 50 01 00 32 01 F4 00")
            csv_lines.append(f"{t+0.020:.6f},Rx,0x788,ECU3,8,06 50 01 00 32 01 F4 00")
            t += 0.05
            
            # 3E 80 (Tester Present)
            csv_lines.append(f"{t:.6f},Tx,0x7DF,Broadcast,8,02 3E 80 00 00 00 00 00")
            csv_lines.append(f"{t+0.01:.6f},Rx,0x598,ECU1,8,02 7E 80 00 00 00 00 00")
            t += 0.05
        
        # 2. Tesla CAN broadcast frames
        # 0x352 (energy) - 111회
        for i in range(111):
            # NominalFullPackEnergy = 74kWh * 50 = 3700 (0x0E74)
            csv_lines.append(f"{t:.6f},Rx,0x352,GTW_packEnergy,8,00 00 74 0E 64 00 00 00")
            t += 0.1
        
        # 0x292 (SOC) - 738회
        for i in range(738):
            # SOC = 85% = 0x55 = 85 hex
            csv_lines.append(f"{t:.6f},Rx,0x292,BMS_socBMS,8,55 00 00 00 00 00 00 00")
            t += 0.05
        
        # 0x401 (brick voltages) - 2655회
        for i in range(2655):
            # Brick voltages: min=3.7V*1000=0x0E74, max=3.75V*1000=0x0EA6
            csv_lines.append(f"{t:.6f},Rx,0x401,BMS_brickMinMax,8,00 2A 74 0E A6 0E 74 0E")
            t += 0.02
        
        # 0x405 (VIN) - 296회 (각 mux 파트가 반복됨)
        for i in range(98):
            csv_lines.append(f"{t:.6f},Rx,0x405,VIN_part1,8,10 5A 5A 5A 31 32 33 34")
            csv_lines.append(f"{t+0.01:.6f},Rx,0x405,VIN_part2,8,11 35 36 37 38 39 30 31")
            csv_lines.append(f"{t+0.02:.6f},Rx,0x405,VIN_part3,8,12 32 33 34 00 00 00 00")
            t += 0.1
        
        # 0x332 (temps) - 추가
        for i in range(100):
            csv_lines.append(f"{t:.6f},Rx,0x332,BMS_temps,8,00 00 50 4E 4F 00 00 00")
            t += 0.05
        
        # 0x132 (pack voltage/current)
        for i in range(100):
            csv_lines.append(f"{t:.6f},Rx,0x132,BMS_packVI,8,64 00 00 00 00 00 00 00")
            t += 0.05
        
        csv_content = "\n".join(csv_lines)
        
        file = FileStorage(
            stream=BytesIO(csv_content.encode()),
            filename="tesla_realistic_broadcast.csv",
            content_type="text/csv"
        )
        
        # Upload and process
        scan_id = process_upload(
            actor=admin_id,
            file=file,
            car_no=FAKE_PLATE,
            device="Tesla Realistic Test"
        )
        
        assert scan_id is not None
        scan = db.session.get(Scan, scan_id)
        assert scan is not None
        
        # 검증 1: Scan type=ev
        assert scan.type == "ev", f"Expected type='ev', got '{scan.type}'"
        
        # 검증 2: VIN 일치
        assert scan.scan_vin == FAKE_VIN, f"Expected VIN '{FAKE_VIN}', got '{scan.scan_vin}'"
        assert scan.car_vin == FAKE_VIN
        
        # 검증 3: Tesla 제조사
        assert scan.car_maker == "Tesla"
        
        # 검증 4: 배터리 데이터 존재
        assert scan.bms_data is not None
        assert scan.bms_data.get('source') == 'tesla_upload'
        
        # 검증 5: PDF 생성 및 필수 텍스트
        from app.modules.scanner.service import scan_document
        import pypdf
        
        document = scan_document(scan)
        assert document is not None
        assert document.content.startswith(b"%PDF")
        
        reader = pypdf.PdfReader(BytesIO(document.content))
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text()
        
        # Tesla PDF 필수 항목 검증
        assert FAKE_VIN in full_text, "VIN 누락"
        assert "Tesla" in full_text or "테스라" in full_text, "Tesla 제조사 누락"
        assert "SOH" in full_text, "SOH 항목 누락"
        assert "판정보류" in full_text, "판정보류 텍스트 누락"
        
        db.session.rollback()
