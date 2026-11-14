"""Test verification status boundary conditions.

사용자 요구사항:
- 9회 시도 = 미전환
- 10회 중 7회 성공(70%) = 미전환  
- 10회 중 8회 성공(80%) = verified 전환
"""
import pytest
from sqlalchemy import text
from app.extensions import db


@pytest.fixture
def boundary_cleanup(app):
    """Cleanup for boundary tests."""
    with app.app_context():
        db.session.execute(text("DELETE FROM command_stats WHERE maker = 'BoundaryTest'"))
        db.session.execute(text("DELETE FROM diagnostic_commands WHERE maker = 'BoundaryTest'"))
        db.session.execute(text("DELETE FROM definition_sources WHERE file_path LIKE '/test/boundary%'"))
        db.session.commit()
        
        yield
        
        db.session.execute(text("DELETE FROM command_stats WHERE maker = 'BoundaryTest'"))
        db.session.execute(text("DELETE FROM diagnostic_commands WHERE maker = 'BoundaryTest'"))
        db.session.execute(text("DELETE FROM definition_sources WHERE file_path LIKE '/test/boundary%'"))
        db.session.commit()


def test_9_attempts_not_verified(app, boundary_cleanup):
    """Test that 9 attempts does NOT trigger verification.
    
    사용자 요구사항: 9회 시도 = 미전환
    """
    from app.modules.scanner.continuous_learning import LearningStats
    from app.modules.scanner.service import _update_verification_status
    
    with app.app_context():
        maker = 'BoundaryTest'
        model = 'Model1'
        
        # Create source and command
        source_id = db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, sha256, file_size, imported_at)
            VALUES ('canze', '/test/boundary1.json', 'hash1', 100, NOW())
            RETURNING id
        """)).scalar()
        
        db.session.execute(text("""
            INSERT INTO diagnostic_commands 
                (source_id, source_type, maker, model, ecu_address, service, pid, 
                 command_bytes, label, verification_status, verification_count, success_count, failure_count, created_at, updated_at)
            VALUES 
                (:sid, 'canze', :maker, :model, 'BMS', '22', '0101', '220101', 'Test1', 'needs_verification', 0, 0, 0, now(), now())
        """), {'sid': source_id, 'maker': maker, 'model': model})
        db.session.commit()
        
        # Record 9 attempts with 100% success
        stats = LearningStats()
        for i in range(9):
            stats.record_command_result(maker, model, 'BMS', '220101', success=True, response_time_ms=100)
        stats.persist_to_database()
        
        # Update verification status
        _update_verification_status(maker, model)
        
        # Check status NOT changed
        status = db.session.execute(text("""
            SELECT verification_status
            FROM diagnostic_commands
            WHERE maker = :maker AND command_bytes = '220101'
        """), {'maker': maker}).scalar()
        
        assert status == 'needs_verification'


def test_10_attempts_70_percent_not_verified(app, boundary_cleanup):
    """Test that 10 attempts with 70% success does NOT trigger verification.
    
    사용자 요구사항: 10회 중 7회 성공(70%) = 미전환
    """
    from app.modules.scanner.continuous_learning import LearningStats
    from app.modules.scanner.service import _update_verification_status
    
    with app.app_context():
        maker = 'BoundaryTest'
        model = 'Model2'
        
        # Create source and command
        source_id = db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, sha256, file_size, imported_at)
            VALUES ('canze', '/test/boundary2.json', 'hash2', 100, NOW())
            RETURNING id
        """)).scalar()
        
        db.session.execute(text("""
            INSERT INTO diagnostic_commands 
                (source_id, source_type, maker, model, ecu_address, service, pid, 
                 command_bytes, label, verification_status, verification_count, success_count, failure_count, created_at, updated_at)
            VALUES 
                (:sid, 'canze', :maker, :model, 'BMS', '22', '0102', '220102', 'Test2', 'needs_verification', 0, 0, 0, now(), now())
        """), {'sid': source_id, 'maker': maker, 'model': model})
        db.session.commit()
        
        # Record 10 attempts with 70% success (7 success, 3 fail)
        stats = LearningStats()
        for i in range(7):
            stats.record_command_result(maker, model, 'BMS', '220102', success=True, response_time_ms=100)
        for i in range(3):
            stats.record_command_result(maker, model, 'BMS', '220102', success=False, error_type='nrc')
        stats.persist_to_database()
        
        # Update verification status
        _update_verification_status(maker, model)
        
        # Check status NOT changed
        status = db.session.execute(text("""
            SELECT verification_status
            FROM diagnostic_commands
            WHERE maker = :maker AND command_bytes = '220102'
        """), {'maker': maker}).scalar()
        
        assert status == 'needs_verification'


def test_10_attempts_80_percent_verified(app, boundary_cleanup):
    """Test that 10 attempts with 80% success DOES trigger verification.
    
    사용자 요구사항: 10회 중 8회 성공(80%) = verified 전환
    """
    from app.modules.scanner.continuous_learning import LearningStats
    from app.modules.scanner.service import _update_verification_status
    
    with app.app_context():
        maker = 'BoundaryTest'
        model = 'Model3'
        
        # Create source and command
        source_id = db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, sha256, file_size, imported_at)
            VALUES ('canze', '/test/boundary3.json', 'hash3', 100, NOW())
            RETURNING id
        """)).scalar()
        
        db.session.execute(text("""
            INSERT INTO diagnostic_commands 
                (source_id, source_type, maker, model, ecu_address, service, pid, 
                 command_bytes, label, verification_status, verification_count, success_count, failure_count, created_at, updated_at)
            VALUES 
                (:sid, 'canze', :maker, :model, 'BMS', '22', '0103', '220103', 'Test3', 'needs_verification', 0, 0, 0, now(), now())
        """), {'sid': source_id, 'maker': maker, 'model': model})
        db.session.commit()
        
        # Record 10 attempts with 80% success (8 success, 2 fail)
        stats = LearningStats()
        for i in range(8):
            stats.record_command_result(maker, model, 'BMS', '220103', success=True, response_time_ms=100)
        for i in range(2):
            stats.record_command_result(maker, model, 'BMS', '220103', success=False, error_type='nrc')
        stats.persist_to_database()
        
        # Update verification status
        _update_verification_status(maker, model)
        
        # Check status changed to verified
        result = db.session.execute(text("""
            SELECT verification_status, verification_count, success_count
            FROM diagnostic_commands
            WHERE maker = :maker AND command_bytes = '220103'
        """), {'maker': maker}).fetchone()
        
        assert result is not None
        assert result[0] == 'verified'
        assert result[1] == 10  # verification_count
        assert result[2] == 8   # success_count
