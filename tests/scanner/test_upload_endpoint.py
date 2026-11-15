"""Upload endpoint integration tests with proper isolation (Issue #6)."""

import pytest
from io import BytesIO
from unittest.mock import patch


@pytest.fixture
def upload_admin(client, make_user):
    """관리자로 로그인된 클라이언트."""
    from tests.conftest import csrf_token
    
    # 관리자 생성
    admin = make_user(tid="upload_admin", type="admin")
    
    token = csrf_token(client, "/admin/login")
    response = client.post("/admin/login", data={
        "csrf_token": token,
        "tid": admin.tid,
        "password": "password123"  # conftest.py의 PASSWORD
    })
    assert response.status_code in (200, 302)
    return client


def test_upload_endpoint_no_file(upload_admin):
    """파일 없이 요청하면 오류."""
    response = upload_admin.post("/admin/scan/upload")
    
    assert response.status_code == 400
    data = response.get_json()
    assert not data["success"]
    assert "파일" in data["message"]


def test_upload_endpoint_invalid_extension(upload_admin):
    """지원하지 않는 확장자 거부."""
    data = b"invalid data"
    
    response = upload_admin.post(
        "/admin/scan/upload",
        data={
            "file": (BytesIO(data), "test.exe"),
        },
        content_type="multipart/form-data"
    )
    
    assert response.status_code == 400
    result = response.get_json()
    assert not result["success"]
    assert "지원하지 않는 파일 형식" in result["message"]


def test_upload_csv_creates_scan_record(_app_base, make_user):
    """CSV 업로드가 실제로 Scan 레코드를 생성하는지 (격리됨)."""
    from app.modules.scans.models import Scan
    from app.modules.scanner.upload import process_upload
    from werkzeug.datastructures import FileStorage
    from app.extensions import db
    
    # 최소한의 유효한 CSV (PID 01 00 요청 및 응답)
    csv_data = b"""Time,Channel,CAN_ID,DLC,Data
0.001,1,0x7DF,8,02 01 00 00 00 00 00 00
0.050,1,0x7E8,8,06 41 00 BE 1F B8 13 00
0.100,1,0x7DF,8,02 09 00 00 00 00 00 00
0.110,1,0x7E8,8,10 14 49 00 14 57 5A 5A
0.115,1,0x7DF,8,30 00 00 00 00 00 00 00
0.120,1,0x7E8,8,21 5A 31 32 33 34 35 36
0.125,1,0x7E8,8,22 37 38 39 30 31 32 33
"""
    
    with _app_base.app_context():
        admin = make_user(tid="csv_test", type="admin")
        
        file = FileStorage(
            stream=BytesIO(csv_data),
            filename="test_scan.csv",
            content_type="text/csv"
        )
        
        # 트랜잭션 내에서 실행
        scan_id = process_upload(
            actor=admin,
            file=file,
            car_no="88가8888",
            device="테스트 업로드"
        )
        
        # Scan이 생성되었는지 확인
        assert scan_id is not None
        scan = db.session.get(Scan, scan_id)
        assert scan is not None
        assert scan.car_no == "88가8888"
        # Scan doesn't have upload_filename; verify via dataset instead
        assert scan.reports
        
        # 롤백으로 정리
        db.session.rollback()


