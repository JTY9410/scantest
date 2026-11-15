"""Tesla E2E 테스트: 감지, 업로드, PDF 생성."""

import pytest
from pathlib import Path
from io import BytesIO


@pytest.fixture
def tesla_fake_csv():
    """Tesla 가짜 로그 (UDS ID 혼합, 3000+ 프레임)."""
    csv_path = Path(__file__).parent.parent / "fixtures" / "csv" / "tesla_fake_uds_mixed.csv"
    with open(csv_path, 'rb') as f:
        return f.read()


def test_tesla_fake_uds_mixed_upload(_app_base, make_user, tesla_fake_csv):
    """UDS-like ID가 섞인 Tesla 로그: 업로드 200, type=ev."""
    from app.modules.scanner.upload import process_upload
    from app.modules.scans.models import Scan
    from werkzeug.datastructures import FileStorage
    from app.extensions import db
    
    with _app_base.app_context():
        admin = make_user(tid="tesla_fake", type="admin")
        
        file = FileStorage(
            stream=BytesIO(tesla_fake_csv),
            filename="tesla_fake.csv",
            content_type="text/csv"
        )
        
        scan_id = process_upload(
            actor=admin,
            file=file,
            car_no="88테8888",
            car={"maker": "TESLA", "model": "Model 3", "fuel": "전기"},
            device="Tesla 테스트"
        )
        
        assert scan_id is not None, "Upload should return scan_id"
        
        scan = db.session.get(Scan, scan_id)
        assert scan is not None, "Scan should be created"
        
        # type=ev (Tesla 감지)
        assert scan.type == "ev", f"Expected type=ev, got {scan.type}"
        
        # VIN 확인 (정의가 없어 추출 실패 가능, 있으면 검증)
        if scan.scan_vin:
            assert len(scan.scan_vin) == 17, f"VIN should be 17 chars, got {len(scan.scan_vin)}"
            assert scan.scan_vin.startswith("5YJ"), f"VIN should start with 5YJ, got {scan.scan_vin}"
        
        # Tesla 감지 확인 (bms_data 또는 report)
        # canlab 분석 결과가 있으면 steps 확인
        steps = scan.bms_data.get("steps", [])
        if steps:
            # 0x352, 0x292, 0x401이 있어야 함
            ecus = {step.get("header") for step in steps if step.get("header")}
            assert "352" in ecus or "292" in ecus or "401" in ecus, f"Should have Tesla IDs, got {ecus}"
        
        db.session.rollback()


def test_tesla_detection_precedence_over_uds(_app_base, make_user, tesla_fake_csv):
    """Tesla ID가 있으면 UDS ID가 섞여있어도 Tesla로 감지."""
    from app.modules.scanner.upload import process_upload
    from app.modules.scans.models import Scan
    from werkzeug.datastructures import FileStorage
    from app.extensions import db
    
    with _app_base.app_context():
        admin = make_user(tid="tesla_precedence", type="admin")
        
        file = FileStorage(
            stream=BytesIO(tesla_fake_csv),
            filename="tesla_precedence.csv",
            content_type="text/csv"
        )
        
        # 제조사 정보 없이 업로드 (ID만으로 감지)
        scan_id = process_upload(
            actor=admin,
            file=file,
            car_no="99tesla",
            car={"maker": "알수없음", "model": "Unknown", "fuel": "알수없음"},
            device="Tesla ID 감지"
        )
        
        scan = db.session.get(Scan, scan_id)
        assert scan is not None
        
        # Tesla ID (0x352+0x292+0x401) 존재로 감지
        assert scan.type == "ev", f"Should detect as EV by Tesla IDs, got {scan.type}"
        
        db.session.rollback()
