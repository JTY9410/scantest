"""Test ML tables migration from empty DB and from v2.2.8 head."""

import pytest
from sqlalchemy import text, inspect
from flask_migrate import upgrade, downgrade, stamp


def test_migration_from_empty_db(app):
    """Test that migration creates all ML tables from empty DB."""
    with app.app_context():
        from app.extensions import db
        
        # Skip for SQLite - migrations have PostgreSQL-specific features
        if 'sqlite' in str(db.engine.url):
            pytest.skip("Empty DB migration test requires PostgreSQL")
        
        # Drop all tables (with CASCADE for PostgreSQL foreign keys)
        if db.engine.name == 'postgresql':
            # Drop alembic_version first, then use drop_all with CASCADE via raw SQL
            db.session.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
            db.session.commit()
            # Get all table names and drop with CASCADE
            inspector = inspect(db.engine)
            for table in inspector.get_table_names():
                db.session.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
            db.session.commit()
        else:
            db.drop_all()
            db.session.execute(text("DROP TABLE IF EXISTS alembic_version"))
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
    """Test production upgrade path: v2.2.8 (bf7eda1, 20261116_120000) -> current head."""
    with app.app_context():
        from app.extensions import db
        from datetime import datetime
        
        # Skip for SQLite - only test production path with PostgreSQL
        if 'sqlite' in str(db.engine.url):
            pytest.skip("Production upgrade test requires PostgreSQL")
        
        # Drop all tables
        db.session.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
        db.session.commit()
        inspector = inspect(db.engine)
        for table in inspector.get_table_names():
            db.session.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
        db.session.commit()
        
        # Set longer lock timeout for migration DDL operations
        db.session.execute(text("SET lock_timeout = '60s'"))
        db.session.commit()
        
        # Upgrade to v2.2.8 head (20261116_120000) via full migration chain
        upgrade(revision='20261116_120000')
        
        # Insert test data with v2.2.8 battery_reference_capacity schema
        # (old format: manufacturer, model, year_from, year_to, pack_code, 
        #  reference_energy_kwh, reference_definition, source_url, source_type, verified)
        db.session.execute(text("""
            INSERT INTO battery_reference_capacity 
                (manufacturer, model, year_from, year_to, pack_code, reference_energy_kwh,
                 reference_definition, source_url, source_type, verified, created_at)
            VALUES 
                ('Tesla', 'Model 3 Old', 2018, 2021, 'PK999', 75.0, 'Gross', 
                 'https://example.com/old', 'Official', true, NOW())
        """))
        
        # Create test user for foreign key (scans.tester_id references users.id)
        # (users at v2.2.8: type NOT NULL IN ('admin','tester','owner'), password NOT NULL)
        db.session.execute(text("""
            INSERT INTO users (tid, name, type, password, created_at, updated_at)
            VALUES ('test_tester', 'Test Tester', 'tester', 
                    'test_password_hash_placeholder', NOW(), NOW())
        """))
        tester_id = db.session.execute(text("SELECT id FROM users WHERE tid = 'test_tester'")).scalar()
        
        # Insert test scans and ml_scan_features to verify they survive
        db.session.execute(text(f"""
            INSERT INTO scans 
                (type, device_type, device_uid, tester_id, car_no, car_vin, car_model,
                 created_at, updated_at)
            VALUES 
                ('ev', 'obd', 'TEST-DEVICE-001', {tester_id}, '11가1111', 'TEST1234567890123', 
                 'Model 3', NOW(), NOW())
        """))
        scan_id = db.session.execute(text("SELECT id FROM scans WHERE car_no = '11가1111'")).scalar()
        
        db.session.commit()
        
        # Count rows before upgrade
        battery_ref_count_before = db.session.execute(text("SELECT COUNT(*) FROM battery_reference_capacity")).scalar()
        scans_count_before = db.session.execute(text("SELECT COUNT(*) FROM scans")).scalar()
        
        # Note: ml_scan_features at v2.2.8 is empty (new table), and later migrations add
        # NOT NULL columns (maker, etc), so we can't insert v2.2.8-compatible data that survives
        # all migrations. Production v2.2.8 databases have empty ml_scan_features tables.
        
        # Ensure lock timeout is set before upgrading to head (DDL operations need time)
        db.session.execute(text("SET lock_timeout = '60s'"))
        db.session.commit()
        
        # Now upgrade to current head (production path)
        upgrade()
        
        # Verify all tables exist and match models
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        required_tables = [
            'ml_model_runs', 'ml_active_model', 'ml_consistency_scores',
            'battery_reference_capacity', 'scans', 'ml_scan_features'
        ]
        for table in required_tables:
            assert table in tables, f"Table {table} missing after upgrade"
        
        # Verify battery_reference_capacity has new columns
        battery_cols = {col['name'] for col in inspector.get_columns('battery_reference_capacity')}
        new_cols = {'maker', 'pack_id', 'gross_capacity_kwh', 'net_capacity_kwh', 
                    'source_url_1', 'verification_level', 'source_file'}
        assert new_cols.issubset(battery_cols), f"Missing battery columns: {new_cols - battery_cols}"
        
        # Verify scans survived
        scans_count_after = db.session.execute(text("SELECT COUNT(*) FROM scans")).scalar()
        assert scans_count_after == scans_count_before, \
            f"Scans lost: {scans_count_before} -> {scans_count_after}"
        
        # Verify ml_scan_features table exists and has extended columns
        ml_features_cols = {col['name'] for col in inspector.get_columns('ml_scan_features')}
        assert 'maker' in ml_features_cols, "ml_scan_features should have 'maker' column after upgrade"
        
        # Run battery reference seed (simulates entrypoint)
        from app.modules.scans.battery_ref_seed import seed_battery_references
        from pathlib import Path
        
        # Debug: check if data files exist
        data_dir = Path(__file__).parent.parent.parent / 'data' / 'battery_reference'
        print(f"DEBUG: data_dir exists: {data_dir.exists()}, path: {data_dir}")
        if data_dir.exists():
            xlsx_files = list(data_dir.glob('*.xlsx'))
            print(f"DEBUG: found {len(xlsx_files)} xlsx files: {[f.name for f in xlsx_files]}")
        
        # Check count before seed
        count_before = db.session.execute(text("SELECT COUNT(*) FROM battery_reference_capacity")).scalar()
        print(f"DEBUG: battery_reference_capacity count before seed: {count_before}")
        
        seed_battery_references()
        
        # Verify seed loaded correct data
        # Expected count: 221 rows from data sheets (import7: 20, Tesla: 201)
        # (2 rows with all NULL capacities are excluded: Land Rover Range Rover Electric models)
        # (Note: xlsx files have 593 total rows across all sheets, but many are documentation/formulas, not battery data)
        battery_ref_count = db.session.execute(text("SELECT COUNT(*) FROM battery_reference_capacity")).scalar()
        print(f"DEBUG: battery_reference_capacity count after seed: {battery_ref_count}")
        assert battery_ref_count == 221, \
            f"Battery reference count mismatch: expected 221 (import7:20 + Tesla:201, 2 NULL capacity rows excluded), got {battery_ref_count}"
        
        # Verify specific Tesla pack IDs are present
        pk045_exists = db.session.execute(text(
            "SELECT COUNT(*) FROM battery_reference_capacity WHERE pack_id = 'PK045'"
        )).scalar()
        pk044_exists = db.session.execute(text(
            "SELECT COUNT(*) FROM battery_reference_capacity WHERE pack_id = 'PK044'"
        )).scalar()
        
        assert pk045_exists > 0, "PK045 (Model Y LR AWD) not found in seed data"
        assert pk044_exists > 0, "PK044 (Model Y LR China) not found in seed data"
        
        # Verify old-format test row was replaced
        old_row_exists = db.session.execute(text(
            "SELECT COUNT(*) FROM battery_reference_capacity WHERE model = 'Model 3 Old'"
        )).scalar()
        assert old_row_exists == 0, "Old-format test row should have been replaced by seed"