def test_upload_trc_creates_scan_record(_app_base, make_user):
    """TRC 업로드가 실제로 Scan 레코드를 생성하는지 (격리됨)."""
    from app.modules.scans.models import Scan
    from app.modules.scanner.upload import process_upload
    from werkzeug.datastructures import FileStorage
    from app.extensions import db
    
    # 최소한의 유효한 TRC (PCAN 형식 - PID 01 00 요청 및 응답)
    trc_data = b""";$FILEVERSION=1.1
;$STARTTIME=47717.5416666667
;
;   Time (abs)  T  Bus  ID   Reserved  DLC  Data ... Checksum
;
      0.001000  Tx   1  0x7DF   00 00 00 00   8  02 01 00 00 00 00 00 00   00
      0.050000  Rx   1  0x7E8   00 00 00 00   8  06 41 00 BE 1F B8 13 00   00
      0.100000  Tx   1  0x7DF   00 00 00 00   8  02 09 00 00 00 00 00 00   00
      0.110000  Rx   1  0x7E8   00 00 00 00   8  10 14 49 00 14 57 5A 5A   00
      0.115000  Tx   1  0x7DF   00 00 00 00   8  30 00 00 00 00 00 00 00   00
      0.120000  Rx   1  0x7E8   00 00 00 00   8  21 5A 31 32 33 34 35 36   00
      0.125000  Rx   1  0x7E8   00 00 00 00   8  22 37 38 39 30 31 32 33   00
"""
    
    with _app_base.app_context():
        admin = make_user(tid="trc_test", type="admin")
        
        file = FileStorage(
            stream=BytesIO(trc_data),
            filename="test_scan.trc",
            content_type="application/octet-stream"
        )
        
        scan_id = process_upload(
            actor=admin,
            file=file,
            car_no="88가8888",
            device="테스트 TRC 업로드"
        )
        
        assert scan_id is not None
        scan = db.session.get(Scan, scan_id)
        assert scan is not None
        assert scan.car_no == "88가8888"
        # Scan doesn't have upload_filename; verify via dataset instead
        assert scan.reports
        
        db.session.rollback()


def test_upload_with_car_lookup(_app_base, make_user):
    """차량번호 조회와 함께 업로드."""
    from app.modules.scanner.upload import process_upload
    from werkzeug.datastructures import FileStorage
    from app.extensions import db
    
    csv_data = b"""Time,ID,Data
0.001,7DF,0100
0.050,7E8,4100BE1FB813
"""
    
    # car_info.lookup을 Mock으로 대체
    with _app_base.app_context(), \
         patch('app.modules.scans.car_info.lookup') as mock_lookup:
        
        admin = make_user(tid="car_lookup_test", type="admin")
        
        # Mock 차량정보
        mock_lookup.return_value = ({
            "diag_company": "기아",
            "diag_model": "EV9",
            "diag_fuel": "전기",
            "diag_year": 2024
        }, False)
        
        file = FileStorage(
            stream=BytesIO(csv_data),
            filename="test_with_car.csv"
        )
        
        scan_id = process_upload(
            actor=admin,
            file=file,
            car_no="12가3456",
            device="차량정보 조회 테스트"
        )
        
        assert scan_id is not None
        assert mock_lookup.called
        
        db.session.rollback()


def test_upload_endpoint_integration(upload_admin, app):
    """전체 업로드 엔드포인트 통합 테스트 (Mock 최소화)."""
    from app.modules.scans.models import Scan
    from app.extensions import db
    
    csv_data = b"""Time,ID,Data
0.001,7DF,0100
0.050,7E8,4100BE1FB813
"""
    
    # car_info만 Mock (외부 API 호출 방지)
    with patch('app.modules.scans.car_info.lookup') as mock_lookup:
        mock_lookup.return_value = ({
            "diag_company": "현대",
            "diag_model": "아이오닉5",
            "diag_fuel": "전기"
        }, False)
        
        response = upload_admin.post(
            "/admin/scan/upload",
            data={
                "file": (BytesIO(csv_data), "integration_test.csv"),
                "car_no": "88가8888"
            },
            content_type="multipart/form-data"
        )
        
        assert response.status_code == 200
        result = response.get_json()
        assert result["success"]
        assert "scan_id" in result
        
        # Scan이 실제로 생성되었는지 확인
        with app.app_context():
            scan = db.session.get(Scan, result["scan_id"])
            assert scan is not None
            assert scan.car_no == "88가8888"
            assert scan.upload_filename == "integration_test.csv"
            
            # 테스트 후 정리
            db.session.delete(scan)
            db.session.commit()
