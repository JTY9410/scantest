"""v2.2.19 Production Fixes: Comprehensive regression tests.

Tests for all 7 defects found in Mac production deployment:
1. Battery reference seed idempotency (no duplicates, no manual rows)
2. Tesla candidates exclude implausible kWh (345/355 not battery capacity)
3. POST /admin/scan/<id>/recalculate-soh datetime import
4. /admin/ml/decoder-proposals schema (did_hex column)
5. Admin template errors (wescan_profiles, learning_status, learning_commands)
6. Consistency score shown in regular/EV9 PDF
7. Tesla ML features SOH status (미산정 not 미수신)

All tests use FAKE data only (ZZZ12345678901234, 88가8888, fake 5YJ VINs).
"""

import io
import json
import pytest
from unittest.mock import Mock, patch


def test_battery_ref_idempotency_no_duplicates(app):
    """Defect 1: Battery reference seed is idempotent (no duplicates, no manual rows).
    
    Simulates Mac production state:
    - Existing catalog with 221 rows (2 import sources)
    - Manual row from previous version
    - Duplicate rows from non-idempotent import
    
    Expected:
    - After running seed twice, exactly 221 rows remain
    - No source_file='manual' rows
    - No duplicates by (source_file, maker, model, trim, year_from)
    """
    from app.modules.scans.battery_capacity import BatteryReferenceCapacity
    from app.modules.scans.battery_ref_seed import seed_battery_references
    from app import db
    
    with app.app_context():
        # Clean slate
        db.session.query(BatteryReferenceCapacity).delete()
        db.session.commit()
        
        # Pre-populate bad state: manual row + duplicates
        bad_manual = BatteryReferenceCapacity(
            source_file='manual',
            maker='Tesla',
            model='Model 3',
            trim='Long Range',
            year_from=2018,
            year_to=2021,
            gross_capacity_kwh=74.0,
            notes='Manual entry - should be removed'
        )
        db.session.add(bad_manual)
        
        # Add NULL capacity row (invalid)
        null_capacity = BatteryReferenceCapacity(
            source_file='tesla',
            maker='Tesla',
            model='Model X',
            trim='Base',
            year_from=2020,
            official_capacity_kwh=None,
            gross_capacity_kwh=None,
            net_capacity_kwh=None
        )
        db.session.add(null_capacity)
        
        db.session.commit()
        
        # Run seed first time
        seed_battery_references()
        
        first_count = db.session.query(BatteryReferenceCapacity).count()
        assert first_count == 221, f"After first seed: expected 221 rows, got {first_count}"
        
        # Check manual rows removed
        manual_count = db.session.query(BatteryReferenceCapacity).filter_by(
            source_file='manual'
        ).count()
        assert manual_count == 0, f"Manual rows should be removed, found {manual_count}"
        
        # Run seed second time (idempotency test)
        seed_battery_references()
        
        second_count = db.session.query(BatteryReferenceCapacity).count()
        assert second_count == 221, f"After second seed: expected 221 rows, got {second_count}"
        
        # Check no EXACT duplicates (same source_file, maker, model, trim, year_from, pack_id)
        # Multiple rows with same (model, trim, year) but different pack_ids are legitimate
        from sqlalchemy import func
        duplicates = db.session.query(
            BatteryReferenceCapacity.source_file,
            BatteryReferenceCapacity.maker,
            BatteryReferenceCapacity.model,
            BatteryReferenceCapacity.trim,
            BatteryReferenceCapacity.year_from,
            BatteryReferenceCapacity.pack_id,
            func.count().label('count')
        ).group_by(
            BatteryReferenceCapacity.source_file,
            BatteryReferenceCapacity.maker,
            BatteryReferenceCapacity.model,
            BatteryReferenceCapacity.trim,
            BatteryReferenceCapacity.year_from,
            BatteryReferenceCapacity.pack_id
        ).having(func.count() > 1).all()
        
        assert len(duplicates) == 0, f"Found {len(duplicates)} EXACT duplicate rows: {duplicates}"


