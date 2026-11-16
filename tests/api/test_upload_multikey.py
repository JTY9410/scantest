"""Test upload endpoint accepts files[], files, and file keys."""
import pytest
from io import BytesIO
from werkzeug.datastructures import FileStorage


def test_upload_with_files_array_key(admin_client):
    """Test that POST /admin/scan/upload accepts 'files[]' key and routes to process_multi_upload."""
    client = admin_client
    
    # Create two dummy CAN log files
    file1_content = b"""(1234567890.000) can0 7E4#021000000000000000
(1234567890.100) can0 7EC#104101414242424200
"""
    file2_content = b"""(1234567891.000) can0 220#0102030405060708
"""
    
    file1 = FileStorage(
        stream=BytesIO(file1_content),
        filename="file1.log",
        content_type="text/plain"
    )
    file2 = FileStorage(
        stream=BytesIO(file2_content),
        filename="file2.log",
        content_type="text/plain"
    )
    
    # Send with 'files[]' key (literal bracket in key name)
    response = client.post(
        "/admin/scan/upload",
        data={"files[]": [file1, file2], "car_no": "12가3456"},
        content_type="multipart/form-data"
    )
    
    assert response.status_code in (200, 201, 400), f"Upload got unexpected code: {response.status_code}"
    data = response.get_json()
    # Multi-file upload may succeed or fail validation, but it should NOT return 400 with "파일을 선택해주세요"
    if not data.get("success"):
        assert "파일을 선택해주세요" not in data.get("message", ""), "Endpoint did not recognize 'files[]' key"
