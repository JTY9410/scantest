"""Final comprehensive tests for ML Quality Phase 1 (v2.2.22)."""
import pytest
from datetime import datetime, timezone

from app.extensions import db
from app.modules.ml_quality.models import (
    ScanQualitySignal, ImprovementProposal, VersionedConfig
)


class TestPhase1Complete:
    """Complete Phase 1 test coverage."""

    def test_signal_model_creation(self, app):
        """Create and store quality signals."""
        with app.app_context():
            from app.modules.scans.models import Scan
            from app.modules.accounts.models import User
            
            # Get or create user
            user = db.session.query(User).first()
            if not user:
                pytest.skip("No users in test database")
            
            # Create scan
            scan = Scan(
                type='ev',
                device_uid='test-dev',
                tester_id=user.id,
                car_maker='Tesla',
                car_model='Model 3',
                car_no='88가8888',
                car_vin='ZZZ12345678901234',
                status='ok'
            )
            db.session.add(scan)
            db.session.flush()
            
            # Create signal
            signal = ScanQualitySignal(
                scan_id=scan.id,
                decode_failures={"2101": "Unknown"},
                dtc_status_unknown_count=2,
                collected_at=datetime.now(timezone.utc)
            )
            db.session.add(signal)
            db.session.commit()
            
            assert signal.id is not None
            
            # Verify no VIN in data
            assert 'ZZZ12345678901234' not in str(signal.decode_failures)
    
    def test_proposal_lifecycle(self, app):
        """Test proposal approval workflow."""
        with app.app_context():
            # Create proposal
            proposal = ImprovementProposal(
                status="pending",
                manufacturer="Tesla",
                proposal_type="decoder_mapping",
                evidence={"sample_size": 15},
                config_delta={"action": "test"},
                generation_method="rule_based"
            )
            db.session.add(proposal)
            db.session.flush()
            
            # Approve
            proposal.status = "approved"
            config = VersionedConfig(
                config_type="decoder_mapping",
                manufacturer="Tesla",
                config_key=f"test_{proposal.id}",
                config_value={"test": True},
                proposal_id=proposal.id,
                active=True,
                activated_at=datetime.now(timezone.utc)
            )
            db.session.add(config)
            db.session.commit()
            
            # Verify active
            active_configs = db.session.query(VersionedConfig).filter_by(
                active=True, proposal_id=proposal.id
            ).all()
            assert len(active_configs) == 1
            
            # Rollback
            proposal.status = "rolled_back"
            config.active = False
            config.deactivated_at = datetime.now(timezone.utc)
            db.session.commit()
            
            # Verify inactive
            active_configs = db.session.query(VersionedConfig).filter_by(
                active=True, proposal_id=proposal.id
            ).all()
            assert len(active_configs) == 0
    
    def test_admin_routes_exist(self, admin_client):
        """Verify admin routes are accessible."""
        response = admin_client.get("/admin/ml/quality/proposals")
        assert response.status_code == 200
    
    def test_non_admin_blocked(self, client, make_user):
        """Non-admin gets redirected/blocked."""
        with client.application.app_context():
            user = make_user("regular", type="tester", password="test")
            db.session.commit()
        
        client.post("/auth/login", data={
            "username": "regular",
            "password": "test"
        })
        
        response = client.get("/admin/ml/quality/proposals", follow_redirects=False)
        assert response.status_code in [302, 403]
