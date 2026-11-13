"""Test full migration upgrade path from base to head."""
import os
import pytest
from sqlalchemy import text, create_engine
from sqlalchemy.engine.url import make_url
from alembic import command
from alembic.config import Config

from app import create_app
from app.extensions import db


def test_full_upgrade_path_with_seed_data():
    """Test complete migration path from base to head.
    
    Verifies:
    1. Fresh DB can upgrade from base to d7a3e8f6b2c9
    2. Definition data can be inserted at d7a3e8f6b2c9
    3. Upgrade to head succeeds (including battery specs seed)
    4. battery_specs has 23 rows with correct data
    5. is_active and source_type columns work correctly
    """
    base_url = os.environ.get("TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("TEST_DATABASE_URL not set (PostgreSQL required)")
    
    # Create a temporary database for this test
    url = make_url(base_url)
    admin_db_url = url.set(database="postgres")
    test_db_name = "scantest_upgrade_test"
    
    # Create test database
    admin_engine = create_engine(admin_db_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as admin_conn:
        admin_conn.execute(text(f"DROP DATABASE IF EXISTS {test_db_name}"))
        admin_conn.execute(text(f"CREATE DATABASE {test_db_name}"))
    admin_engine.dispose()
    
    # Use the test database
    db_url = url.set(database=test_db_name).render_as_string(hide_password=False)
    
    # Set environment variable so migrations use the correct database
    old_db_url = os.environ.get("TEST_MIGRATION_DATABASE_URL")
    os.environ["TEST_MIGRATION_DATABASE_URL"] = db_url
    
    try:
        engine = create_engine(db_url)
        app = create_app("testing")
        
        with app.app_context():
            config = Config("migrations/alembic.ini")
            config.set_main_option("script_location", "migrations")
            config.set_main_option("sqlalchemy.url", db_url)
            
            # Step 1: Upgrade from base to d7a3e8f6b2c9 (classification migration)
            command.upgrade(config, "d7a3e8f6b2c9")
            
            # Step 2: Insert some definition data
            conn = engine.connect()
            
            conn.execute(text("""
                INSERT INTO definition_sources (id, source_type, file_path, sha256, file_size, imported_at)
                VALUES 
                (9001, 'dbc', 'test/upgrade_test.dbc', '0123456789abcdef' || repeat('0', 48), 1024, CURRENT_TIMESTAMP)
            """))
            
            conn.execute(text("""
                INSERT INTO vehicle_definitions (id, source_id, maker, model, year_from, created_at)
                VALUES (9001, 9001, 'Hyundai', 'IONIQ 5', 2021, CURRENT_TIMESTAMP)
            """))
            
            conn.commit()
            
            # Step 3: Upgrade to head (includes battery specs seed)
            command.upgrade(config, "head")
            
            # Step 4: Verify battery_specs has 23 rows
            result = conn.execute(text("SELECT COUNT(*) FROM battery_specs"))
            count = result.scalar()
            assert count == 23, f"Expected 23 battery specs, got {count}"
            
            # Step 5: Verify source_url and source_type for IONIQ 5 Standard Range
            result = conn.execute(text("""
                SELECT cell_chemistry, cell_count, cell_config, source_url, source_note, source_type, is_active
                FROM battery_specs
                WHERE maker = 'Hyundai' AND model = 'IONIQ 5' AND trim_grade = 'Standard Range'
            """))
            row = result.fetchone()
            assert row is not None, "IONIQ 5 Standard Range not found"
            
            # Debug: print what we got
            print(f"\nDEBUG - IONIQ 5 Standard Range data:")
            print(f"  cell_chemistry: {row[0]}")
            print(f"  cell_count: {row[1]}")
            print(f"  cell_config: {row[2]}")
            print(f"  source_url: {row[3]}")
            print(f"  source_note: {row[4]}")
            print(f"  source_type: {row[5]}")
            print(f"  is_active: {row[6]}")
            
            # Verify columns are correctly mapped (not shifted)
            assert row[0] == 'NMC', f"cell_chemistry should be 'NMC', got: {row[0]}"
            assert row[1] == 288, f"cell_count should be 288, got: {row[1]}"
            assert row[2] == '144s2p', f"cell_config should be '144s2p', got: {row[2]}"
            assert 'hyundai.com' in row[3], f"source_url should contain hyundai.com, got: {row[3]}"
            assert 'newsroom' in row[4] or 'Official' in row[4], f"source_note should mention newsroom/Official, got: {row[4]}"
            assert row[5] == 'manufacturer', f"source_type should be 'manufacturer', got: {row[5]}"
            assert row[6] is True, f"is_active should be True, got: {row[6]}"
            
            # Step 6: Verify is_active semantics work
            # Update one row to inactive
            conn.execute(text("""
                UPDATE battery_specs 
                SET is_active = FALSE 
                WHERE maker = 'Hyundai' AND model = 'IONIQ 5' AND trim_grade = 'Long Range'
            """))
            conn.commit()
            
            # Verify active/inactive counts
            result = conn.execute(text("""
                SELECT 
                    COUNT(*) FILTER (WHERE is_active = TRUE) as active_count,
                    COUNT(*) FILTER (WHERE is_active = FALSE) as inactive_count
                FROM battery_specs
            """))
            active_count, inactive_count = result.fetchone()
            assert active_count == 22, f"Expected 22 active specs, got {active_count}"
            assert inactive_count == 1, f"Expected 1 inactive spec, got {inactive_count}"
            
            # Step 7: Verify our test vehicle definition still exists
            result = conn.execute(text("""
                SELECT COUNT(*) FROM vehicle_definitions WHERE id = 9001
            """))
            assert result.scalar() == 1, "Test vehicle definition should still exist"
            
            conn.close()
            
            # Close all connections
            db.session.remove()
            db.engine.dispose()
        
        engine.dispose()
    finally:
        if old_db_url:
            os.environ["TEST_MIGRATION_DATABASE_URL"] = old_db_url
        elif "TEST_MIGRATION_DATABASE_URL" in os.environ:
            del os.environ["TEST_MIGRATION_DATABASE_URL"]
    
    # Terminate connections and drop test database
    admin_engine = create_engine(admin_db_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as admin_conn:
        admin_conn.execute(text(f"""
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = '{test_db_name}'
            AND pid <> pg_backend_pid()
        """))
        admin_conn.execute(text(f"DROP DATABASE IF EXISTS {test_db_name}"))
    admin_engine.dispose()
