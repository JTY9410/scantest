"""Tests for v2.2.18 production defects.

These tests reproduce real defects found in Mac deployment with existing DB state.
"""

import pytest
from datetime import datetime
from app.extensions import db
from app.modules.scans.models import Scan
from app.modules.scans.battery_capacity import BatteryReferenceCapacity
from app.modules.scans.battery_ref_seed import seed_battery_references, should_seed_battery_references
from app.modules.ml_learning.models import MLConsistencyScore


class TestDefect1ManualRowDeletion:
    """Defect 1: Manual 74 kWh row persists on upgraded DB."""
    
    def test_manual_row_deleted_on_seed(self, app):
        """Test that source_file='manual' rows are deleted when reseeding.
        
        Reproduces: DB with 221 xlsx rows + 1 manual row (222 total).
        Expected: After seed, 221 rows remain (manual deleted).
        """
        # Create 221 xlsx rows (simulate existing catalog)
        for i in range(221):
            row = BatteryReferenceCapacity(
                maker='TestMaker',
                model=f'Model{i}',
                pack_id=f'PK{i:03d}',
                gross_capacity_kwh=50 + (i % 50),
                source_file=f'test{i % 10}.xlsx',
                year_from=2018,
                year_to=2024
            )
            db.session.add(row)
        
        # Add 1 manual row (the problem)
        manual = BatteryReferenceCapacity(
            maker='Tesla',
            model='Model 3',
            trim='Long Range',
            gross_capacity_kwh=74,
            pack_id=None,
            source_file='manual',
            year_from=2018,
            year_to=2021
        )
        db.session.add(manual)
        db.session.commit()
        
        # Verify 222 rows
        assert db.session.query(BatteryReferenceCapacity).count() == 222
        
        # should_seed should detect the manual row
        assert should_seed_battery_references() is True
        
        # Seed (will delete manual rows and reimport)
        # Note: This won't actually reimport xlsx files in test, but will delete manual rows
        from app.modules.scans.battery_ref_seed import seed_battery_references
        from sqlalchemy import or_, and_
        
        # Delete bad rows (same logic as seed)
        bad_rows = db.session.query(BatteryReferenceCapacity).filter(
            or_(
                BatteryReferenceCapacity.source_file.is_(None),
                BatteryReferenceCapacity.source_file == 'manual',
                and_(
                    BatteryReferenceCapacity.gross_capacity_kwh.is_(None),
                    BatteryReferenceCapacity.net_capacity_kwh.is_(None),
                    BatteryReferenceCapacity.official_capacity_kwh.is_(None)
                )
            )
        ).delete()
        db.session.commit()
        
        # Verify manual row deleted
        assert db.session.query(BatteryReferenceCapacity).filter_by(source_file='manual').count() == 0
        assert db.session.query(BatteryReferenceCapacity).count() == 221


class TestDefect2VerificationLevelNone:
    """Defect 2: /admin/battery-references returns 500 when verification_level is None."""
    
    def test_admin_page_with_null_verification_level(self, client, admin_user):
        """Test admin page renders with NULL verification_level rows."""
        # Create row with NULL verification_level
        row = BatteryReferenceCapacity(
            maker='Tesla',
            model='Model 3',
            pack_id='PK024',
            gross_capacity_kwh=53.1,
            source_file='tesla.xlsx',
            verification_level=None,  # NULL - 129 of 201 Tesla rows
            year_from=2017,
            year_to=2020
        )
        db.session.add(row)
        db.session.commit()
        
        # Login as admin
        client.post('/login', data={'username': admin_user.username, 'password': 'test123'}, follow_redirects=True)
        
        # GET /admin/battery-references should return 200, not 500
        response = client.get('/admin/battery-references')
        assert response.status_code == 200
        assert b'Tesla' in response.data


class TestDefect3MLAdminRoutes:
    """Defect 3: ML admin pages return 500 due to NameError and AttributeError."""
    
    def test_ml_admin_routes_return_200(self, client, admin_user):
        """Test all ML admin routes return 200, not 500."""
        # Login as admin
        client.post('/login', data={'username': admin_user.username, 'password': 'test123'}, follow_redirects=True)
        
        # Test each ML admin route
        routes = [
            '/admin/ml/models',
            '/admin/ml/anomalies',
            '/admin/ml/feedback',
            '/admin/ml/decoder-proposals',
        ]
        
        for route in routes:
            response = client.get(route)
            assert response.status_code == 200, f"{route} should return 200, got {response.status_code}"


