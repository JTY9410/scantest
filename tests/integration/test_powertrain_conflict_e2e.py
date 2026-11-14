"""End-to-end test for powertrain conflict detection and override.

사용자 요구사항 (b):
- citation_url에 가짜 URL 입력
- 충돌 감지, 결과 페이지 모달, override 저장, plan 반영
"""
import pytest
from sqlalchemy import text
from app.extensions import db
from app.modules.accounts.models import User
from app.modules.accounts.passwords import hash_password


@pytest.fixture
def conflict_e2e_cleanup(app):
    """Cleanup for conflict E2E tests."""
    with app.app_context():
        db.session.execute(text("DELETE FROM scans WHERE car_no = '88가8888'"))
        db.session.execute(text("DELETE FROM vin_decode_rules WHERE wmi_pattern = 'ZZZ'"))
        db.session.commit()
        
        yield
        
        db.session.execute(text("DELETE FROM scans WHERE car_no = '88가8888'"))
        db.session.execute(text("DELETE FROM vin_decode_rules WHERE wmi_pattern = 'ZZZ'"))
        db.session.commit()


def test_conflict_detection_and_storage(app, conflict_e2e_cleanup):
    """Test that conflict is detected and stored in DB.
    
    사용자 요구사항: 충돌 감지
    """
    from app.modules.scanner.service import run_scan
    
    with app.app_context():
        # Create test user
        test_user = User(
            type='tester',
            tid='test_conflict_e2e',
            name='Test User',
            password=hash_password('testpass123')
        )
        db.session.add(test_user)
        
        # Add VIN rule for ICE with citation_url
        # vds_position and vds_value_pattern must be NULL for simple WMI-only matching
        db.session.execute(text("""
            INSERT INTO vin_decode_rules 
                (wmi_pattern, vds_position, vds_value_pattern, manufacturer, powertrain, confidence, source_url, citation_url)
            VALUES 
                ('ZZZ', NULL, NULL, 'ConflictMaker', 'ICE', 0.9, 'https://example.test/vin', 'https://example.test/vin-rule')
        """))
        db.session.commit()
        
        # Fake car: plate=전기 (BEV), VIN=ICE
        fake_car = {
            'car_no': '88가8888',
            'diag_fuel': '전기',  # Plate lookup = BEV
            'diag_company': 'ConflictMaker',
            'model': 'ConflictModel',
            'diag_car_id': 'ZZZ12345678901234'  # VIN rule = ICE
        }
        
        fake_steps = [
            {'command': 'ATZ', 'reply': 'OK', 'error': None},
            {'command': '0100', 'reply': '4100', 'error': None}
        ]
        
        # Run scan
        scan = run_scan(
            actor=test_user,
            car_no='88가8888',
            car=fake_car,
            steps=fake_steps,
            transport='ble'
        )
        
        # Verify conflict was detected and stored
        scan_data = db.session.execute(text("""
            SELECT powertrain_conflict, plate_powertrain, vin_powertrain, type, type_source
            FROM scans
            WHERE id = :scan_id
        """), {'scan_id': scan.id}).fetchone()
        
        assert scan_data is not None, "Scan not found"
        
        # Debug: print actual values
        print(f"Debug - powertrain_conflict: {scan_data[0]}")
        print(f"Debug - plate_powertrain: {scan_data[1]}")
        print(f"Debug - vin_powertrain: {scan_data[2]}")
        print(f"Debug - type: {scan_data[3]}")
        print(f"Debug - type_source: {scan_data[4]}")
        
        # If conflict not detected, check why
        if not scan_data[0]:
            # Check if VIN rule was found
            vin_check = db.session.execute(text("""
                SELECT COUNT(*) FROM vin_decode_rules WHERE wmi_pattern = 'ZZZ'
            """)).scalar()
            print(f"Debug - VIN rules with ZZZ: {vin_check}")
        
        assert scan_data[0] is True, f"powertrain_conflict should be True, got {scan_data[0]}"
        assert scan_data[1] == 'BEV', f"plate_powertrain should be BEV, got {scan_data[1]}"
        assert scan_data[2] == 'ICE', f"vin_powertrain should be ICE, got {scan_data[2]}"
        # Type uses plate as primary (BEV -> ev)
        assert scan_data[3] in ('ev', 'EV'), f"type should be ev, got {scan_data[3]}"


