"""Tests for scan flow integration (v2.2.25)."""

import pytest
from datetime import datetime, timezone

from app.extensions import db
from app.modules.adaptive_collection.models import (
    CollectionProfile,
    SignalWhitelist,
    SignalUsageStats,
    ProfileStatus
)
from app.modules.adaptive_collection.scan_integration import (
    get_active_profile,
    apply_profile_to_plan,
    should_include_step,
    get_whitelisted_signals,
    _step_to_signal_id
)


class TestProfileApplication:
    """Test profile application to scan plans."""
    
    def test_unapproved_profile_has_no_effect(self, app):
        """Unapproved profile does not affect request list."""
        with app.app_context():
            profile = CollectionProfile(
                version='test-draft',
                status=ProfileStatus.DRAFT.value,
                manufacturer='Tesla',
                model='Model3',
                signals_to_skip=['did:F190', 'pid:05'],
                generation_evidence={}
            )
            
            db.session.add(profile)
            db.session.commit()
            
            steps = [
                {'command': '22F190', 'label': 'VIN'},
                {'command': '0105', 'label': 'Coolant temp'},
                {'command': '010C', 'label': 'RPM'}
            ]
            
            filtered, profile_id, was_full = apply_profile_to_plan(
                steps, 'Tesla', 'Model3', force_full_scan=False, scan_count=1
            )
            
            assert len(filtered) == 3  # All steps included
            assert profile_id is None
            assert was_full is True
    
    def test_approved_profile_reduces_request_list(self, app):
        """Approved profile filters out skipped signals."""
        with app.app_context():
            profile = CollectionProfile(
                version='test-approved',
                status=ProfileStatus.APPROVED.value,
                manufacturer='Tesla',
                model='Model3',
                signals_to_skip=['did:F190', 'pid:05'],
                generation_evidence={},
                approved_at=datetime.now(timezone.utc)
            )
            
            db.session.add(profile)
            db.session.commit()
            
            steps = [
                {'command': '22F190', 'label': 'VIN'},
                {'command': '0105', 'label': 'Coolant temp'},
                {'command': '010C', 'label': 'RPM'}
            ]
            
            filtered, profile_id, was_full = apply_profile_to_plan(
                steps, 'Tesla', 'Model3', force_full_scan=False, scan_count=1
            )
            
            assert len(filtered) == 1  # Only RPM (010C) included
            assert profile_id == profile.id
            assert was_full is False
            assert filtered[0]['command'] == '010C'
    
    def test_whitelisted_signals_never_skipped(self, app):
        """Whitelisted signals always included even if in skip list."""
        with app.app_context():
            # Add to whitelist
            whitelist = SignalWhitelist(
                signal_identifier='did:F190',
                reason='required_for_vin',
                is_active=True
            )
            
            profile = CollectionProfile(
                version='test-whitelist',
                status=ProfileStatus.APPROVED.value,
                manufacturer='Tesla',
                model='Model3',
                signals_to_skip=['did:F190', 'pid:05'],  # F190 is whitelisted
                generation_evidence={},
                approved_at=datetime.now(timezone.utc)
            )
            
            db.session.add_all([whitelist, profile])
            db.session.commit()
            
            steps = [
                {'command': '22F190', 'label': 'VIN'},
                {'command': '0105', 'label': 'Coolant temp'},
                {'command': '010C', 'label': 'RPM'}
            ]
            
            filtered, profile_id, was_full = apply_profile_to_plan(
                steps, 'Tesla', 'Model3', force_full_scan=False, scan_count=1
            )
            
            assert len(filtered) == 2  # VIN (whitelisted) + RPM
            commands = [s['command'] for s in filtered]
            assert '22F190' in commands
            assert '010C' in commands
            assert '0105' not in commands
    
    def test_force_full_scan_bypasses_profile(self, app):
        """force_full_scan ignores profile and includes all steps."""
        with app.app_context():
            profile = CollectionProfile(
                version='test-forced',
                status=ProfileStatus.APPROVED.value,
                manufacturer='Tesla',
                model='Model3',
                signals_to_skip=['did:F190', 'pid:05'],
                generation_evidence={},
                approved_at=datetime.now(timezone.utc)
            )
            
            db.session.add(profile)
            db.session.commit()
            
            steps = [
                {'command': '22F190', 'label': 'VIN'},
                {'command': '0105', 'label': 'Coolant temp'},
                {'command': '010C', 'label': 'RPM'}
            ]
            
            filtered, profile_id, was_full = apply_profile_to_plan(
                steps, 'Tesla', 'Model3', force_full_scan=True, scan_count=1
            )
            
            assert len(filtered) == 3  # All steps included
            assert profile_id is None
            assert was_full is True
    
    def test_nth_scan_sampling(self, app):
        """Every Nth scan automatically becomes full rescan sample."""
        with app.app_context():
            profile = CollectionProfile(
                version='test-nth',
                status=ProfileStatus.APPROVED.value,
                manufacturer='Tesla',
                model='Model3',
                signals_to_skip=['did:F190'],
                generation_evidence={},
                approved_at=datetime.now(timezone.utc),
                full_rescan_interval=10
            )
            
            db.session.add(profile)
            db.session.commit()
            
            steps = [
                {'command': '22F190', 'label': 'VIN'},
                {'command': '010C', 'label': 'RPM'}
            ]
            
            # Scan 9: not Nth scan, profile applies
            filtered, profile_id, was_full = apply_profile_to_plan(
                steps, 'Tesla', 'Model3', force_full_scan=False, scan_count=9
            )
            assert len(filtered) == 1  # F190 skipped
            assert was_full is False
            
            # Scan 10: Nth scan (10 % 10 == 0), full rescan
            filtered, profile_id, was_full = apply_profile_to_plan(
                steps, 'Tesla', 'Model3', force_full_scan=False, scan_count=10
            )
            assert len(filtered) == 2  # All included
            assert was_full is True
            
            # Scan 20: also Nth scan
            filtered, profile_id, was_full = apply_profile_to_plan(
                steps, 'Tesla', 'Model3', force_full_scan=False, scan_count=20
            )
            assert len(filtered) == 2
            assert was_full is True
    
    def test_model_override_precedence(self, app):
        """Model-specific profile takes precedence over manufacturer."""
        with app.app_context():
            manufacturer_profile = CollectionProfile(
                version='test-maker',
                status=ProfileStatus.APPROVED.value,
                manufacturer='Tesla',
                model=None,  # Manufacturer-level
                signals_to_skip=['did:F190'],
                generation_evidence={},
                approved_at=datetime.now(timezone.utc)
            )
            
            model_profile = CollectionProfile(
                version='test-model',
                status=ProfileStatus.APPROVED.value,
                manufacturer='Tesla',
                model='Model3',  # Model-specific
                signals_to_skip=['pid:05'],
                generation_evidence={},
                approved_at=datetime.now(timezone.utc)
            )
            
            db.session.add_all([manufacturer_profile, model_profile])
            db.session.commit()
            
            # Model3 should use model-specific profile
            profile = get_active_profile('Tesla', 'Model3')
            assert profile.id == model_profile.id
            assert profile.signals_to_skip == ['pid:05']
            
            # ModelX should use manufacturer-level profile
            profile = get_active_profile('Tesla', 'ModelX')
            assert profile.id == manufacturer_profile.id
            assert profile.signals_to_skip == ['did:F190']