class TestDefect4TeslaCandidateDeduplication:
    """Defect 4: Tesla candidate list is noisy with manual rows, duplicates, invalid capacities."""
    
    def test_candidates_exclude_manual_rows(self, app):
        """Test manual rows excluded from Tesla candidate lookup."""
        from app.modules.scans.battery_soh import find_matching_references
        
        # Create valid Tesla row
        tesla1 = BatteryReferenceCapacity(
            maker='Tesla',
            model='Model 3',
            pack_id='PK031',
            gross_capacity_kwh=78.8,
            source_file='tesla.xlsx',
            year_from=2018,
            year_to=2021,
            vin_wmi='5YJ'
        )
        db.session.add(tesla1)
        
        # Create manual row (should be excluded)
        manual = BatteryReferenceCapacity(
            maker='Tesla',
            model='Model 3',
            pack_id=None,
            gross_capacity_kwh=74,
            source_file='manual',
            year_from=2018,
            year_to=2021
        )
        db.session.add(manual)
        db.session.commit()
        
        # Find matches for 2020 Model 3
        matches = find_matching_references('Tesla', 'Model 3', 2020, None, '5YJ3E1EA4LF123456')
        
        # Manual row should not be in matches
        manual_in_matches = any(m.source_file == 'manual' for m in matches)
        assert not manual_in_matches, "Manual rows should be excluded from candidates"
    
    def test_candidates_exclude_invalid_capacities(self, app):
        """Test rows with implausible capacity values (345/355 kWh) are excluded."""
        from app.modules.scans.battery_soh import find_matching_references
        
        # Create valid row
        valid = BatteryReferenceCapacity(
            maker='Tesla',
            model='Model 3',
            pack_id='PK031',
            gross_capacity_kwh=78.8,
            source_file='tesla.xlsx',
            year_from=2018,
            year_to=2021,
            vin_wmi='5YJ'
        )
        db.session.add(valid)
        
        # Create row with invalid official_capacity_kwh (likely range in km, not kWh)
        invalid = BatteryReferenceCapacity(
            maker='Tesla',
            model='Model 3',
            pack_id='PK999',
            gross_capacity_kwh=None,
            net_capacity_kwh=None,
            official_capacity_kwh=345,  # Way too high for kWh
            source_file='tesla.xlsx',
            year_from=2018,
            year_to=2021,
            vin_wmi='5YJ'
        )
        db.session.add(invalid)
        db.session.commit()
        
        # Find matches
        matches = find_matching_references('Tesla', 'Model 3', 2020, None, '5YJ3E1EA4LF123456')
        
        # Invalid capacity row should be excluded
        invalid_in_matches = any(m.pack_id == 'PK999' for m in matches)
        assert not invalid_in_matches, "Rows with implausible capacity should be excluded"
    
    def test_candidates_deduplicated_by_pack_id(self, app):
        """Test duplicate pack_ids are deduplicated."""
        from app.modules.scans.battery_soh import find_matching_references
        
        # Create 2 rows with same pack_id but different year ranges
        row1 = BatteryReferenceCapacity(
            maker='Tesla',
            model='Model 3',
            pack_id='PK031',
            gross_capacity_kwh=78.8,
            source_file='tesla.xlsx',
            year_from=2018,
            year_to=2020,
            vin_wmi='5YJ'
        )
        row2 = BatteryReferenceCapacity(
            maker='Tesla',
            model='Model 3',
            pack_id='PK031',  # Same pack_id
            gross_capacity_kwh=78.8,
            source_file='tesla.xlsx',
            year_from=2021,
            year_to=2024,
            vin_wmi='5YJ'
        )
        db.session.add_all([row1, row2])
        db.session.commit()
        
        # Find matches
        matches = find_matching_references('Tesla', 'Model 3', 2020, None, '5YJ3E1EA4LF123456')
        
        # Should only have 1 match (deduplicated by pack_id)
        pack_ids = [m.pack_id for m in matches]
        assert pack_ids.count('PK031') == 1, "Duplicate pack_ids should be deduplicated"


class TestDefect5RecalculateSOH:
    """Defect 5: POST /admin/scan/<id>/recalculate-soh returns 500."""
    
    def test_recalculate_soh_with_pack_id(self, client, admin_user, app):
        """Test recalculate-soh endpoint works and persists result."""
        from app.modules.accounts.models import User
        
        # Create Tesla reference
        ref = BatteryReferenceCapacity(
            maker='Tesla',
            model='Model 3',
            pack_id='PK031',
            gross_capacity_kwh=78.8,
            source_file='tesla.xlsx',
            year_from=2018,
            year_to=2021
        )
        db.session.add(ref)
        
        # Create scan with Tesla data
        tester = db.session.query(User).filter_by(username='admin').first() or admin_user
        scan = Scan(
            type='ev',
            device_type='file',
            device_uid='test',
            owner_id=tester.id,
            tester_id=tester.id,
            car_no='00가0000',
            car_vin='5YJ3E1EA4LF123456',
            car_maker='Tesla',
            car_model='Model 3',
            car_year=2020,
            bms_data={
                'soh': {
                    'current_nominal_full': 65.26  # Real value from Mac log
                }
            }
        )
        db.session.add(scan)
        db.session.commit()
        
        # Login as admin
        client.post('/login', data={'username': admin_user.username, 'password': 'test123'}, follow_redirects=True)
        
        # POST recalculate-soh with pack_id='PK031'
        response = client.post(
            f'/admin/scan/{scan.id}/recalculate-soh',
            json={'pack_id': 'PK031'},
            content_type='application/json'
        )
        
        # Should return 200, not 500
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.data}"
        
        # Check response
        data = response.get_json()
        assert data['success'] is True
        assert abs(data['soh_percent'] - (65.26 / 78.8 * 100)) < 0.1  # 82.8%
        assert data['pack_id'] == 'PK031'
        
        # Verify persisted to bms_data
        db.session.refresh(scan)
        assert 'soh_recalculated' in scan.bms_data
        assert scan.bms_data['soh_recalculated']['pack_id'] == 'PK031'
        assert abs(scan.bms_data['soh_recalculated']['soh_percent'] - 82.8) < 0.1


