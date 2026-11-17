"""v2.2.5 결함 수정 테스트."""

import pytest


def test_tesla_vin_with_nul_padding():
    """Tesla VIN 추출: mux 0x10 앞 NUL 패딩 무시, 문자셋만 추출."""
    from app.modules.tesla.detect import extract_vin_from_frames
    
    # mux 0x10: 앞 4바이트 NUL + 3바이트 유효 VIN
    # mux 0x11: 7바이트 유효 VIN
    # mux 0x12: 7바이트 유효 VIN (8바이트에 7개)
    frames = [
        (0.1, 0x405, b'\x10\x00\x00\x00\x005YJ'),  # mux 0x10: NUL padding + 5YJ
        (0.2, 0x405, b'\x11SA1E26H'),  # mux 0x11: SA1E26H
        (0.3, 0x405, b'\x12F123456\x00'),  # mux 0x12: F123456 + padding
    ]
    
    vin = extract_vin_from_frames(frames)
    
    # 유효한 17자 VIN, NUL 없음
    assert vin == "5YJSA1E26HF123456"
    assert '\x00' not in vin


def test_tesla_upload_vin_no_nul_in_db(_app_base, make_user):
    """Tesla 업로드: DB VIN에 NUL 없음."""
    from app.modules.scanner.upload import process_upload
    from app.modules.scans.models import Scan
    from werkzeug.datastructures import FileStorage
    from app.extensions import db
    from io import BytesIO
    
    # Tesla 픽스처 (실제 0x405 VIN 프레임)
    csv_content = b"""Timestamp,Channel,CAN_ID,DLC,Data
0.100000,1,00000405,8,10 00 00 00 00 35 59 4A
0.110000,1,00000405,8,11 53 41 31 45 32 36 48
0.120000,1,00000405,8,12 46 31 32 33 34 35 36
0.200000,1,00000352,8,AA BB CC DD EE FF 00 11
0.210000,1,00000292,8,11 22 33 44 55 66 77 88
"""
    
    with _app_base.app_context():
        admin = make_user(tid="tesla_vin_nul", type="admin")
        
        file = FileStorage(
            stream=BytesIO(csv_content),
            filename="tesla_vin_test.csv",
            content_type="text/csv"
        )
        
        scan_id = process_upload(
            actor=admin,
            file=file,
            car_no="88테8888",
            car={"maker": "TESLA", "model": "Model 3", "fuel": "전기"},
            device="테스트"
        )
        
        assert scan_id is not None
        
        scan = db.session.get(Scan, scan_id)
        assert scan is not None
        
        # VIN에 NUL 없음
        if scan.scan_vin:
            assert '\x00' not in scan.scan_vin
        
        db.session.rollback()


def test_seed_tesla_reference_idempotent(_app_base):
    """seed_tesla_reference_data is now a no-op (deprecated in v2.2.19).
    
    All Tesla data comes from xlsx import. This test verifies:
    1. The deprecated function doesn't insert any rows
    2. No manual rows exist after seed (cleaned by battery_ref_seed)
    """
    from app.modules.tesla.reference_data import seed_tesla_reference_data
    from app.extensions import db
    from sqlalchemy import text
    
    with _app_base.app_context():
        # Get initial count
        before_count = db.session.execute(
            text("SELECT COUNT(*) FROM battery_reference_capacity")
        ).scalar()
        
        # Call deprecated seed function (should be no-op)
        seed_tesla_reference_data()
        
        after_count = db.session.execute(
            text("SELECT COUNT(*) FROM battery_reference_capacity")
        ).scalar()
        
        # Verify no-op: count unchanged
        assert before_count == after_count, "seed_tesla_reference_data should not insert any rows (deprecated)"
        
        # Verify no manual rows exist
        manual_count = db.session.execute(
            text("SELECT COUNT(*) FROM battery_reference_capacity WHERE source_file = 'manual'")
        ).scalar()
        assert manual_count == 0, "No manual rows should exist after seed"
        
        db.session.rollback()


def test_report_bms_soc_key_exists():
    """report.py에서 'bms_soc' 키가 아닌 'soc' 키를 사용하는지 확인."""
    import re
    import os
    
    # 프로젝트 루트 찾기
    test_dir = os.path.dirname(__file__)
    repo_root = os.path.abspath(os.path.join(test_dir, '..', '..'))
    report_path = os.path.join(repo_root, 'app', 'modules', 'scanner', 'report.py')
    
    with open(report_path, 'r') as f:
        content = f.read()
    
    # BMS SOC를 읽는 부분에서 "bms_soc" 키를 쓰지 않아야 함
    # 실제로는 "soc" 키를 사용
    bms_section = re.search(r'"BMS SOC".*?_battery_value\(result, "(\w+)"\)', content, re.DOTALL)
    
    if bms_section:
        key_used = bms_section.group(1)
        assert key_used == "soc", f"BMS SOC should use 'soc' key, not '{key_used}'"


def test_version_is_2_2_5():
    """__version__ = 2.2.22 (updated from 2.2.5 → ... → 2.2.18 → 2.2.19 → 2.2.20 → 2.2.21 → 2.2.22)"""
    from app import __version__
    assert __version__.__version__ == "2.2.23"


def test_max_upload_size_600mb():
    """업로드 한도 600MB."""
    from app.modules.scanner import upload
    assert upload.MAX_UPLOAD_SIZE == 600 * 1024 * 1024