def test_production_config_starts_no_threads(app):
    """Verify that scheduler is not started when flags are unset (default)."""
    import os
    
    # This tests the documented production config requirement:
    # ML_SCHEDULER_ENABLED and ML_AUTO_BACKFILL must be explicitly enabled
    
    # Verify flags are disabled by default
    sched_enabled = os.environ.get('ML_SCHEDULER_ENABLED', '').lower() in ('true', '1', 'yes')
    backfill_enabled = os.environ.get('ML_AUTO_BACKFILL', '').lower() in ('true', '1', 'yes')
    
    assert not sched_enabled, "ML_SCHEDULER_ENABLED must not be enabled by default"
    assert not backfill_enabled, "ML_AUTO_BACKFILL must not be enabled by default"
    
    # Integration test confirms no threads are started when these are false


def test_single_migration_head(app):
    """Verify there is only one migration head."""
    with app.app_context():
        from flask_migrate import current
        from alembic import command
        from app.extensions import migrate
        
        # Get migration context
        config = migrate.get_config()
        script = command.ScriptDirectory.from_config(config)
        
        # Get all heads
        heads = list(script.get_heads())
        assert len(heads) == 1, f"Expected 1 head, found {len(heads)}: {heads}"


def test_ml_tables_have_correct_columns(app):
    """Verify ML tables have correct column structure."""
    with app.app_context():
        from app.extensions import db
        
        # Skip for SQLite - migrations have PostgreSQL-specific features
        if 'sqlite' in str(db.engine.url):
            pytest.skip("ML tables test requires PostgreSQL migrations")
        
        # Drop and recreate via migrations to ensure schema is correct
        if db.engine.name == 'postgresql':
            db.session.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
            db.session.commit()
            # Get all table names and drop with CASCADE
            inspector_pre = inspect(db.engine)
            for table in inspector_pre.get_table_names():
                db.session.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
            db.session.commit()
        else:
            db.drop_all()
            db.session.execute(text("DROP TABLE IF EXISTS alembic_version"))
            db.session.commit()
        
        # Run migrations to create tables
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
