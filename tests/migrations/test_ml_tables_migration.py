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
        
        # Upgrade to v2.2.8 head (20261116_120000) via full migration chain
        upgrade(revision='20261116_120000')
        
        # Insert representative data with v2.2.8 schema
        # battery_reference_capacity had: id, manufacturer, model, year_from, year_to,
        # pack_code, reference_energy_kwh, reference_definition, source_url, source_type,
        # verified, notes, created_at
        db.session.execute(text("""
            INSERT INTO battery_reference_capacity 
                (manufacturer, model, year_from, year_to, pack_code, reference_energy_kwh,
                 reference_definition, source_url, source_type, verified, notes, created_at)
            VALUES 
                ('Tesla', 'Model 3', 2018, 2021, 'PK031', 75.0, 'Gross', 
                 'https://example.com/source', 'Official', true, 'Test data', NOW())
        """))
        
        # Insert test scan
        db.session.execute(text("""
            INSERT INTO scans 
                (car_no, vin, timestamp, result_summary)
            VALUES 
                ('11가1111', 'TEST1234567890123', NOW(), '{"status": "ok"}')
        """))
        scan_id = db.session.execute(text("SELECT id FROM scans WHERE car_no = '11가1111'")).scalar()
        
        # Insert ml_scan_features
        db.session.execute(text(f"""
            INSERT INTO ml_scan_features 
                (scan_id, feature_vector, decoded_values, signals_read, created_at)
            VALUES 
                ({scan_id}, '{{}}', '{{}}', '{{}}', NOW())
        """))
        
        db.session.commit()
        
        # Count existing rows
        battery_ref_count_before = db.session.execute(text("SELECT COUNT(*) FROM battery_reference_capacity")).scalar()
        scans_count_before = db.session.execute(text("SELECT COUNT(*) FROM scans")).scalar()
        ml_features_count_before = db.session.execute(text("SELECT COUNT(*) FROM ml_scan_features")).scalar()
        
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
                    'source_url_1', 'verification_level'}
        assert new_cols.issubset(battery_cols), f"Missing battery columns: {new_cols - battery_cols}"
        
        # Verify data survived migration
        battery_ref_count_after = db.session.execute(text("SELECT COUNT(*) FROM battery_reference_capacity")).scalar()
        scans_count_after = db.session.execute(text("SELECT COUNT(*) FROM scans")).scalar()
        ml_features_count_after = db.session.execute(text("SELECT COUNT(*) FROM ml_scan_features")).scalar()
        
        # Battery reference should have more rows (seed data loaded)
        assert battery_ref_count_after > battery_ref_count_before, \
            "Battery reference seed did not load"
        assert scans_count_after == scans_count_before, "Scans data lost"
        assert ml_features_count_after == ml_features_count_before, "ML features data lost"


def test_production_config_starts_no_threads(app):
    """Verify production config does not start scheduler threads in web workers."""
    import os
    import threading
    from app import create_app
    
    # Use test app's database URI (already valid)
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    
    # Save original env
    orig_sched = os.environ.get('ML_SCHEDULER_ENABLED')
    orig_backfill = os.environ.get('ML_AUTO_BACKFILL')
    orig_db = os.environ.get('SQLALCHEMY_DATABASE_URI')
    orig_secret = os.environ.get('SECRET_KEY')
    
    try:
        # Set production-like config with scheduler disabled (default)
        os.environ['SQLALCHEMY_DATABASE_URI'] = db_uri
        os.environ['SECRET_KEY'] = 'test-key-for-thread-test'
        os.environ.pop('ML_SCHEDULER_ENABLED', None)
        os.environ.pop('ML_AUTO_BACKFILL', None)
        
        # Count threads before app creation
        threads_before = set(t.name for t in threading.enumerate())
        
        # Create production app (config_name='production' but TESTING will be False)
        prod_app = create_app('production')
        
        with prod_app.app_context():
            # Count threads after app creation
            threads_after = set(t.name for t in threading.enumerate())
            new_threads = threads_after - threads_before
            
            # Filter scheduler/backfill threads
            scheduler_threads = [t for t in new_threads 
                                if 'scheduler' in t.lower() or 'backfill' in t.lower()]
            
            assert len(scheduler_threads) == 0, \
                f"Production app started scheduler threads: {scheduler_threads}"
    
    finally:
        # Restore env
        if orig_db:
            os.environ['SQLALCHEMY_DATABASE_URI'] = orig_db
        else:
            os.environ.pop('SQLALCHEMY_DATABASE_URI', None)
        if orig_secret:
            os.environ['SECRET_KEY'] = orig_secret
        else:
            os.environ.pop('SECRET_KEY', None)
        if orig_sched:
            os.environ['ML_SCHEDULER_ENABLED'] = orig_sched
        if orig_backfill:
            os.environ['ML_AUTO_BACKFILL'] = orig_backfill


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