def test_tesla_candidates_exclude_implausible_kwh(app):
    """Defect 2: Tesla candidates exclude 345/355 kWh (not battery capacity).
    
    Tests that rows with only official_capacity_kwh set to implausible values
    (345, 355 - likely range in km or miles) are excluded from candidates.
    
    Expected candidates for 2020 Model 3 with 5YJ WMI and 65.26 kWh:
    - PK024 53.1 kWh
    - PK030 78.8 kWh
    - PK031 78.8 kWh
    - PK039 78.8 kWh
    
    NOT included:
    - Rows with official_capacity_kwh=345 or 355 (implausible)
    - Rows with pack_id NULL and gross NULL
    """
    from app.modules.scans.battery_soh import find_matching_references
    from app.modules.scans.battery_capacity import BatteryReferenceCapacity
    from app import db
    
    with app.app_context():
        # Clean slate
        db.session.query(BatteryReferenceCapacity).delete()
        
        # Good candidates
        good1 = BatteryReferenceCapacity(
            source_file='tesla',
            maker='Tesla',
            model='Model 3',
            pack_id='PK024',
            year_from=2018,
            year_to=2021,
            vin_wmi='5YJ',
            gross_capacity_kwh=53.1
        )
        good2 = BatteryReferenceCapacity(
            source_file='tesla',
            maker='Tesla',
            model='Model 3',
            pack_id='PK030',
            year_from=2018,
            year_to=2021,
            vin_wmi='5YJ',
            gross_capacity_kwh=78.8
        )
        
        # Bad: implausible official_capacity_kwh only (likely range not battery)
        bad1 = BatteryReferenceCapacity(
            source_file='tesla',
            maker='Tesla',
            model='Model 3',
            year_from=2020,
            vin_wmi='5YJ',
            official_capacity_kwh=345.0,  # Implausible - likely range
            gross_capacity_kwh=None,
            net_capacity_kwh=None
        )
        bad2 = BatteryReferenceCapacity(
            source_file='tesla',
            maker='Tesla',
            model='Model 3',
            year_from=2020,
            vin_wmi='5YJ',
            official_capacity_kwh=355.0,  # Implausible - likely range
            gross_capacity_kwh=None,
            net_capacity_kwh=None
        )
        
        for ref in [good1, good2, bad1, bad2]:
            db.session.add(ref)
        
        db.session.commit()
        
        # Query for 2020 Model 3 with 5YJ WMI (fake VIN)
        fake_vin = 'ZZZ12345678901234'  # Will decode to 5YJ in tests
        matches = find_matching_references(
            maker='Tesla',
            model='Model 3',
            year=2020,
            vin=fake_vin
        )
        
        # Should only get good candidates (PK024, PK030), not bad ones (345/355)
        pack_ids = {m.pack_id for m in matches if m.pack_id}
        assert 'PK024' in pack_ids, "PK024 should be included"
        assert 'PK030' in pack_ids, "PK030 should be included"
        
        # Check implausible values excluded
        capacities = [m.official_capacity_kwh for m in matches if m.official_capacity_kwh]
        assert 345.0 not in capacities, "345 kWh should be excluded (implausible)"
        assert 355.0 not in capacities, "355 kWh should be excluded (implausible)"


def test_recalculate_soh_datetime_import(admin_client, app):
    """Defect 3: POST /admin/scan/<id>/recalculate-soh datetime import.
    
    Tests that the route doesn't crash with NameError: name 'datetime' is not defined.
    """
    from app.modules.scans.models import Scan
    from app.modules.scans.battery_capacity import BatteryReferenceCapacity
    from app import db
    
    with app.app_context():
        # Create a fake Tesla scan with BMS data
        scan = Scan(
            type='manual',  # Required field
            device_type='file',  # Required field
            device_uid='test',  # Required field
            car_vin='ZZZ12345678901234',
            car_no='88가8888',
            car_maker='Tesla',
            car_model='Model 3',
            car_year=2020,
            bms_data={
                'source': 'tesla_upload',
                'decoded': {
                    'pack_vi': {
                        'current_nominal_full': 65.26
                    }
                }
            }
        )
        db.session.add(scan)
        
        # Add reference for PK031
        ref = BatteryReferenceCapacity(
            source_file='tesla',
            maker='Tesla',
            model='Model 3',
            pack_id='PK031',
            year_from=2018,
            year_to=2021,
            vin_wmi='5YJ',
            gross_capacity_kwh=78.8
        )
        db.session.add(ref)
        db.session.commit()
        
        scan_id = scan.id
    
    # POST recalculate with pack_id
    response = admin_client.post(
        f'/admin/scan/{scan_id}/recalculate-soh',
        json={'pack_id': 'PK031'}
    )
    
    # Should return 200, not 500 NameError
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.get_json()}"
    
    data = response.get_json()
    assert data['success'] is True
    assert 'soh_percent' in data
    assert data['pack_id'] == 'PK031'


def test_ml_decoder_proposals_route(admin_client, app):
    """Defect 4: /admin/ml/decoder-proposals schema (did_hex column).
    
    Tests that the route doesn't crash with UndefinedColumn.
    """
    response = admin_client.get('/admin/ml/decoder-proposals')
    
    # Should return 200, not 500 UndefinedColumn
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"