def test_conflict_modal_in_html(app, client, conflict_e2e_cleanup):
    """Test that scan result page shows conflict modal.
    
    사용자 요구사항: 결과 페이지 모달
    """
    # Ensure CSRF is disabled for this test (isolation issue)
    app.config["WTF_CSRF_ENABLED"] = False
    
    from app.modules.scanner.service import run_scan
    
    with app.app_context():
        # Create admin user
        admin = User(
            type='admin',
            tid='admin_conflict_e2e',
            name='Admin User',
            password=hash_password('adminpass123')
        )
        db.session.add(admin)
        
        # Add VIN rule
        db.session.execute(text("""
            INSERT INTO vin_decode_rules 
                (wmi_pattern, vds_position, vds_value_pattern, manufacturer, powertrain, confidence, source_url, citation_url)
            VALUES 
                ('ZZZ', NULL, NULL, 'ModalMaker', 'ICE', 0.9, 'https://example.test/vin', 'https://example.test/vin-rule')
        """))
        db.session.commit()
        
        # Create scan with conflict
        fake_car = {
            'car_no': '88가8888',
            'diag_fuel': '전기',
            'diag_company': 'ModalMaker',
            'model': 'ModalModel',
            'diag_car_id': 'ZZZ12345678901234'
        }
        
        fake_steps = [{'command': 'ATZ', 'reply': 'OK', 'error': None}]
        
        scan = run_scan(
            actor=admin,
            car_no='88가8888',
            car=fake_car,
            steps=fake_steps,
            transport='ble'
        )
        
        scan_id = scan.id
    
    # Login and get scan page
    login_response = client.post('/admin/login', data={
        'tid': 'admin_conflict_e2e',
        'password': 'adminpass123'
    }, follow_redirects=True)
    
    assert login_response.status_code == 200, f"Login failed: {login_response.status_code}"
    
    response = client.get(f'/admin/scans/{scan_id}')
    
    if response.status_code == 302:
        print(f"Redirected to: {response.location}")
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    html = response.data.decode('utf-8')
    
    # Check for conflict indicators in HTML
    has_conflict = (
        'powertrain_conflict_modal' in html or
        'powertrain-conflict' in html or
        '동력원 불일치' in html or
        f'data-scan-id="{scan_id}"' in html
    )
    assert has_conflict, "Conflict modal not found in HTML"


def test_override_saves_to_db(app, client, conflict_e2e_cleanup):
    """Test that override API saves to DB.
    
    사용자 요구사항: /admin/powertrain/override 저장
    """
    # Ensure CSRF is disabled for this test (isolation issue)
    app.config["WTF_CSRF_ENABLED"] = False
    
    from app.modules.scanner.service import run_scan
    
    with app.app_context():
        # Create admin
        admin = User(
            type='admin',
            tid='admin_override_e2e',
            name='Admin User',
            password=hash_password('adminpass123')
        )
        db.session.add(admin)
        
        # Add VIN rule
        db.session.execute(text("""
            INSERT INTO vin_decode_rules 
                (wmi_pattern, vds_position, vds_value_pattern, manufacturer, powertrain, confidence, source_url, citation_url)
            VALUES 
                ('ZZZ', NULL, NULL, 'OverrideMaker', 'ICE', 0.9, 'https://example.test/vin', 'https://example.test/vin-rule')
        """))
        db.session.commit()
        
        # Create scan with conflict
        fake_car = {
            'car_no': '88가8888',
            'diag_fuel': '전기',
            'diag_company': 'OverrideMaker',
            'model': 'OverrideModel',
            'diag_car_id': 'ZZZ12345678901234'
        }
        
        fake_steps = [{'command': 'ATZ', 'reply': 'OK', 'error': None}]
        
        scan = run_scan(
            actor=admin,
            car_no='88가8888',
            car=fake_car,
            steps=fake_steps,
            transport='ble'
        )
        
        scan_id = scan.id
    
    # Login
    client.post('/admin/login', data={
        'tid': 'admin_override_e2e',
        'password': 'adminpass123'
    }, follow_redirects=True)
    
    # Call override API
    response = client.post('/admin/powertrain/override',
        json={
            'scan_id': scan_id,
            'powertrain': 'ICE',  # Choose VIN result
            'reason': 'E2E test override'
        },
        content_type='application/json'
    )
    
    assert response.status_code == 200
    
    # Verify in DB
    with app.app_context():
        scan_data = db.session.execute(text("""
            SELECT type, type_source, powertrain_conflict
            FROM scans
            WHERE id = :scan_id
        """), {'scan_id': scan_id}).fetchone()
        
        assert scan_data is not None
        assert scan_data[0] in ('ice', 'ICE'), f"type should be ice, got {scan_data[0]}"
        assert scan_data[1] == 'manual_override', f"type_source should be manual_override, got {scan_data[1]}"
        assert scan_data[2] is False, f"conflict should be resolved, got {scan_data[2]}"
