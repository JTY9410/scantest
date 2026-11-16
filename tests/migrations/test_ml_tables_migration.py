"""Test ML tables migration from empty DB and from v2.2.8 head."""

import pytest
from sqlalchemy import text, inspect
from flask_migrate import upgrade, downgrade, stamp


def test_migration_from_empty_db(app):
    """Test that migration creates all ML tables from empty DB."""
    with app.app_context():
        from app.extensions import db
        
        # Drop all tables
        db.drop_all()
        db.session.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
        db.session.commit()
        
        # Run migrations
        upgrade()
        
        # Verify all ML tables exist
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        required_ml_tables = [
            'ml_scan_features',
            'ml_feedback',
            'ml_models',
            'ml_anomaly_detections',
            'ml_model_runs',
            'ml_active_model',
            'ml_consistency_scores',
            'ml_decoder_proposals',
        ]
        
        for table in required_ml_tables:
            assert table in tables, f"Table {table} not created by migration"


def test_migration_from_v228_head(app):
    """Test that migration works from v2.2.8 head (b67b02dd9931)."""
    with app.app_context():
        from app.extensions import db
        
        # Skip for SQLite - only test with PostgreSQL in CI
        if 'sqlite' in str(db.engine.url):
            pytest.skip("v2.2.8 head test requires PostgreSQL")
        
        # Drop all tables
        db.drop_all()
        db.session.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
        db.session.commit()
        
        # Stamp at v2.2.8 head (after command_stats migration)
        stamp(revision='b67b02dd9931')
        
        # Run upgrade to current head
        upgrade()
        
        # Verify all ML tables exist
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        required_ml_tables = [
            'ml_model_runs',
            'ml_active_model',
            'ml_consistency_scores',
        ]
        
        for table in required_ml_tables:
            assert table in tables, f"Table {table} not created by migration from v2.2.8"
        
        # Verify maker_aliases exists (should be there from earlier migration)
        assert 'maker_aliases' in tables, "maker_aliases table missing after upgrade from v2.2.8"


def test_single_migration_head(app):
    """Verify there is only one migration head."""
    with app.app_context():
        from flask_migrate import current, heads
        
        head_list = heads()
        assert len(head_list) == 1, f"Expected 1 head, found {len(head_list)}: {head_list}"


def test_ml_tables_have_correct_columns(app):
    """Verify ML tables have correct column structure."""
    with app.app_context():
        from app.extensions import db
        
        # Ensure tables exist
        upgrade()
        
        inspector = inspect(db.engine)
        
        # Check ml_model_runs columns
        ml_runs_cols = {col['name'] for col in inspector.get_columns('ml_model_runs')}
        required_runs_cols = {
            'id', 'run_type', 'trigger_reason', 'training_samples', 
            'validation_samples', 'test_samples', 'model_type', 'model_path',
            'metrics', 'status', 'error_message', 'started_at', 'completed_at'
        }
        assert required_runs_cols.issubset(ml_runs_cols), \
            f"ml_model_runs missing columns: {required_runs_cols - ml_runs_cols}"
        
        # Check ml_active_model columns
        active_cols = {col['name'] for col in inspector.get_columns('ml_active_model')}
        required_active_cols = {
            'id', 'model_run_id', 'activated_at', 'activated_by', 'model_path'
        }
        assert required_active_cols.issubset(active_cols), \
            f"ml_active_model missing columns: {required_active_cols - active_cols}"
        
        # Check ml_consistency_scores columns
        consistency_cols = {col['name'] for col in inspector.get_columns('ml_consistency_scores')}
        required_consistency_cols = {
            'id', 'scan_id', 'score', 'distribution_match', 
            'physical_plausibility', 'issues_detected', 'created_at'
        }
        assert required_consistency_cols.issubset(consistency_cols), \
            f"ml_consistency_scores missing columns: {required_consistency_cols - consistency_cols}"
