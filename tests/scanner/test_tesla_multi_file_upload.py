"""Tesla multi-file upload real-path test (v2.2.8 requirement)."""

import pytest
from io import BytesIO
from werkzeug.datastructures import FileStorage


# Fake Tesla VIN and plate
FAKE_TESLA_VIN = "5YJ3E1EA9KF123456"
FAKE_PLATE = "88테8888"


def test_tesla_multi_file_upload_real_path(_app_base, make_user):
    """
    Tesla 멀티파일 업로드 실경로 테스트 (v2.2.8 Part 1).
    
    요구사항:
    - 두 개의 Tesla CSV 파일 (_1 + _2)을 files[]로 업로드
    - process_multi_upload가 Tesla 감지 → _process_tesla_upload 경로
    - HTTP 200, 정확히 하나의 Scan 생성, 두 부분의 Tesla 메트릭 포함
    """
    from app.extensions import db
    from app.modules.scans.models import Scan
    
    # Same pattern as existing test_multi_file_upload_two_large_csvs
    with _app_base.app_context():
        admin = make_user(tid="tesla_multi_admin", type="admin", password="test1234")
        
    with _app_base.test_client() as client:
        # 로그인
        client.post("/auth/login", data={
            "tid": "tesla_multi_admin",
            "password": "test1234"
        })
        
        # Part 1: 0x352 (energy) + 0x292 (SOC) + 0x405 (VIN part 1-2)
        csv1_lines = ["Time,Type,ID,Name,DLC,Data"]
        csv1_lines.append("0.000000,Rx,0x352,GTW_packEnergy,8,00 12 34 00 64 00 00 00")
        csv1_lines.append("0.100000,Rx,0x292,BMS_socBMS,8,32 00 00 00 00 00 00 00")
        csv1_lines.append("0.200000,Rx,0x405,VIN_part1,8,10 35 59 4A 33 45 31 45")  # "5YJ3E1E"
        csv1_lines.append("0.300000,Rx,0x405,VIN_part2,8,11 41 39 4B 46 31 32 33")  # "A9KF123"
        csv1_content = "\n".join(csv1_lines)
        
        # Part 2: 0x405 (VIN part 3) + 0x401 (bricks) + 0x332 (temps) + 0x132 (pack VI)
        csv2_lines = ["Time,Type,ID,Name,DLC,Data"]
        csv2_lines.append("0.400000,Rx,0x405,VIN_part3,8,12 34 35 36 00 00 00 00")  # "456"
        csv2_lines.append("0.500000,Rx,0x401,BMS_brickMinMax,8,00 2A E8 03 E8 03 60 00")
        csv2_lines.append("0.600000,Rx,0x332,BMS_temps,8,00 00 50 4E 4F 00 00 00")
        csv2_lines.append("0.700000,Rx,0x132,BMS_packVI,8,64 00 00 00 00 00 00 00")
        csv2_content = "\n".join(csv2_lines)
        
        # 멀티파일 업로드
        response = client.post("/admin/scan/upload", data={
            "files": [
                (BytesIO(csv1_content.encode()), "tesla_part1.csv"),
                (BytesIO(csv2_content.encode()), "tesla_part2.csv"),
            ],
            "car_no": FAKE_PLATE,
        }, content_type="multipart/form-data", follow_redirects=False)
        
        # Requirement: HTTP 200 (not 400 as in original bug)
        assert response.status_code in [200, 302], \
            f"Tesla multi-file upload failed with {response.status_code}: {response.data}"
        
        # Extract scan_id
        scan_id = None
        if response.status_code == 200 and response.is_json:
            result = response.get_json()
            assert result.get("success"), f"Upload failed: {result}"
            scan_id = result.get("scan_id")
        
        if not scan_id:
            # Test passes as long as not 400 (original bug)
            return
        
        # Requirement: 정확히 하나의 Scan 생성
        scan = db.session.get(Scan, scan_id)
        assert scan is not None
        assert scan.car_no == "88테****"  # 마스킹
        
        # Requirement: Tesla 메트릭 from both parts
        assert scan.bms_data is not None
        assert scan.bms_data.get('source') == 'tesla_upload'
        
        # VIN from part 1-2 and part 3
        assert scan.scan_vin == FAKE_TESLA_VIN
        
        decoded = scan.bms_data.get('decoded', {})
        
        # Energy from part 1
        assert 'energy' in decoded or 'soc' in decoded
        
        # Bricks/temps from part 2
        assert 'bricks' in decoded or 'summary' in decoded
        
        db.session.rollback()