class TestSignalIdentification:
    """Test signal identifier conversion."""
    
    def test_step_to_signal_id_did(self, app):
        """UDS DID correctly converted."""
        with app.app_context():
            assert _step_to_signal_id({'command': '22F190'}) == 'did:F190'
            assert _step_to_signal_id({'command': '22 F190'}) == 'did:F190'
            assert _step_to_signal_id({'command': '221050'}) == 'did:1050'
    
    def test_step_to_signal_id_pid(self, app):
        """OBD PID correctly converted."""
        with app.app_context():
            assert _step_to_signal_id({'command': '0105'}) == 'pid:05'
            assert _step_to_signal_id({'command': '010C'}) == 'pid:0C'
    
    def test_step_to_signal_id_uds(self, app):
        """UDS commands correctly converted."""
        with app.app_context():
            assert _step_to_signal_id({'command': '190209'}) == 'uds:190209'
            assert _step_to_signal_id({'command': '1902FF'}) == 'uds:1902FF'


class TestAccessControl:
    """Test non-admin 403 responses."""
    
    def test_non_admin_cannot_access_profiles(self, app, client, make_user):
        """Non-admin gets 403 on profile routes."""
        with app.app_context():
            user_id = make_user('tester', type='tester')
        
        client.post('/admin/login', data={'tid': 'tester', 'pwd': 'test'})
        
        response = client.get('/admin/adaptive/profiles')
        assert response.status_code == 403
    
    def test_non_admin_cannot_approve(self, app, client, make_user):
        """Non-admin gets 403 on approve."""
        with app.app_context():
            user_id = make_user('tester', type='tester')
            
            profile = CollectionProfile(
                version='test',
                status=ProfileStatus.DRAFT.value,
                manufacturer='Tesla',
                signals_to_skip=[],
                generation_evidence={}
            )
            db.session.add(profile)
            db.session.commit()
            profile_id = profile.id
        
        client.post('/admin/login', data={'tid': 'tester', 'pwd': 'test'})
        
        response = client.post(
            f'/admin/adaptive/profiles/{profile_id}/approve',
            json={'notes': 'test'}
        )
        assert response.status_code == 403
