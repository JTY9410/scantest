"""Tests for raw file storage (v2.2.19+)."""

import pytest
from pathlib import Path


def test_store_and_retrieve_raw_file(app, make_user):
    """Store raw file and verify SHA256 match."""
    from app.modules.scans.raw_storage import store_raw_file, read_raw_file
    from app import db
    
    with app.app_context():
        # Create user for tester_id
        user_id = make_user(tid="test_raw_user1", type="tester")
        
        # Create fake scan
        from app.modules.scans.models import Scan
        scan = Scan(type='ev', device_type='file', device_uid='test', tester_id=user_id, car_no='88가8888', car_vin='ZZZ12345678901234')
        db.session.add(scan)
        db.session.flush()
        
        # Store file
        test_data = b'Fake CSV content\nZZZ12345678901234,88\xea\xb0\x808888'
        raw_file = store_raw_file(scan.id, test_data, 'test.csv', 'text/csv')
        db.session.commit()
        
        # Verify
        assert raw_file.sha256 is not None
        assert raw_file.original_filename == 'test.csv'
        assert raw_file.size_bytes == len(test_data)
        
        # Read back
        content = read_raw_file(raw_file)
        assert content == test_data


def test_raw_viewer_admin_only(admin_client, client, app, make_user):
    """Raw viewer requires admin role."""
    from app.modules.scans.models import Scan
    from app import db
    
    with app.app_context():
        user_id = make_user(tid="test_raw_user2", type="tester")
        scan = Scan(type='ev', device_type='file', device_uid='test', tester_id=user_id, car_no='88가8888')
        db.session.add(scan)
        db.session.commit()
        scan_id = scan.id
    
    # Admin can access
    response = admin_client.get(f'/admin/scan/{scan_id}/raw')
    assert response.status_code == 200
    
    # Non-admin redirected/denied
    response = client.get(f'/admin/scan/{scan_id}/raw', follow_redirects=False)
    assert response.status_code in [302, 403]


def test_raw_viewer_shows_unmasked_content(admin_client, app, make_user):
    """Preview shows UNMASKED plates and VINs."""
    from app.modules.scans.raw_storage import store_raw_file
    from app.modules.scans.models import Scan
    from app import db
    
    with app.app_context():
        user_id = make_user(tid="test_raw_user3", type="tester")
        scan = Scan(type='ev', device_type='file', device_uid='test', tester_id=user_id, car_no='12가3456', car_vin='5YJ3E1EB1KF123456')
        db.session.add(scan)
        db.session.flush()
        
        # Store file with plate and VIN
        content = 'VIN: 5YJ3E1EB1KF123456\nPlate: 12가3456\n'
        raw_file = store_raw_file(scan.id, content.encode(), 'data.txt', 'text/plain')
        db.session.commit()
        
        scan_id = scan.id
        file_id = raw_file.id
    
    # Preview should show unmasked
    response = admin_client.get(f'/admin/scan/{scan_id}/raw/{file_id}/preview')
    assert response.status_code == 200
    assert b'5YJ3E1EB1KF123456' in response.data
    assert '12가3456' in response.get_data(as_text=True)


def test_download_creates_audit_log(admin_client, app, make_user):
    """Download creates audit log entry."""
    from app.modules.scans.raw_storage import store_raw_file
    from app.modules.scans.models import Scan
    from app.modules.scans.raw_files import RawFileAccessLog
    from app import db
    
    with app.app_context():
        user_id = make_user(tid="test_raw_user4", type="tester")
        scan = Scan(type='ev', device_type='file', device_uid='test', tester_id=user_id, car_no='88가8888')
        db.session.add(scan)
        db.session.flush()
        
        raw_file = store_raw_file(scan.id, b'test', 'test.txt')
        db.session.commit()
        
        scan_id = scan.id
        file_id = raw_file.id
        
        # No logs yet
        assert db.session.query(RawFileAccessLog).count() == 0
    
    # Download
    response = admin_client.get(f'/admin/scan/{scan_id}/raw/{file_id}/download')
    assert response.status_code == 200
    
    with app.app_context():
        # Audit log created
        logs = db.session.query(RawFileAccessLog).filter_by(
            scan_id=scan_id, action='download'
        ).all()
        assert len(logs) == 1
        assert logs[0].user_email is not None


def test_old_scan_shows_no_raw_files(admin_client, app, make_user):
    """Scan without raw files shows '원본 없음 (v2.2.19 이전 업로드)'."""
    from app.modules.scans.models import Scan
    from app import db
    
    with app.app_context():
        user_id = make_user(tid="test_raw_user5", type="tester")
        scan = Scan(type='ev', device_type='file', device_uid='test', tester_id=user_id, car_no='88가8888')
        db.session.add(scan)
        db.session.commit()
        scan_id = scan.id
    
    response = admin_client.get(f'/admin/scan/{scan_id}/raw')
    assert response.status_code == 200
    assert '원본 없음' in response.get_data(as_text=True)
    assert 'v2.2.19 이전' in response.get_data(as_text=True)
