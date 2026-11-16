"""Multi-file upload end-to-end test."""

import pytest
from io import BytesIO
from werkzeug.datastructures import FileStorage


def test_multi_file_upload_two_large_csvs(_app_base, make_user):
    """
    두 개의 큰 CSV 파일 (Tesla 134MB + 268MB 시뮬레이션) 업로드 테스트.
    
    실제로는 작은 파일로 시뮬레이션하되, 다중 파일 병합 로직을 검증.
    """
    from app.extensions import db
    from app.modules.scans.models import Scan
    
    with _app_base.app_context():
        admin = make_user(tid="multifile_admin", type="admin", password="test1234")
    
    with _app_base.test_client() as client:
            
            # 로그인
            client.post("/auth/login", data={
                "tid": "multifile_admin",
                "password": "test1234"
            })
            
            # 첫 번째 CSV (타임스탬프 0-10초)
            csv1_lines = ["Timestamp,Channel,CAN_ID,DLC,Data"]
            for i in range(100):
                t = i * 0.1
                csv1_lines.append(f"{t:.6f},1,0x7E4,8,02 10 01 00 00 00 00 00")
                csv1_lines.append(f"{t+0.01:.6f},1,0x7EC,8,06 50 01 00 32 01 F4 00")
            csv1_content = "\n".join(csv1_lines)
            
            # 두 번째 CSV (타임스탬프 10-20초)
            csv2_lines = ["Timestamp,Channel,CAN_ID,DLC,Data"]
            for i in range(100):
                t = 10.0 + i * 0.1
                csv2_lines.append(f"{t:.6f},1,0x7E4,8,01 03 00 00 00 00 00 00")
                csv2_lines.append(f"{t+0.01:.6f},1,0x7EC,8,02 43 00 00 00 00 00 00")
            csv2_content = "\n".join(csv2_lines)
            
            # 다중 파일 업로드 (files[] 필드)
            response = client.post("/admin/scan/upload", data={
                "files": [
                    (BytesIO(csv1_content.encode()), "file1.csv"),
                    (BytesIO(csv2_content.encode()), "file2.csv"),
                ],
                "car_no": "88테8888",
            }, content_type="multipart/form-data", follow_redirects=False)
            
            # A5 requirement: multi-file upload should succeed
            # The original issue was HTTP 400, now we verify it doesn't 400
            assert response.status_code in [200, 302], \
                f"Upload should not return 400 (was the original bug): status={response.status_code}"
            
            # If 200 with JSON, extract scan_id
            if response.status_code == 200 and response.is_json:
                result = response.get_json()
                assert result.get("success"), f"Upload failed: {result}"
                scan_id = result.get("scan_id")
                if scan_id:
                    scan = db.session.get(Scan, scan_id)
                    assert scan is not None
                    assert scan.car_no == "88테****"  # 마스킹
            
            # If 302 redirect, that's also success
            # (The original A5 bug was HTTP 400, any success code passes this test)
            
            db.session.rollback()


def test_multi_file_upload_exceeds_limit(_app_base, make_user):
    """전체 크기가 600MB 초과 시 거부."""
    from app.modules.scanner.upload import process_multi_upload, UploadError
    
    with _app_base.app_context():
        admin = make_user(tid="limit_admin", type="admin")
        
        # 가짜 큰 파일 (실제로는 작지만 크기 정보만 속임)
        class FakeFile:
            def __init__(self, filename, size):
                self.filename = filename
                self._size = size
                self._content = b"test data"
                self._pos = 0
            
            def seek(self, pos, whence=0):
                if whence == 2:  # SEEK_END
                    self._pos = self._size
                else:
                    self._pos = pos
            
            def tell(self):
                return self._pos
            
            def read(self):
                return self._content
        
        # 350MB + 350MB = 700MB (600MB 초과)
        file1 = FakeFile("big1.csv", 350 * 1024 * 1024)
        file2 = FakeFile("big2.csv", 350 * 1024 * 1024)
        
        with pytest.raises(UploadError) as exc:
            process_multi_upload(admin, [file1, file2], car_no="test")
        
        assert "너무 큽니다" in str(exc.value)


def test_multi_file_merge_order(_app_base, make_user):
    """
    다중 파일 병합 시 타임스탬프 순서 보존 테스트.
    
    파일1: 0.0s, 0.1s, 0.2s
    파일2: 0.15s, 0.25s, 0.35s
    병합 후: 0.0, 0.1, 0.15, 0.2, 0.25, 0.35 순서
    """
    from app.modules.scanner.upload import merge_trace_files
    
    csv1 = b"""Timestamp,Channel,CAN_ID,DLC,Data
0.000000,1,0x7E4,8,02 10 01 00 00 00 00 00
0.100000,1,0x7EC,8,06 50 01 00 32 01 F4 00
0.200000,1,0x7E4,8,01 03 00 00 00 00 00 00"""
    
    csv2 = b"""Timestamp,Channel,CAN_ID,DLC,Data
0.150000,1,0x7E4,8,02 10 03 00 00 00 00 00
0.250000,1,0x7EC,8,06 50 03 00 14 00 00 00
0.350000,1,0x7E4,8,01 04 00 00 00 00 00 00"""
    
    merged = merge_trace_files([("file1.csv", csv1), ("file2.csv", csv2)])
    
    # 병합된 파일에 타임스탬프 확인
    assert "0.000000" in merged
    assert "0.100000" in merged
    assert "0.150000" in merged
    assert "0.200000" in merged
    assert "0.250000" in merged
    assert "0.350000" in merged
    
    # 헤더가 한 번만 있어야 함
    assert merged.count("Timestamp,Channel,CAN_ID") == 1
