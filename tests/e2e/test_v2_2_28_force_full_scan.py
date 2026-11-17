"""v2.2.28 force_full_scan feature tests."""

import pytest
import io
from datetime import datetime, timezone

from app.extensions import db
from app.modules.scans.models import Scan
from app.modules.adaptive_collection.models import (
    CollectionProfile,
    ProfileStatus
)


@pytest.fixture
def make_scan(app):
    """Create a minimal scan for testing."""
    def _make(**kwargs):
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test',
            tester_id=1,
            car_no=kwargs.get('car_no', '88가8888'),
            car_vin=kwargs.get('car_vin', 'ZZZ12345678901234'),
            car_maker='Tesla',
            car_model='Model3',
            **{k: v for k, v in kwargs.items() if k not in ['car_no', 'car_vin']}
        )
        db.session.add(scan)
        db.session.commit()
        return scan
    return _make


class TestForceFullScanBackend:
    """Test force_full_scan backend logic."""
    
    def test_scan_fields_exist(self, app, make_scan):
        """Scan model has force_full_scan fields."""
        with app.app_context():
            scan = make_scan(
                force_full_scan=True,
                was_full_scan=True,
                is_rescan_sample=False,
                collection_profile_id=123
            )
            
            assert scan.force_full_scan is True
            assert scan.was_full_scan is True
            assert scan.is_rescan_sample is False
            assert scan.collection_profile_id == 123


class TestCollectionMethodLogic:
    """Test collection method determination logic."""
    
    def test_force_full_scan_label(self, app):
        """Force full scan produces correct label."""
        from app.modules.scanner.report import inspection as build_inspection
        from app.modules.scanner.service import scan_result
        
        with app.app_context():
            scan = Scan(
                id=1,
                type='ev',
                device_type='test',
                device_uid='test',
                tester_id=1,
                car_no='88가8888',
                car_vin='ZZZ12345678901234',
                car_maker='Tesla',
                car_model='Model3',
                force_full_scan=True,
                was_full_scan=True
            )
            db.session.add(scan)
            db.session.commit()
            
            result = scan_result(scan)
            view = build_inspection(scan, result)
            
            assert view['collection_method'] == '전체 스캔 (강제)'
    
    def test_rescan_sample_label(self, app):
        """Rescan sample produces correct label."""
        from app.modules.scanner.report import inspection as build_inspection
        from app.modules.scanner.service import scan_result
        
        with app.app_context():
            scan = Scan(
                id=2,
                type='ev',
                device_type='test',
                device_uid='test',
                tester_id=1,
                car_no='88가8888',
                car_vin='ZZZ12345678901234',
                car_maker='Tesla',
                car_model='Model3',
                is_rescan_sample=True,
                was_full_scan=True
            )
            db.session.add(scan)
            db.session.commit()
            
            result = scan_result(scan)
            view = build_inspection(scan, result)
            
            assert view['collection_method'] == '전체 스캔 (샘플링 재수집)'
    
    def test_profile_label(self, app):
        """Profile usage produces correct label."""
        from app.modules.scanner.report import inspection as build_inspection
        from app.modules.scanner.service import scan_result
        
        with app.app_context():
            profile = CollectionProfile(
                version='v1.2.3',
                status=ProfileStatus.APPROVED.value,
                manufacturer='기아',
                signals_to_skip=[],
                generation_evidence={}
            )
            db.session.add(profile)
            db.session.commit()
            profile_id = profile.id
            
            scan = Scan(
                id=3,
                type='ev',
                device_type='test',
                device_uid='test',
                tester_id=1,
                car_no='88가8888',
                car_vin='ZZZ12345678901234',
                car_maker='기아',
                car_model='EV6',
                collection_profile_id=profile_id,
                was_full_scan=False
            )
            db.session.add(scan)
            db.session.commit()
            
            result = scan_result(scan)
            view = build_inspection(scan, result)
            
            assert f'프로파일 #{profile_id} vv1.2.3 적용' in view['collection_method']