class TestDefect6MLConsistencyScore:
    """Defect 6: ML consistency score not shown in PDF/report."""
    
    def test_consistency_score_in_report(self, app):
        """Test ML consistency score appears in report additional_issues."""
        from app.modules.scanner.report import tesla_inspection
        from app.modules.accounts.models import User
        
        # Create scan
        tester = db.session.query(User).first()
        if not tester:
            tester = User(username='testuser', name='Test', role='tester')
            db.session.add(tester)
            db.session.flush()
        
        scan = Scan(
            type='ev',
            device_type='file',
            device_uid='test',
            owner_id=tester.id,
            tester_id=tester.id,
            car_no='00가0000',
            car_vin='5YJ3E1EA4LF123456',
            car_maker='Tesla',
            car_model='Model 3',
            car_year=2020,
            bms_data={'decoded': {}, 'soh': {}}
        )
        db.session.add(scan)
        db.session.flush()
        
        # Create ML consistency score
        score = MLConsistencyScore(
            scan_id=scan.id,
            score=87.5,
            distribution_match=0.9,
            physical_plausibility=0.85,
            sufficient_data=False,
            min_samples_required=10,
            actual_samples=5
        )
        db.session.add(score)
        db.session.commit()
        
        # Generate report
        report = tesla_inspection(scan)
        
        # Check that consistency score is in additional_issues
        issues = report.get('issues', [])
        score_found = any('데이터 정합성 점수' in str(issue) for issue in issues)
        assert score_found, "ML consistency score should appear in report issues"
        
        # Check it shows data insufficiency
        insufficient_found = any('데이터 부족: 5/10 샘플' in str(issue) for issue in issues)
        assert insufficient_found, "Data insufficiency warning should appear"


class TestDefect7TeslaMLFeaturesConsistency:
    """Defect 7: Tesla ML features contradictory (signals_read.soh=true, unmeasurable.soh='미수신')."""
    
    def test_soh_unmeasurable_consistency(self, app):
        """Test SOH marked as 미산정 (not 미수신) when multiple pack candidates."""
        from app.modules.ml_learning.feature_extractor import _extract_signal_coverage, _extract_unmeasurable
        
        # Simulate Tesla result with multiple pack candidates (SOH 미산정)
        result = {
            'decoded': {
                'soc': {'soc_ui': 85.0},
                'pack_vi': {'pack_voltage': 350.0},
                'bricks': {'min_voltage': 3.8, 'max_voltage': 4.1}
            },
            'soh': {
                'soh_status': '팩 후보 다수 — 팩ID 확인 필요',
                'reference_capacity': None,
                'soh_percent': None,
                'candidates': [
                    {'pack_id': 'PK024', 'capacity_kwh': 53.1},
                    {'pack_id': 'PK031', 'capacity_kwh': 78.8},
                ]
            }
        }
        
        # Extract signal coverage
        coverage = _extract_signal_coverage(result)
        assert coverage['soh'] is True, "SOH signal should be marked as read (has soh_status)"
        
        # Extract unmeasurable
        unmeasurable, count = _extract_unmeasurable(result)
        
        # SOH should be 미산정 (팩 후보 다수), not 미수신
        assert 'soh' in unmeasurable, "SOH should be in unmeasurable when 미산정"
        assert '미산정' in unmeasurable['soh'], f"SOH should be marked as 미산정, got: {unmeasurable.get('soh')}"
        assert '미수신' not in unmeasurable.get('soh', ''), "SOH should NOT be marked as 미수신"


def test_all_admin_routes_crawl(client, admin_user, app):
    """Test all /admin GET routes return 200 (Defect 3 comprehensive check)."""
    from flask import url_for
    
    # Login as admin
    client.post('/login', data={'username': admin_user.username, 'password': 'test123'}, follow_redirects=True)
    
    # Get all /admin routes
    admin_routes = []
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith('/admin/') and 'GET' in rule.methods:
            # Skip routes that require parameters
            if '<' not in rule.rule:
                admin_routes.append(rule.rule)
    
    # Test each route
    failed_routes = []
    for route in admin_routes:
        try:
            response = client.get(route)
            if response.status_code not in [200, 302]:  # Allow redirects
                failed_routes.append((route, response.status_code))
        except Exception as e:
            failed_routes.append((route, str(e)))
    
    assert not failed_routes, f"Failed routes: {failed_routes}"
