"""Upload endpoint integration tests with proper isolation."""

import pytest
from io import BytesIO


@pytest.fixture(scope="function")
def isolated_app(_app_base):
    """Completely isolated app instance per test."""
    return _app_base


@pytest.fixture(scope="function")
def upload_client(isolated_app):
    """Test client with fresh admin user."""
    from app.modules.accounts.models import User
    from app.modules.accounts.passwords import hash_password
    from app.extensions import db
    from tests.conftest import csrf_token
    import uuid
    
    with isolated_app.app_context():
        # Unique user per test
        tid = f"upload_{uuid.uuid4().hex[:8]}"
        user = User(
            tid=tid,
            name="Upload Test",
            type="admin",
            password=hash_password("testpass123")
        )
        db.session.add(user)
        db.session.commit()
    
    client = isolated_app.test_client()
    token = csrf_token(client, "/admin/login")
    client.post("/admin/login", data={
        "csrf_token": token,
        "tid": tid,
        "password": "testpass123"
    })
    
    return client


def test_upload_endpoint_no_file(upload_client):
    """파일 없이 요청하면 오류."""
    response = upload_client.post("/admin/scan/upload")
    
    assert response.status_code == 400
    data = response.get_json()
    assert not data["success"]
    assert "파일" in data["message"]


def test_upload_endpoint_csv_mock(upload_client, monkeypatch):
    """CSV 파일 업로드 (Mock으로 격리)."""
    from app.modules.scanner import upload as upload_module
    
    # Mock to avoid full scan processing
    def mock_process_upload(actor, file, car_no=None, car=None, device=""):
        return 12345  # Mock scan_id
    
    monkeypatch.setattr(upload_module, "process_upload", mock_process_upload)
    
    data = b"Time,ID,Data\n0.001,7E0,0222F190\n"
    
    response = upload_client.post(
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
    assert result["scan_id"] == 12345
