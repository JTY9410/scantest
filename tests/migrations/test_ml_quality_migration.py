"""Test ML Quality Analysis migration round-trip (v2.2.22 Phase 1)."""

import pytest
from sqlalchemy import text, inspect
from flask_migrate import upgrade, downgrade


def test_ml_quality_migration_roundtrip(app):
    """Test upgrade and downgrade of ML quality tables with single head."""
    with app.app_context():
        from app.extensions import db
        
        # Skip for SQLite - migrations are PostgreSQL-specific
        if 'sqlite' in str(db.engine.url):
            pytest.skip("Migration test requires PostgreSQL")
        
        # Drop all tables to start fresh
        db.session.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
        db.session.commit()
        inspector = inspect(db.engine)
        for table in inspector.get_table_names():
            db.session.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
        db.session.commit()
        
        # Upgrade to the revision BEFORE ML quality tables
        upgrade(revision='20261117_110000')
        
        # Verify ML quality tables don't exist yet
        inspector = inspect(db.engine)
        tables_before = inspector.get_table_names()
        assert 'scan_quality_signals' not in tables_before
        assert 'improvement_proposals' not in tables_before
        assert 'proposal_audit_log' not in tables_before
        assert 'versioned_configs' not in tables_before
        
        # Upgrade to ML quality migration (20261117_120000)
        upgrade(revision='20261117_120000')
        
        # Verify all ML quality tables exist with correct columns
        inspector = inspect(db.engine)
        tables_after = inspector.get_table_names()
        
        assert 'scan_quality_signals' in tables_after
        assert 'improvement_proposals' in tables_after
        assert 'proposal_audit_log' in tables_after
        assert 'versioned_configs' in tables_after
        
        # Verify scan_quality_signals columns
        signals_cols = {col['name'] for col in inspector.get_columns('scan_quality_signals')}
        assert 'id' in signals_cols
        assert 'scan_id' in signals_cols
        assert 'decode_failures' in signals_cols
        assert 'unmeasurable_items' in signals_cols
        assert 'dtc_status_unknown_count' in signals_cols
        assert 'consistency_score' in signals_cols
        
        # Verify improvement_proposals columns
        proposals_cols = {col['name'] for col in inspector.get_columns('improvement_proposals')}
        assert 'id' in proposals_cols
        assert 'status' in proposals_cols
        assert 'manufacturer' in proposals_cols
        assert 'model' in proposals_cols
        assert 'proposal_type' in proposals_cols
        assert 'evidence' in proposals_cols
        assert 'config_delta' in proposals_cols
        assert 'generation_method' in proposals_cols
        
        # Verify proposal_audit_log columns
        audit_cols = {col['name'] for col in inspector.get_columns('proposal_audit_log')}
        assert 'id' in audit_cols
        assert 'proposal_id' in audit_cols
        assert 'action' in audit_cols
        assert 'user_id' in audit_cols
        assert 'user_email' in audit_cols
        assert 'reason' in audit_cols
        
        # Verify versioned_configs columns
        configs_cols = {col['name'] for col in inspector.get_columns('versioned_configs')}
        assert 'id' in configs_cols
        assert 'config_type' in configs_cols
        assert 'config_key' in configs_cols
        assert 'config_value' in configs_cols
        assert 'proposal_id' in configs_cols
        assert 'active' in configs_cols
        
        # Downgrade back to 20261117_110000
        downgrade(revision='20261117_110000')
        
        # Verify ML quality tables removed
        inspector = inspect(db.engine)
        tables_after_downgrade = inspector.get_table_names()
        assert 'scan_quality_signals' not in tables_after_downgrade
        assert 'improvement_proposals' not in tables_after_downgrade
        assert 'proposal_audit_log' not in tables_after_downgrade
        assert 'versioned_configs' not in tables_after_downgrade
        
        # Upgrade again to verify idempotency
        upgrade(revision='20261117_120000')
        
        # Verify tables exist again
        inspector = inspect(db.engine)
        tables_final = inspector.get_table_names()
        assert 'scan_quality_signals' in tables_final
        assert 'improvement_proposals' in tables_final
        assert 'proposal_audit_log' in tables_final
        assert 'versioned_configs' in tables_final
        
        # Verify single migration head (no branches)
        heads = db.session.execute(text(
            "SELECT version_num FROM alembic_version"
        )).fetchall()
        assert len(heads) == 1, f"Expected single migration head, got {len(heads)}: {heads}"
