"""Test ML Quality Analysis Phase 1 (v2.2.22).

Scan error analysis and admin-approval improvement loop.
"""
import pytest
from datetime import datetime, timezone

from app.modules.ml_quality.models import ImprovementProposal, VersionedConfig
from app.extensions import db


class TestImprovementProposals:
    """Test improvement proposal models and basic operations."""

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
            assert proposal.proposal_type == "decoder_mapping"
    
    def test_versioned_config_creation(self, app):
        """Create a versioned config entry."""
        with app.app_context():
            proposal = ImprovementProposal(
                status="approved",
                manufacturer="Tesla",
                proposal_type="threshold",
                evidence={"sample_size": 20},
                config_delta={"action": "adjust_threshold", "value": 95},
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
            db.session.commit()
            
            assert config.id is not None
            assert config.active is True
            assert config.config_type == "threshold"
            assert config.config_value["value"] == 95
