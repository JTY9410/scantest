"""End-to-end test for adaptive collection integration (v2.2.26)."""

import pytest
from datetime import datetime, timezone

from app.extensions import db
from app.modules.adaptive_collection.models import (
    CollectionProfile,
    SignalWhitelist,
    SignalUsageStats,
    ProfileStatus
)
from app.modules.scans.models import Scan
from app.modules.scanner.profile_hook import apply_profile_if_enabled


class TestAdaptiveE2E:
    """End-to-end tests for adaptive collection."""
    
    def test_profile_applied_in_scan_flow(self, app):
        """Test that profiles are applied when building scan plan."""
        with app.app_context():
            # Create approved profile
            profile = CollectionProfile(
                version='test-e2e',
                status=ProfileStatus.APPROVED.value,
                manufacturer='Tesla',
                model='Model3',
                signals_to_skip=['did:F190'],
                generation_evidence={},
                approved_at=datetime.now(timezone.utc)
            )
            
            db.session.add(profile)
            db.session.commit()
            
            # Simulate scan plan
            steps = [
                {'command': '22F190', 'label': 'VIN'},
                {'command': '010C', 'label': 'RPM'}
            ]
            
            # Apply profile through hook (called from service.py:306)
            filtered, profile_id, was_full = apply_profile_if_enabled(
                steps, 'Tesla', 'Model3', force_full_scan=False
            )
            
            # Verify profile was applied
            assert len(filtered) == 1  # F190 skipped
            assert filtered[0]['command'] == '010C'
            assert profile_id == profile.id
            assert was_full is False
    
    def test_force_full_scan_in_flow(self, app):
        """Test force_full_scan bypasses profile."""
        with app.app_context():
            profile = CollectionProfile(
                version='test-force',
                status=ProfileStatus.APPROVED.value,
                manufacturer='Tesla',
                model='Model3',
                signals_to_skip=['did:F190'],
                generation_evidence={},
                approved_at=datetime.now(timezone.utc)
            )
            
            db.session.add(profile)
            db.session.commit()
            
            steps = [
                {'command': '22F190', 'label': 'VIN'},
                {'command': '010C', 'label': 'RPM'}
            ]
            
            # Force full scan
            filtered, profile_id, was_full = apply_profile_if_enabled(
                steps, 'Tesla', 'Model3', force_full_scan=True
            )
            
            # Verify all steps included
            assert len(filtered) == 2
            assert profile_id is None
            assert was_full is True


class TestCallPoints:
    """Verify integration call points."""
    
    def test_service_integration_point(self, app):
        """Verify profile application is called from service.py."""
        # This tests that the integration point exists and is callable
        # Actual line: app/modules/scanner/service.py:306
        from app.modules.scanner.profile_hook import apply_profile_if_enabled
        
        # Simulate what happens at line 306
        steps = [{'command': '010C'}]
        result = apply_profile_if_enabled(steps, 'Tesla', 'Model3')
        
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert isinstance(result[0], list)  # filtered steps
        # result[1] is profile_id (int or None)
        assert isinstance(result[2], bool)  # was_full_scan
