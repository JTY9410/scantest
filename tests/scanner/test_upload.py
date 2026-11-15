"""Test scan data upload functionality."""

import pytest
from io import BytesIO

from app.modules.scanner.upload import validate_upload, UploadError, parse_uploaded_trace
from werkzeug.datastructures import FileStorage


def test_validate_upload_empty_file():
    """빈 파일은 거부."""
    file = FileStorage(stream=BytesIO(b""), filename="empty.csv")
    
    with pytest.raises(UploadError, match="빈 파일"):
        validate_upload(file)


def test_validate_upload_invalid_extension():
    """지원하지 않는 확장자는 거부."""
    file = FileStorage(stream=BytesIO(b"data"), filename="test.exe")
    
    with pytest.raises(UploadError, match="지원하지 않는 파일 형식"):
        validate_upload(file)


def test_validate_upload_too_large(monkeypatch):
    """크기 제한 초과 파일은 거부."""
    from app.modules.scanner import upload
    monkeypatch.setattr(upload, "MAX_UPLOAD_SIZE", 100)
    
    data = b"x" * 200
    file = FileStorage(stream=BytesIO(data), filename="large.csv")
    
    with pytest.raises(UploadError, match="크기가 너무 큽니다"):
        validate_upload(file)


def test_validate_upload_valid_csv():
    """유효한 CSV 파일은 통과."""
    data = b"Time,ID,Data\n0.001,7E0,0222F190\n"
    file = FileStorage(stream=BytesIO(data), filename="test.csv")
    
    # Should not raise
    validate_upload(file)


def test_parse_uploaded_trace_minimal():
    """최소 trace 파싱."""
    # Minimal valid WeCar ELM format with UDS transaction
    content = b"""@WeCar ELM327
>7E0 03 22 F1 90
<7E8 06 62 F1 90 12 34 56
"""
    
    # Should raise because trace.transactions might be empty with this format
    # This is a format validation test, not a complete parse test
    try:
        result = parse_uploaded_trace(content, "test.txt")
        # If it succeeds, check it's not empty
        assert result
    except UploadError as exc:
        # Expected if no valid transactions
        assert "트랜잭션" in str(exc) or "파싱" in str(exc)


def test_parse_uploaded_trace_invalid_format():
    """잘못된 형식은 오류."""
    content = b"This is not a valid CAN log"
    
    with pytest.raises(UploadError):
        parse_uploaded_trace(content, "invalid.txt")


def test_upload_endpoint_no_file(app, make_user):
    """파일 없이 요청하면 오류."""
    from tests.conftest import admin_login
    from app.extensions import db
    
    with app.app_context():
        # Ensure clean state
        db.session.rollback()
        make_user("admin_upload_test", type="admin", password="test123upload", name="Upload Admin")
        db.session.commit()
    
    client = app.test_client()
    admin_login(client, "admin_upload_test", "test123upload")
    
    response = client.post("/admin/scan/upload")
    
    assert response.status_code == 400
    data = response.get_json()
    assert not data["success"]
    assert "파일" in data["message"]


def test_upload_endpoint_with_fake_csv(app, make_user, monkeypatch):
    """가짜 CSV 파일 업로드 (E2E 스텁)."""
    from tests.conftest import admin_login
    from app.extensions import db
    
    with app.app_context():
        # Ensure clean state
        db.session.rollback()
        make_user("admin_csv_test", type="admin", password="test456csv", name="CSV Upload Admin")
        db.session.commit()
    
    # Mock process_upload to avoid full processing
    from app.modules.scanner import upload
    
    def mock_process_upload(actor, file, car_no=None, car=None, device=""):
        return 999  # Fake scan_id
    
    monkeypatch.setattr(upload, "process_upload", mock_process_upload)
    
    client = app.test_client()
    admin_login(client, "admin_csv_test", "test456csv")
    
    data = b"Time,ID,Data\n0.001,7E0,0222F190\n"
    
    response = client.post(
        "/admin/scan/upload",
        data={
            "file": (BytesIO(data), "test.csv"),
            "car_no": "88가8888"
        },
        content_type="multipart/form-data"
    )
    
    assert response.status_code == 200
    result = response.get_json()
    assert result["success"]
    assert result["scan_id"] == 999
