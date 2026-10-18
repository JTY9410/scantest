"""Test knowledge base CRUD operations."""
import pytest
from app.extensions import db
from app.modules.knowledge.models import KnowledgeCommand, KnowledgeDTC, KnowledgeFormula, KnowledgeTerm
from app.modules.knowledge.service import list_commands, list_formulas, list_dtcs, verify_command


def test_create_command(app):
    """Test creating a knowledge command."""
    with app.app_context():
        cmd = KnowledgeCommand(
            maker="현대",
            model="아반떼",
            command="22 1050",
            label="실주행거리",
            source="test",
            status="draft",
        )
        db.session.add(cmd)
        db.session.commit()
        
        assert cmd.id is not None
        assert cmd.status == "draft"


def test_list_verified_only(app):
    """Test that list functions return only verified items by default."""
    with app.app_context():
        # Add draft
        draft = KnowledgeCommand(command="01 00", label="Draft", source="test", status="draft")
        db.session.add(draft)
        
        # Add verified
        verified = KnowledgeCommand(command="01 0C", label="Verified", source="test", status="verified")
        db.session.add(verified)
        db.session.commit()
        
        results = list_commands(status="verified")
        assert len([c for c in results if c.label == "Verified"]) > 0
        assert len([c for c in results if c.label == "Draft"]) == 0


def test_verify_command(app):
    """Test verifying a draft command."""
    with app.app_context():
        cmd = KnowledgeCommand(command="22 B002", label="Test", source="test", status="draft")
        db.session.add(cmd)
        db.session.commit()
        cmd_id = cmd.id
        
        verify_command(cmd_id, user_id=1)
        
        updated = db.session.get(KnowledgeCommand, cmd_id)
        assert updated.status == "verified"
        assert updated.verified_by == 1
        assert updated.verified_at is not None


def test_formula_with_maker(app):
    """Test formula scoping by maker."""
    with app.app_context():
        # Generic formula
        generic = KnowledgeFormula(
            command="01 0D",
            pid="0D",
            label="Vehicle Speed",
            formula="A",
            unit="km/h",
            source="SAE_J1979",
            status="verified",
        )
        db.session.add(generic)
        
        # Hyundai-specific formula
        hyundai = KnowledgeFormula(
            maker="현대",
            command="22 1050",
            pid="1050",
            label="실주행거리",
            formula="(A*256+B)/10",
            unit="km",
            source="wescan",
            status="verified",
        )
        db.session.add(hyundai)
        db.session.commit()
        
        all_formulas = list_formulas(status="verified", maker=None)
        hyundai_formulas = list_formulas(status="verified", maker="현대")
        
        assert len(hyundai_formulas) >= len([f for f in all_formulas if f.maker == "현대"])


def test_dtc_lookup(app):
    """Test DTC code lookup."""
    with app.app_context():
        dtc = KnowledgeDTC(
            code="P0300",
            description="Random/Multiple Cylinder Misfire Detected",
            category="Powertrain",
            source="SAE_J2012",
            status="verified",
        )
        db.session.add(dtc)
        db.session.commit()
        
        results = list_dtcs(status="verified")
        p0300 = next((d for d in results if d.code == "P0300"), None)
        assert p0300 is not None
        assert "Misfire" in p0300.description
