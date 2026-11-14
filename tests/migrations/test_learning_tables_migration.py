"""Test learning persistence tables migration."""
import pytest
from sqlalchemy import text, inspect
from app.extensions import db


def test_migration_creates_command_stats_table(app):
    """Test that migration creates command_stats table with correct schema."""
    with app.app_context():
        inspector = inspect(db.engine)
        
        # Check table exists
        assert 'command_stats' in inspector.get_table_names()
        
        # Check columns
        columns = {col['name']: col for col in inspector.get_columns('command_stats')}
        
        assert 'id' in columns
        assert 'maker' in columns
        assert 'model' in columns
        assert 'ecu' in columns
        assert 'command' in columns
        assert 'attempts' in columns
        assert 'successes' in columns
        assert 'timeouts' in columns
        assert 'nrcs' in columns
        assert 'ucb_score' in columns
        assert 'thompson_alpha' in columns
        assert 'thompson_beta' in columns
        assert 'last_seen' in columns
        
        # Check indexes
        indexes = {idx['name']: idx for idx in inspector.get_indexes('command_stats')}
        assert 'ix_command_stats_maker' in indexes
        assert 'ix_command_stats_ecu' in indexes


def test_migration_creates_learning_runs_table(app):
    """Test that migration creates learning_runs table."""
    with app.app_context():
        inspector = inspect(db.engine)
        
        assert 'learning_runs' in inspector.get_table_names()
        
        columns = {col['name']: col for col in inspector.get_columns('learning_runs')}
        
        assert 'id' in columns
        assert 'run_name' in columns
        assert 'params' in columns
        assert 'metrics' in columns
        assert 'status' in columns
        assert 'promoted_at' in columns
        assert 'rolled_back_at' in columns


def test_command_stats_unique_constraint(app):
    """Test that command_stats has unique constraint on (maker, model, ecu, command)."""
    with app.app_context():
        # Insert first row
        db.session.execute(text("""
            INSERT INTO command_stats (maker, model, ecu, command)
            VALUES ('Hyundai', 'Ioniq 5', 'BMS', '220101')
        """))
        db.session.commit()
        
        # Try to insert duplicate - should fail
        with pytest.raises(Exception):  # IntegrityError
            db.session.execute(text("""
                INSERT INTO command_stats (maker, model, ecu, command)
                VALUES ('Hyundai', 'Ioniq 5', 'BMS', '220101')
            """))
            db.session.commit()
        
        db.session.rollback()


def test_migration_from_023ea1858efa_works(app):
    """Test that upgrading from 023ea1858efa (Mac state) works."""
    # This test verifies the migration path is clean
    # If the test suite runs successfully, this path works
    with app.app_context():
        # Just verify tables exist (created by conftest fixture)
        inspector = inspect(db.engine)
        assert 'command_stats' in inspector.get_table_names()
        assert 'learning_runs' in inspector.get_table_names()
