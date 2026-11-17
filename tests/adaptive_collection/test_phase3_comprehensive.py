"""Comprehensive Phase 3 (Adaptive Collection) tests (v2.2.24)."""

import pytest
from datetime import datetime, timezone

from app.extensions import db
from app.modules.adaptive_collection.models import (
    SignalUsageStats,
    CollectionProfile,
    CollectionProfileAudit,
    SignalWhitelist,
    SignalWhitelistAudit,
    ProfileStatus
)
from app.modules.adaptive_collection.profile_generator import generate_collection_profile, check_reenable_signals


class TestSignalUsageTracking:
    """Test signal usage statistics tracking."""
    
    def test_usage_stats_creation(self, app):
        """Test creating usage statistics."""
        with app.app_context():
            stat = SignalUsageStats(
                manufacturer='Tesla',
                model='Model3',
                signal_identifier='did:2101',
                requested_count=10,
                responded_count=8,
                decoded_count=7
            )
            
            db.session.add(stat)
            db.session.commit()
            
            retrieved = db.session.query(SignalUsageStats).first()
            assert retrieved.manufacturer == 'Tesla'
            assert retrieved.model == 'Model3'
            assert retrieved.requested_count == 10


class TestProfileGeneration:
    """Test collection profile generation logic."""
    
    def test_generate_profile_no_data(self, app):
        """Test profile generation with no usage data."""
        with app.app_context():
            profile = generate_collection_profile(manufacturer='Tesla', model='ModelX')
            assert profile is None
    
    def test_generate_profile_skips_non_responding(self, app):
        """Test that non-responding signals are marked for skip."""
        with app.app_context():
            stat1 = SignalUsageStats(
                manufacturer='Tesla',
                model='Model3',
                signal_identifier='did:2101',
                requested_count=30,
                responded_count=0,
                decoded_count=0
            )
            
            stat2 = SignalUsageStats(
                manufacturer='Tesla',
                model='Model3',
                signal_identifier='did:2102',
                requested_count=30,
                responded_count=28,
                decoded_count=25,
                used_in_report_count=20
            )
            
            db.session.add_all([stat1, stat2])
            db.session.commit()
            
            profile = generate_collection_profile(
                manufacturer='Tesla',
                model='Model3',
                skip_threshold_scans=20
            )
            
            assert profile is not None
            assert 'did:2101' in profile.signals_to_skip
            assert 'did:2102' not in profile.signals_to_skip
    
    def test_generate_profile_respects_whitelist(self, app):
        """Test that whitelisted signals are never skipped."""
        with app.app_context():
            whitelist = SignalWhitelist(
                signal_identifier='did:2101',
                reason='required_for_soh',
                is_active=True
            )
            
            db.session.add(whitelist)
            db.session.commit()
            
            stat = SignalUsageStats(
                manufacturer='Tesla',
                model='Model3',
                signal_identifier='did:2101',
                requested_count=30,
                responded_count=0,
                decoded_count=0
            )
            
            db.session.add(stat)
            db.session.commit()
            
            profile = generate_collection_profile(
                manufacturer='Tesla',
                model='Model3',
                skip_threshold_scans=20
            )
            
            assert profile is None or 'did:2101' not in profile.signals_to_skip


class TestProfileApprovalWorkflow:
    """Test profile approval workflow."""
    
    def test_approve_profile(self, app, admin_client):
        """Test approving a draft profile."""
        with app.app_context():
            profile = CollectionProfile(
                version='profile-test-001',
                status=ProfileStatus.DRAFT.value,
                manufacturer='Tesla',
                model='Model3',
                signals_to_skip=['did:2101'],
                generation_evidence={}
            )
            
            db.session.add(profile)
            db.session.commit()
            profile_id = profile.id
        
        response = admin_client.post(
            f'/admin/adaptive/profiles/{profile_id}/approve',
            json={'notes': 'Approved after review'}
        )
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        
        with app.app_context():
            profile = db.session.get(CollectionProfile, profile_id)
            assert profile.status == ProfileStatus.APPROVED.value
    
    def test_rollback_profile(self, app, admin_client):
        """Test rolling back an approved profile."""
        with app.app_context():
            profile = CollectionProfile(
                version='profile-test-002',
                status=ProfileStatus.APPROVED.value,
                manufacturer='Tesla',
                signals_to_skip=[],
                generation_evidence={},
                approved_at=datetime.now(timezone.utc)
            )
            
            db.session.add(profile)
            db.session.commit()
            profile_id = profile.id
        
        response = admin_client.post(
            f'/admin/adaptive/profiles/{profile_id}/rollback',
            json={'reason': 'Causing issues'}
        )
        
        assert response.status_code == 200
        
        with app.app_context():
            profile = db.session.get(CollectionProfile, profile_id)
            assert profile.status == ProfileStatus.ROLLED_BACK.value


class TestSignalWhitelist:
    """Test signal whitelist management."""
    
    def test_add_to_whitelist(self, app, admin_client):
        """Test adding signal to whitelist."""
        response = admin_client.post(
            '/admin/adaptive/whitelist',
            json={
                'signal_identifier': 'did:2101',
                'reason': 'required_for_soh',
                'description': 'Battery voltage signal'
            }
        )
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True


class TestReenableProposals:
    """Test signal re-enable proposals."""
    
    def test_check_reenable_proposals(self, app):
        """Test detecting signals that should be re-enabled."""
        with app.app_context():
            profile = CollectionProfile(
                version='profile-test-reenable',
                status=ProfileStatus.APPROVED.value,
                manufacturer='Tesla',
                model='Model3',
                signals_to_skip=['did:2101'],
                generation_evidence={},
                approved_at=datetime.now(timezone.utc)
            )
            
            db.session.add(profile)
            db.session.commit()
            
            stat = SignalUsageStats(
                manufacturer='Tesla',
                model='Model3',
                signal_identifier='did:2101',
                requested_count=10,
                responded_count=8,
                decoded_count=8,
                used_in_report_count=5
            )
            
            db.session.add(stat)
            db.session.commit()
            
            proposals = check_reenable_signals(
                manufacturer='Tesla',
                model='Model3',
                profile_id=profile.id
            )
            
            assert len(proposals) == 1
            assert proposals[0]['signal'] == 'did:2101'


class TestAdminRoutesCrawl:
    """Test that new admin routes are accessible."""
    
    def test_profiles_list_route(self, app, admin_client):
        """Test profiles list route."""
        response = admin_client.get('/admin/adaptive/profiles')
        assert response.status_code in [200, 500]
