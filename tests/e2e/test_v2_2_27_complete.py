"""v2.2.27 complete feature tests."""

import pytest
from datetime import datetime, timezone

from app.extensions import db
from app.modules.adaptive_collection.models import (
    CollectionProfile,
    SignalWhitelist,
    SignalWhitelistAudit,
    CollectionProfileAudit,
    ProfileStatus
)


class TestWhitelistManagement:
    """Test whitelist add/remove with CSRF and audit."""
    
    def test_whitelist_add_creates_audit(self, app, admin_client):
        """Adding to whitelist creates audit row."""
        with app.app_context():
            before_count = db.session.query(SignalWhitelistAudit).count()
        
        response = admin_client.post(
            '/admin/adaptive/whitelist/add',
            data={
                'signal_identifier': 'did:TEST',
                'reason': 'test reason',
                'description': 'test desc'
            }
        )
        
        assert response.status_code == 302  # Redirect
        
        with app.app_context():
            audit = db.session.query(SignalWhitelistAudit).filter_by(
                signal_identifier='did:TEST',
                action='add'
            ).first()
            
            assert audit is not None
            assert 'test reason' in audit.reason
    
    def test_whitelist_remove_creates_audit(self, app, admin_client):
        """Removing from whitelist creates audit row."""
        with app.app_context():
            whitelist = SignalWhitelist(
                signal_identifier='did:REMOVE',
                reason='to remove',
                is_active=True
            )
            db.session.add(whitelist)
            db.session.commit()
            whitelist_id = whitelist.id
        
        response = admin_client.post(
            f'/admin/adaptive/whitelist/{whitelist_id}/remove',
            data={'reason': 'removal reason'}
        )
        
        assert response.status_code == 302
        
        with app.app_context():
            audit = db.session.query(SignalWhitelistAudit).filter_by(
                signal_identifier='did:REMOVE',
                action='remove'
            ).first()
            
            assert audit is not None
            assert audit.reason == 'removal reason'
    
    def test_non_admin_whitelist_403(self, app, client, make_user):
        """Non-admin cannot access whitelist management."""
        with app.app_context():
            make_user('tester', type='tester')
        
        client.post('/admin/login', data={'tid': 'tester', 'pwd': 'test'})
        
        response = client.post(
            '/admin/adaptive/whitelist/add',
            data={'signal_identifier': 'did:X', 'reason': 'test'}
        )
        assert response.status_code in [302, 403]


class TestProfileGeneration:
    """Test synchronous profile generation."""
    
    def test_generate_creates_pending_profile(self, app, admin_client):
        """Generate button creates draft profile."""
        with app.app_context():
            # Create usage data
            from app.modules.adaptive_collection.models import SignalUsageStats
            
            stat = SignalUsageStats(
                manufacturer='TestMaker',
                model='TestModel',
                signal_identifier='did:UNUSED',
                requested_count=30,
                responded_count=0,
                decoded_count=0
            )
            db.session.add(stat)
            db.session.commit()
        
        response = admin_client.post(
            '/admin/adaptive/profiles/generate',
            data={
                'manufacturer': 'TestMaker',
                'model': 'TestModel',
                'threshold': '20'
            }
        )
        
        assert response.status_code == 302  # Redirect to profile detail
        
        with app.app_context():
            profile = db.session.query(CollectionProfile).filter_by(
                manufacturer='TestMaker',
                model='TestModel'
            ).first()
            
            assert profile is not None
            assert profile.status == ProfileStatus.DRAFT.value
            assert 'did:UNUSED' in profile.signals_to_skip
    
    def test_generate_creates_audit_log(self, app, admin_client):
        """Profile generation creates audit log."""
        with app.app_context():
            from app.modules.adaptive_collection.models import SignalUsageStats
            
            stat = SignalUsageStats(
                manufacturer='AuditTest',
                signal_identifier='did:X',
                requested_count=30,
                responded_count=0
            )
            db.session.add(stat)
            db.session.commit()
        
        admin_client.post(
            '/admin/adaptive/profiles/generate',
            data={'manufacturer': 'AuditTest', 'threshold': '20'}
        )
        
        with app.app_context():
            audit = db.session.query(CollectionProfileAudit).filter_by(
                action='create'
            ).order_by(CollectionProfileAudit.id.desc()).first()
            
            assert audit is not None
            assert 'admin UI' in audit.reason


class TestUsageStatsView:
    """Test usage stats viewing."""
    
    def test_usage_stats_accessible(self, app, admin_client):
        """Usage stats page accessible to admin."""
        response = admin_client.get('/admin/adaptive/usage-stats')
        assert response.status_code == 200
    
    def test_non_admin_stats_403(self, app, client, make_user):
        """Non-admin cannot view stats."""
        with app.app_context():
            make_user('tester', type='tester')
        
        client.post('/admin/login', data={'tid': 'tester', 'pwd': 'test'})
        
        response = client.get('/admin/adaptive/usage-stats')
        assert response.status_code in [302, 403]


class TestScanModelFields:
    """Test scan model has all required fields."""
    
    def test_scan_has_profile_tracking(self, app):
        """Scan model has profile tracking columns."""
        from app.modules.scans.models import Scan
        
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
                collection_profile_id=123,
                was_full_scan=False,
                force_full_scan=True,
                is_rescan_sample=True
            )
            
            assert scan.collection_profile_id == 123
            assert scan.was_full_scan is False
            assert scan.force_full_scan is True
            assert scan.is_rescan_sample is True
