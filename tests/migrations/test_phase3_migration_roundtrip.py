"""Phase 3 migration round-trip test (v2.2.25)."""

import pytest
from sqlalchemy import text, inspect

from app import create_app
from app.extensions import db


@pytest.mark.skipif(
    not pytest.config.getoption("--test-db-url", default=""),
    reason="Migration test requires PostgreSQL"
)
def test_phase3_migration_roundtrip():
    """Test Phase 3 migration: upgrade, downgrade, upgrade."""
    import os
    os.environ.setdefault('TEST_DATABASE_URL', pytest.config.getoption("--test-db-url", default=""))
    
    app = create_app("testing")
    
    with app.app_context():
        # Get current revision
        from flask_migrate import upgrade, downgrade, current
        
        initial_rev = db.session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        
        # Downgrade Phase 3
        downgrade(revision='20261117_130000')  # Down to Phase 2
        
        # Verify Phase 3 tables don't exist
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        assert 'signal_usage_stats' not in tables
        assert 'collection_profiles' not in tables
        assert 'signal_whitelist' not in tables
        
        # Upgrade back to Phase 3
        upgrade(revision='20261117_150000')
        
        # Verify Phase 3 tables exist
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        assert 'signal_usage_stats' in tables
        assert 'collection_profiles' in tables
        assert 'collection_profile_audit' in tables
        assert 'signal_whitelist' in tables
        assert 'signal_whitelist_audit' in tables
        
        # Verify scan table has new columns
        scan_columns = {col['name'] for col in inspector.get_columns('scans')}
        assert 'collection_profile_id' in scan_columns
        assert 'was_full_scan' in scan_columns
        assert 'force_full_scan' in scan_columns
        assert 'is_rescan_sample' in scan_columns
        
        # Restore to initial revision
        if initial_rev:
            upgrade(revision=initial_rev)


def test_phase3_tables_structure(app):
    """Verify Phase 3 table structure in current database."""
    with app.app_context():
        from sqlalchemy import inspect
        
        inspector = inspect(db.engine)
        
        # Check signal_usage_stats
        if 'signal_usage_stats' in inspector.get_table_names():
            cols = {col['name'] for col in inspector.get_columns('signal_usage_stats')}
            assert 'id' in cols
            assert 'manufacturer' in cols
            assert 'model' in cols
            assert 'signal_identifier' in cols
            assert 'requested_count' in cols
            assert 'responded_count' in cols
            assert 'decoded_count' in cols
            assert 'used_in_report_count' in cols
            assert 'used_in_soh_count' in cols
            assert 'used_in_soh_inference_count' in cols
        
        # Check collection_profiles
        if 'collection_profiles' in inspector.get_table_names():
            cols = {col['name'] for col in inspector.get_columns('collection_profiles')}
            assert 'id' in cols
            assert 'version' in cols
            assert 'status' in cols
            assert 'manufacturer' in cols
            assert 'model' in cols
            assert 'signals_to_skip' in cols
            assert 'skip_threshold_scans' in cols
            assert 'full_rescan_interval' in cols
