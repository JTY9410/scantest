"""Promotion workflow tests"""
import pytest
from datetime import datetime

from app.extensions import db
from app.modules.knowledge.models import KnowledgeCommand, KnowledgeFormula, PromotionLog
from app.modules.knowledge.service import promote_command, promote_formula, demote_command, demote_formula


@pytest.fixture
def test_command(app):
    """Create a test command"""
    with app.app_context():
        cmd = KnowledgeCommand(
            maker="테스트",
            command="22TEST",
            label="테스트 명령어",
            source="test",
            status="experimental",
            confidence=0.7
        )
        db.session.add(cmd)
        db.session.commit()
        return cmd.id


@pytest.fixture
def test_formula(app):
    """Create a test formula"""
    with app.app_context():
        formula = KnowledgeFormula(
            maker="테스트",
            command="22TEST",
            label="테스트 수식",
            formula="A[0]",
            source="test",
            status="experimental",
            confidence=0.7
        )
        db.session.add(formula)
        db.session.commit()
        return formula.id


def test_promote_command(app, test_command):
    """Test command promotion"""
    with app.app_context():
        # Promote
        result = promote_command(test_command, user_id=1, evidence="테스트 검증")
        assert result is True
        
        # Check command status
        cmd = db.session.get(KnowledgeCommand, test_command)
        assert cmd.status == "verified"
        assert cmd.verified_by == 1
        assert cmd.verified_at is not None
        
        # Check audit log
        log = db.session.query(PromotionLog).filter_by(
            entity_type="command",
            entity_id=test_command
        ).first()
        assert log is not None
        assert log.old_status == "experimental"
        assert log.new_status == "verified"
        assert log.evidence == "테스트 검증"


def test_promote_formula(app, test_formula):
    """Test formula promotion"""
    with app.app_context():
        result = promote_formula(test_formula, user_id=1, evidence="실차 테스트")
        assert result is True
        
        formula = db.session.get(KnowledgeFormula, test_formula)
        assert formula.status == "verified"
        
        log = db.session.query(PromotionLog).filter_by(
            entity_type="formula",
            entity_id=test_formula
        ).first()
        assert log is not None
        assert log.new_status == "verified"


def test_demote_command(app, test_command):
    """Test command demotion"""
    with app.app_context():
        # First promote
        promote_command(test_command, user_id=1)
        
        # Then demote
        result = demote_command(test_command, user_id=1, reason="재검증 필요")
        assert result is True
        
        cmd = db.session.get(KnowledgeCommand, test_command)
        assert cmd.status == "experimental"
        
        # Check demotion log
        logs = db.session.query(PromotionLog).filter_by(
            entity_type="command",
            entity_id=test_command
        ).order_by(PromotionLog.promoted_at.desc()).all()
        
        assert len(logs) >= 2
        assert logs[0].new_status == "experimental"
        assert "재검증 필요" in (logs[0].notes or "")


def test_promote_nonexistent(app):
    """Test promoting non-existent command"""
    with app.app_context():
        result = promote_command(99999, user_id=1)
        assert result is False


def test_promote_already_verified(app, test_command):
    """Test promoting already verified command"""
    with app.app_context():
        # Promote twice
        promote_command(test_command, user_id=1)
        result = promote_command(test_command, user_id=1)
        assert result is True  # Should return True (idempotent)
        
        # Should only have one log entry
        logs = db.session.query(PromotionLog).filter_by(
            entity_type="command",
            entity_id=test_command
        ).all()
        assert len(logs) == 1


def test_promotion_log_tracking(app, test_command):
    """Test that all promotions are logged"""
    with app.app_context():
        # Multiple status changes
        promote_command(test_command, user_id=1, evidence="첫 검증")
        demote_command(test_command, user_id=2, reason="오류 발견")
        promote_command(test_command, user_id=3, evidence="재검증 완료")
        
        logs = db.session.query(PromotionLog).filter_by(
            entity_type="command",
            entity_id=test_command
        ).order_by(PromotionLog.promoted_at).all()
        
        assert len(logs) == 3
        assert logs[0].promoted_by == 1
        assert logs[1].promoted_by == 2
        assert logs[2].promoted_by == 3
