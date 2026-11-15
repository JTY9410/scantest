"""Simple upload tests without admin_client dependency."""

import pytest
from io import BytesIO

from app.modules.scanner.upload import validate_upload, UploadError, parse_uploaded_trace
from werkzeug.datastructures import FileStorage


def test_validate_empty_file():
    """빈 파일 거부."""
    file = FileStorage(stream=BytesIO(b""), filename="empty.csv")
    
    with pytest.raises(UploadError, match="빈 파일"):
        validate_upload(file)


def test_validate_invalid_extension():
    """지원하지 않는 확장자 거부."""
    file = FileStorage(stream=BytesIO(b"data"), filename="test.exe")
    
    with pytest.raises(UploadError, match="지원하지 않는 파일 형식"):
        validate_upload(file)


def test_validate_too_large(monkeypatch):
    """크기 제한 초과 거부."""
    from app.modules.scanner import upload
    monkeypatch.setattr(upload, "MAX_UPLOAD_SIZE", 100)
    
    data = b"x" * 200
    file = FileStorage(stream=BytesIO(data), filename="large.csv")
    
    with pytest.raises(UploadError, match="크기가 너무 큽니다"):
        validate_upload(file)


def test_validate_valid_csv():
    """유효한 CSV 파일 통과."""
    data = b"Time,ID,Data\n0.001,7E0,0222F190\n"
    file = FileStorage(stream=BytesIO(data), filename="test.csv")
    
    # Should not raise
    validate_upload(file)


def test_parse_invalid_format():
    """잘못된 형식 오류."""
    content = b"This is not a valid CAN log"
    
    with pytest.raises(UploadError):
        parse_uploaded_trace(content, "invalid.txt")