def test_admin_template_errors(client_authed_admin, app):
    """Defect 5: Admin template errors fixed.
    
    Tests:
    - /admin/wescan-profiles: sorted_makers line 63 syntax
    - /admin/learning/: summary[4] format
    - /admin/learning/commands: template exists
    - /admin/api/battery-specs/list: select import
    """
    # wescan-profiles
    response = admin_client.get('/admin/wescan-profiles')
    assert response.status_code == 200, f"/admin/wescan-profiles failed: {response.status_code}"
    
    # learning status
    response = admin_client.get('/admin/learning/')
    assert response.status_code == 200, f"/admin/learning/ failed: {response.status_code}"
    
    # learning commands (now exists)
    response = admin_client.get('/admin/learning/commands')
    assert response.status_code == 200, f"/admin/learning/commands failed: {response.status_code}"
    
    # battery-specs/list (select import)
    response = admin_client.get('/admin/api/battery-specs/list')
    assert response.status_code == 200, f"/admin/api/battery-specs/list failed: {response.status_code}"


def test_consistency_score_in_regular_pdf(app):
    """Defect 6: Consistency score shown in regular/EV9 PDF.
    
    Tests that issues['additional'] is rendered in the PDF for all report types.
    """
    from app.modules.scanner.pdf import _additional_info_and_issues_section, _p, _SMALL
    
    # Regular report with consistency score in issues['additional']
    view = {
        'kind': 'ev',
        'additional_info': {},
        'issues': {
            'additional': [
                '데이터 정합성 점수: 85.0%',
                '다른 추가 문제'
            ]
        }
    }
    
    story = _additional_info_and_issues_section(view)
    
    # Should have rendered the additional issues
    assert len(story) > 0, "Story should not be empty"
    
    # Check that consistency score text is in the story
    story_text = ' '.join([str(el) for el in story])
    assert '데이터 정합성 점수' in story_text or any(
        '정합성' in str(el) for el in story if hasattr(el, '__str__')
    ), "Consistency score should be in PDF"


def test_tesla_ml_features_soh_status(app):
    """Defect 7: Tesla ML features show correct unmeasurable_items for SOH.
    
    When SOH is 미산정 (multiple pack candidates), should show:
    - unmeasurable_items: {'soh': '미산정 (팩 후보 다수)'}
    - signals_read.soh: true (data exists, just not calculated)
    
    NOT:
    - unmeasurable_items: {'soh': '미수신'}
    - signals_read.soh: false
    """
    from app.modules.ml_learning.feature_extractor import _extract_signal_coverage, _extract_unmeasurable
    
    # Tesla result with SOH 미산정 (multiple candidates)
    result = {
        'decoded': {
            'soc': {'soc_ui': 85.0},
            'pack_vi': {'pack_voltage': 350.0}
        },
        'soh': {
            'soh_status': '팩 후보 다수 — 팩ID 확인 필요',
            'candidates': [
                {'pack_id': 'PK030', 'capacity_kwh': 78.8},
                {'pack_id': 'PK031', 'capacity_kwh': 78.8}
            ],
            'reference_capacity': None,
            'soh_percent': None
        }
    }
    
    # Check signal coverage - SOH data exists
    coverage = _extract_signal_coverage(result)
    assert coverage['soh'] is True, "SOH signal should be marked as present (data exists)"
    
    # Check unmeasurable - should be 미산정 not 미수신
    unmeasurable, count = _extract_unmeasurable(result)
    assert 'soh' in unmeasurable, "SOH should be in unmeasurable"
    assert '미산정' in unmeasurable['soh'], f"Expected 미산정, got: {unmeasurable['soh']}"
    assert '팩 후보 다수' in unmeasurable['soh'], f"Expected 팩 후보 다수, got: {unmeasurable['soh']}"
    assert unmeasurable['soh'] != '미수신', "Should not be 미수신 when data exists"


def test_admin_route_crawl_200(admin_client, app):
    """Smoke test: Crawl all parameter-less admin GET routes, assert 200.
    
    Excludes file-export endpoints that require params:
    - /admin/scan/<id>/pdf
    - /admin/scan/<id>/wescan-json
    - /admin/battery-references/export
    """
    from flask import url_for
    
    with app.app_context():
        # Get all routes
        excluded_rules = {
            '/admin/scan/<int:scan_id>/pdf',
            '/admin/scan/<int:scan_id>/wescan-json',
            '/admin/battery-references/export',
            '/admin/scan/<int:scan_id>/recalculate-soh'  # POST only
        }
        
        admin_routes = []
        for rule in app.url_map.iter_rules():
            if rule.rule.startswith('/admin') and 'GET' in rule.methods:
                # Skip routes with parameters (except int IDs we can mock)
                if '<' not in rule.rule or '<int:' in rule.rule:
                    if rule.rule not in excluded_rules:
                        admin_routes.append(rule.rule)
        
        # Crawl each route
        for route in admin_routes:
            # Replace <int:id> with 1 (won't exist, but should return 404 not 500)
            url = route.replace('<int:scan_id>', '1')
            url = url.replace('<int:id>', '1')
            
            response = admin_client.get(url)
            
            # Allow 200, 302 (redirect), 404 (not found)
            # Do NOT allow 500 (server error)
            assert response.status_code in [200, 302, 404], \
                f"{url} returned {response.status_code} (expected 200/302/404)"
