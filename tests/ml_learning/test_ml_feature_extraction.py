"""ML feature extraction real-path test (v2.2.8 requirement)."""

import pytest
from io import BytesIO
from werkzeug.datastructures import FileStorage


FAKE_TESLA_VIN = "5YJ3E1EA9KF123456"
FAKE_EV_PLATE = "99서9999"
FAKE_TESLA_PLATE = "88테8888"


def test_ml_feature_extraction_tesla_upload_real_path(_app_base, make_user):
    """
    Tesla 업로드 스캔의 ML feature 추출 실경로 테스트 (v2.2.8 Part 2).
    
    요구사항:
    - Tesla CSV 업로드 → process_upload → _process_tesla_upload
    - Scan 생성 후 extract_and_store_features 호출
    - 정확히 하나의 MLScanFeature 행 생성
    - decoded_values에 plate/VIN 없음 (익명화)
    - scan.device_type 사용 (not scan.device)
    - bms_data layout 처리 (decoded/soh at top level)
    """
    from app.extensions import db
    from app.modules.scans.models import Scan
    from app.modules.ml_learning.models import MLScanFeature
    from app.modules.scanner.upload import process_upload
    
    with _app_base.app_context():
        admin = make_user(tid="ml_tesla_admin", type="admin")
        
        # Tesla CSV
        csv_content = f"""Time,Type,ID,Name,DLC,Data
0.000000,Rx,0x352,GTW_packEnergy,8,00 12 34 00 64 00 00 00
0.100000,Rx,0x292,BMS_socBMS,8,32 00 00 00 00 00 00 00
0.200000,Rx,0x401,BMS_brickMinMax,8,00 2A E8 03 E8 03 60 00
0.300000,Rx,0x332,BMS_temps,8,00 00 50 4E 4F 00 00 00
0.400000,Rx,0x405,VIN_part1,8,10 35 59 4A 33 45 31 45
0.500000,Rx,0x405,VIN_part2,8,11 41 39 4B 46 31 32 33
0.600000,Rx,0x405,VIN_part3,8,12 34 35 36 00 00 00 00
0.700000,Rx,0x132,BMS_packVI,8,64 00 00 00 00 00 00 00
"""
        
        file = FileStorage(
            stream=BytesIO(csv_content.encode()),
            filename="tesla_test.csv",
            content_type="text/csv"
        )
        
        # 기존 feature 개수
        before_count = db.session.query(MLScanFeature).count()
        
        # Upload (should trigger feature extraction)
        scan_id = process_upload(
            actor=admin,
            file=file,
            car_no=FAKE_TESLA_PLATE,
            device="Tesla ML Test"
        )
        
        assert scan_id is not None
        scan = db.session.get(Scan, scan_id)
        assert scan is not None
        assert scan.bms_data is not None
        assert scan.bms_data.get('source') == 'tesla_upload'
        
        # Requirement: 정확히 하나의 MLScanFeature 행 생성
        after_count = db.session.query(MLScanFeature).count()
        assert after_count == before_count + 1, \
            f"Expected exactly 1 new feature, got {after_count - before_count}"
        
        # 가장 최근 feature 조회
        feature = db.session.query(MLScanFeature).order_by(
            MLScanFeature.created_at.desc()
        ).first()
        
        assert feature is not None
        
        # Requirement: scan_id is stored for idempotency (not NULL)
        assert feature.scan_id == scan.id
        
        # Requirement: maker/model/fuel populated
        assert feature.maker == "Tesla"
        assert feature.fuel_type in ["ev", "전기"]
        
        # Requirement: decoded_values에 plate/VIN 없음
        decoded_values = feature.decoded_values or {}
        assert isinstance(decoded_values, dict)
        
        # Check no VIN/plate in keys or values
        for key, value in decoded_values.items():
            assert "vin" not in key.lower(), f"VIN key found: {key}"
            assert "plate" not in key.lower(), f"Plate key found: {key}"
            if isinstance(value, str):
                assert FAKE_TESLA_VIN not in value, f"VIN value found: {value}"
                assert FAKE_TESLA_PLATE not in value, f"Plate value found: {value}"
        
        # Requirement: signals_read non-empty (Tesla upload layout handled)
        signals_read = feature.signals_read or {}
        assert len(signals_read) > 0, "signals_read should not be empty for Tesla upload"
        
        db.session.rollback()


def test_ml_feature_extraction_ev_upload_real_path(_app_base, make_user):
    """
    일반 EV 업로드 스캔의 ML feature 추출 실경로 테스트.
    
    요구사항:
    - 일반 UDS CSV 업로드 → process_upload
    - Scan 생성 후 extract_and_store_features 호출
    - 정확히 하나의 MLScanFeature 행 생성
    - decoded_values에 plate/VIN 없음
    """
    from app.extensions import db
    from app.modules.scans.models import Scan
    from app.modules.ml_learning.models import MLScanFeature
    from app.modules.scanner.upload import process_upload
    
    with _app_base.app_context():
        admin = make_user(tid="ml_ev_admin", type="admin")
        
        # 일반 EV9 UDS CSV
        csv_content = """Timestamp,Channel,CAN_ID,DLC,Data
0.000000,1,0x7E4,8,02 10 01 00 00 00 00 00
0.010000,1,0x7EC,8,06 50 01 00 32 01 F4 00
0.020000,1,0x7E4,8,03 22 01 01 00 00 00 00
0.030000,1,0x7EC,8,10 14 62 01 01 4B 49 41
0.040000,1,0x7E4,8,30 00 00 00 00 00 00 00
0.050000,1,0x7EC,8,21 20 45 56 39 00 00 00
"""
        
        file = FileStorage(
            stream=BytesIO(csv_content.encode()),
            filename="ev9_test.csv",
            content_type="text/csv"
        )
        
        before_count = db.session.query(MLScanFeature).count()
        
        # Upload
        scan_id = process_upload(
            actor=admin,
            file=file,
            car_no=FAKE_EV_PLATE,
            device="EV ML Test"
        )
        
        assert scan_id is not None
        scan = db.session.get(Scan, scan_id)
        assert scan is not None
        
        # Requirement: 정확히 하나의 MLScanFeature 행 생성
        after_count = db.session.query(MLScanFeature).count()
        assert after_count == before_count + 1, \
            f"Expected exactly 1 new feature, got {after_count - before_count}"
        
        # 가장 최근 feature 조회
        feature = db.session.query(MLScanFeature).order_by(
            MLScanFeature.created_at.desc()
        ).first()
        
        assert feature is not None
        assert feature.scan_id == scan.id  # Stored for idempotency
        
        # Requirement: decoded_values에 plate/VIN 없음
        decoded_values = feature.decoded_values or {}
        assert isinstance(decoded_values, dict)
        
        for key, value in decoded_values.items():
            assert "vin" not in key.lower()
            assert "plate" not in key.lower()
            if isinstance(value, str):
                assert FAKE_EV_PLATE not in value
        
        db.session.rollback()
