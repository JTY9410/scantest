"""v2.2.26 feature tests."""

import pytest
from datetime import datetime, timezone

from app.extensions import db
from app.modules.adaptive_collection.models import CollectionProfile, ProfileStatus
from app.modules.scans.models import Scan


class TestAdminCrawl:
    """Test admin routes are accessible."""
    
    def test_adaptive_profiles_crawl(self, app, admin_client):
        """Adaptive collection routes accessible."""
        response = admin_client.get('/admin/adaptive/profiles')
        assert response.status_code == 200
        
        response = admin_client.get('/admin/adaptive/whitelist')
        assert response.status_code == 200


class TestForceFullScan:
    """Test force_full_scan option."""
    
    def test_scan_model_has_force_full_scan(self, app):
        """Scan model has force_full_scan column."""
        with app.app_context():
            scan = Scan(
                type='ev',
                device_type='test',
                device_uid='test',
                tester_id=1,
                car_no='88가8888',
                car_vin='ZZZ12345678901234',
                car_maker='Tesla',
                car_model='Model3',
                force_full_scan=True
            )
            
            assert scan.force_full_scan is True


class TestProfileDisplay:
    """Test profile display in results."""
    
    def test_scan_has_profile_fields(self, app):
        """Scan model has profile tracking fields."""
        with app.app_context():
            scan = Scan(
                type='ev',
                device_type='test',
                device_uid='test',
                tester_id=1,
                car_no='88가8888',
                car_vin='ZZZ12345678901234',
                car_maker='Tesla',
                car_model='Model3',
                collection_profile_id=1,
                was_full_scan=False,
                is_rescan_sample=False
            )
            
            assert scan.collection_profile_id == 1
            assert scan.was_full_scan is False
            assert scan.is_rescan_sample is False
