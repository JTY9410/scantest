"""Test ML Quality Analysis Phase 1 (v2.2.22).

Scan error analysis and admin-approval improvement loop.
"""
import pytest
from datetime import datetime, timezone

from app.modules.ml_quality.models import (
    ScanQualitySignal, ImprovementProposal, ProposalAuditLog, VersionedConfig
)
from app.modules.ml_quality.signal_collector import collect_quality_signals
from app.extensions import db


class TestQualitySignalCollection:
    """Test quality signal collection."""

    def test_collect_basic_signals(self, app):
        """Collect quality signals from scan result."""
        with app.app_context():
            from app.modules.scans.models import Scan
            from app.modules.accounts.models import User
            
            # Create test scan
            user = db.session.query(User).filter_by(type='admin').first()
            scan = Scan(
                type='ev',
                device_uid='test-device',
                tester_id=user.id,
                car_maker='Tesla',
                car_model='Model 3',
                car_no='88가8888',
                car_vin='ZZZ12345678901234',
                status='ok'
            )
            db.session.add(scan)
            db.session.flush()
            
            # Mock scan result with quality issues
            result = {
                "status": "ok",
                "errors": [
                    {"type": "decode_error", "did": "2101", "message": "Unknown format"},
                    {"type": "out_of_range", "signal": "pack_voltage", "value": 450, "range": "200-400"}
                ],
                "dtcs": [
                    {"code": "P0420", "status": 0x0D},
                    {"code": "P0171"}  # No status byte
                ],
                "steps": [
                    {"command": "22F190", "excluded": True, "exclude_reason": "Timeout"}
                ]
            }
            
            # Collect signals
            signal = collect_quality_signals(scan, result)
            
            assert signal.scan_id == scan.id
            assert signal.decode_failures == {"2101": "Unknown format"}
            assert signal.out_of_range_values == {"pack_voltage": {"value": 450, "range": "200-400"}}
            assert signal.dtc_status_unknown_count == 1
            assert len(signal.excluded_steps) == 1
            assert signal.excluded_steps[0]["command"] == "22F190"


class TestImprovementProposals:
    """Test improvement proposal lifecycle."""

    def test_create_proposal(self, app):
        """Create an improvement proposal."""
        with app.app_context():
            proposal = ImprovementProposal(
                status="pending",
                manufacturer="Tesla",
                model="Model 3",
                proposal_type="decoder_mapping",
                evidence={"sample_size": 15, "failures": {"2101": {"count": 12}}},
                config_delta={"action": "add_decoder_mappings", "dids": ["2101"]},
                expected_effect="Reduce decode failures for DID 2101",
                generation_method="rule_based"
            )
            db.session.add(proposal)
            db.session.commit()
            
            assert proposal.id is not None
            assert proposal.status == "pending"
            assert proposal.generation_method == "rule_based"
    
    def test_approve_proposal_creates_config(self, app):
        """Approving a proposal creates versioned config."""
        with app.app_context():
            from app.modules.accounts.models import User
            
            user = db.session.query(User).filter_by(type='admin').first()
            
            proposal = ImprovementProposal(
                status="pending",
                manufacturer="Tesla",
                proposal_type="decoder_mapping",
                evidence={"sample_size": 15},
                config_delta={"action": "add_decoder_mappings"},
                generation_method="rule_based"
            )
            db.session.add(proposal)
            db.session.flush()
            
            # Simulate approval
            proposal.status = "approved"
            audit = ProposalAuditLog(
                proposal_id=proposal.id,
                action="approve",
                user_id=user.id,
                user_email=user.email,
                previous_status="pending"
            )
            db.session.add(audit)
            
            config = VersionedConfig(
                config_type=proposal.proposal_type,
                manufacturer=proposal.manufacturer,
                config_key=f"{proposal.proposal_type}_{proposal.id}",
                config_value=proposal.config_delta,
                proposal_id=proposal.id,
                active=True,
                activated_at=datetime.now(timezone.utc)
            )
            db.session.add(config)
            db.session.commit()
            
            assert proposal.status == "approved"
            assert len(proposal.audit_logs) == 1
            assert proposal.audit_logs[0].action == "approve"
            assert config.active is True
    
    def test_rollback_deactivates_config(self, app):
        """Rolling back a proposal deactivates its configs."""
        with app.app_context():
            from app.modules.accounts.models import User
            
            user = db.session.query(User).filter_by(type='admin').first()
            
            proposal = ImprovementProposal(
                status="approved",
                manufacturer="Tesla",
                proposal_type="threshold",
                evidence={"sample_size": 20},
                config_delta={"action": "adjust_threshold"},
                generation_method="rule_based"
            )
            db.session.add(proposal)
            db.session.flush()
            
            config = VersionedConfig(
                config_type=proposal.proposal_type,
                manufacturer=proposal.manufacturer,
                config_key=f"{proposal.proposal_type}_{proposal.id}",
                config_value=proposal.config_delta,
                proposal_id=proposal.id,
                active=True,
                activated_at=datetime.now(timezone.utc)
            )
            db.session.add(config)
            db.session.flush()
            
            # Simulate rollback
            proposal.status = "rolled_back"
            config.active = False
            config.deactivated_at = datetime.now(timezone.utc)
            
            audit = ProposalAuditLog(
                proposal_id=proposal.id,
                action="rollback",
                user_id=user.id,
                user_email=user.email,
                previous_status="approved",
                reason="Testing rollback"
            )
            db.session.add(audit)
            db.session.commit()
            
            assert proposal.status == "rolled_back"
            assert config.active is False
            assert config.deactivated_at is not None
