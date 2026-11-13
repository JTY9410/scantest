"""Test powertrain classification migration c075a656c25f."""
import pytest
import os
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from alembic import command
from alembic.config import Config

from app import create_app


def test_powertrain_classification_real_samples():
    """Test powertrain classification with real-world samples."""
    base_url = os.environ.get("TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("TEST_DATABASE_URL not set (PostgreSQL required)")
    
    url = make_url(base_url)
    admin_db_url = url.set(database="postgres")
    test_db_name = f"scantest_powertrain_test_{os.getpid()}"
    
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
            
            # Upgrade to the revision just before our new migration
            command.upgrade(config, "202f1f3d61e5")
            
            # Insert test data with real-world samples
            conn = engine.connect()
            
            # Insert definition sources
            conn.execute(text("""
                INSERT INTO definition_sources (id, source_type, file_path, sha256, file_size, imported_at)
                VALUES
                (1, 'obdb', '02_OBDb_진단정의/Chevrolet/Bolt-EV/default.json', 'a'||repeat('0', 63), 1000, CURRENT_TIMESTAMP),
                (2, 'dbc', '01_DBC/Tesla/tesla_powertrain_final.dbc', 'b'||repeat('0', 63), 2000, CURRENT_TIMESTAMP),
                (3, 'dbc', '01_DBC/Tesla/Model3CAN_final.dbc', 'c'||repeat('0', 63), 3000, CURRENT_TIMESTAMP),
                (4, 'dbc', '01_DBC/BYD/byd_tang_phev_2015_final.dbc', 'd'||repeat('0', 63), 4000, CURRENT_TIMESTAMP),
                (5, 'obdb', '02_OBDb_진단정의/Jeep/Wrangler-4xe/default.json', 'e'||repeat('0', 63), 5000, CURRENT_TIMESTAMP),
                (6, 'obdb', '02_OBDb_진단정의/Citroen/eC4-X/default.json', 'f'||repeat('0', 63), 6000, CURRENT_TIMESTAMP),
                (7, 'wican', '03_WiCAN_PID/Citroen/Citroen_ C-Zero/profile.json', 'g'||repeat('0', 63), 7000, CURRENT_TIMESTAMP),
                (8, 'wican', '03_WiCAN_PID/Smart/Smart_ #1/profile.json', 'h'||repeat('0', 63), 8000, CURRENT_TIMESTAMP),
                (9, 'torque', '04_Torque_PID/Ray EV/extendedpids/Kia_Ray_EV_Extra_gauges.csv', 'i'||repeat('0', 63), 9000, CURRENT_TIMESTAMP),
                (10, 'dbc', '01_DBC/_ECU_장비_프로토콜/BOSCH/ms43.dbc', 'j'||repeat('0', 63), 10000, CURRENT_TIMESTAMP),
                (11, 'dbc', '01_DBC/_공통_프로토콜/OBD2/obd2.dbc', 'k'||repeat('0', 63), 11000, CURRENT_TIMESTAMP),
                (12, 'obdb', '02_OBDb_진단정의/Hyundai/IONIQ 5/default.json', 'l'||repeat('0', 63), 12000, CURRENT_TIMESTAMP),
                (13, 'obdb', '02_OBDb_진단정의/Nissan/Leaf/default.json', 'm'||repeat('0', 63), 13000, CURRENT_TIMESTAMP),
                (14, 'obdb', '02_OBDb_진단정의/Porsche/Taycan/default.json', 'n'||repeat('0', 63), 14000, CURRENT_TIMESTAMP),
                (15, 'obdb', '02_OBDb_진단정의/BMW/i3/default.json', 'o'||repeat('0', 63), 15000, CURRENT_TIMESTAMP),
                (16, 'obdb', '02_OBDb_진단정의/VW/ID.4/default.json', 'p'||repeat('0', 63), 16000, CURRENT_TIMESTAMP),
                (17, 'obdb', '02_OBDb_진단정의/Hyundai/Tucson/default.json', 'q'||repeat('0', 63), 17000, CURRENT_TIMESTAMP),
                (18, 'obdb', '02_OBDb_진단정의/Toyota/Prius/default.json', 'r'||repeat('0', 63), 18000, CURRENT_TIMESTAMP),
                (19, 'dbc', '01_DBC/Polestar/polestar_2.dbc', 's'||repeat('0', 63), 19000, CURRENT_TIMESTAMP),
                (20, 'dbc', '01_DBC/_ECU_장비_프로토콜/MARELLI/marelli_ecu.dbc', 't'||repeat('0', 63), 20000, CURRENT_TIMESTAMP)
            """))
            
            # Insert vehicle definitions with unknown powertrain
            conn.execute(text("""
                INSERT INTO vehicle_definitions (source_id, maker, model, submodel, powertrain, year_from, created_at)
                VALUES
                (1, 'Chevrolet', 'Bolt-EV', NULL, 'unknown', 2017, CURRENT_TIMESTAMP),
                (2, 'Tesla', NULL, NULL, 'unknown', 2012, CURRENT_TIMESTAMP),
                (3, 'Tesla', 'Model 3', NULL, 'unknown', 2017, CURRENT_TIMESTAMP),
                (4, 'BYD', NULL, NULL, 'unknown', 2015, CURRENT_TIMESTAMP),
                (5, 'Jeep', 'Wrangler-4xe', NULL, 'unknown', 2021, CURRENT_TIMESTAMP),
                (6, 'Citroen', 'eC4-X', NULL, 'unknown', 2022, CURRENT_TIMESTAMP),
                (7, 'Citroen', 'C-Zero', 'Citroen: C-Zero', 'unknown', 2010, CURRENT_TIMESTAMP),
                (8, 'Smart', '#1', 'Smart: #1', 'unknown', 2023, CURRENT_TIMESTAMP),
                (9, NULL, 'extendedpids', NULL, 'unknown', 2020, CURRENT_TIMESTAMP),
                (10, 'BOSCH', NULL, NULL, 'unknown', 2000, CURRENT_TIMESTAMP),
                (11, NULL, 'OBD2', NULL, 'unknown', 2000, CURRENT_TIMESTAMP),
                (12, 'Hyundai', 'IONIQ 5', NULL, 'unknown', 2021, CURRENT_TIMESTAMP),
                (13, 'Nissan', 'Leaf', NULL, 'unknown', 2010, CURRENT_TIMESTAMP),
                (14, 'Porsche', 'Taycan', NULL, 'unknown', 2020, CURRENT_TIMESTAMP),
                (15, 'BMW', 'i3', NULL, 'unknown', 2013, CURRENT_TIMESTAMP),
                (16, 'VW', 'ID.4', NULL, 'unknown', 2021, CURRENT_TIMESTAMP),
                (17, 'Hyundai', 'Tucson', NULL, 'unknown', 2015, CURRENT_TIMESTAMP),
                (18, 'Toyota', 'Prius', NULL, 'unknown', 1997, CURRENT_TIMESTAMP),
                (19, 'Polestar', '2', NULL, 'unknown', 2020, CURRENT_TIMESTAMP),
                (20, 'MARELLI', NULL, NULL, 'unknown', 2000, CURRENT_TIMESTAMP)
            """))
            
            conn.commit()
            
            # Now upgrade to our new migration
            command.upgrade(config, "c075a656c25f")
            
            # Verify classifications
            
            # BEV vehicles
            result = conn.execute(text("""
                SELECT maker, model FROM vehicle_definitions WHERE powertrain = 'BEV' ORDER BY id
            """))
            bev_vehicles = result.fetchall()
            
            # Should classify as BEV: Bolt-EV, Tesla models, eC4, C-Zero, Smart #1, IONIQ 5, Leaf, Taycan, i3, ID.4, Polestar
            assert len(bev_vehicles) >= 11, f"Expected at least 11 BEV vehicles, got {len(bev_vehicles)}: {bev_vehicles}"
            
            makers_models = [(row[0], row[1]) for row in bev_vehicles]
            assert ('Chevrolet', 'Bolt-EV') in makers_models
            assert ('Tesla', 'Model 3') in makers_models
            assert ('Citroen', 'eC4-X') in makers_models
            assert ('Citroen', 'C-Zero') in makers_models
            assert ('Smart', '#1') in makers_models
            assert ('Hyundai', 'IONIQ 5') in makers_models
            assert ('Nissan', 'Leaf') in makers_models
            assert ('Porsche', 'Taycan') in makers_models
            assert ('BMW', 'i3') in makers_models
            assert ('VW', 'ID.4') in makers_models
            assert ('Polestar', '2') in makers_models
            
            # PHEV vehicles
            result = conn.execute(text("""
                SELECT maker, model FROM vehicle_definitions WHERE powertrain = 'PHEV' ORDER BY id
            """))
            phev_vehicles = result.fetchall()
            
            # Should classify as PHEV: BYD Tang (from file path), Wrangler-4xe
            assert len(phev_vehicles) >= 2, f"Expected at least 2 PHEV vehicles, got {len(phev_vehicles)}: {phev_vehicles}"
            
            makers_models = [(row[0], row[1]) for row in phev_vehicles]
            assert ('Jeep', 'Wrangler-4xe') in makers_models
            assert ('BYD', None) in makers_models  # BYD Tang from file path
            
            # HEV vehicles
            result = conn.execute(text("""
                SELECT maker, model FROM vehicle_definitions WHERE powertrain = 'HEV' ORDER BY id
            """))
            hev_vehicles = result.fetchall()
            
            # Should classify as HEV: Prius
            assert len(hev_vehicles) >= 1, f"Expected at least 1 HEV vehicle, got {len(hev_vehicles)}: {hev_vehicles}"
            makers_models = [(row[0], row[1]) for row in hev_vehicles]
            assert ('Toyota', 'Prius') in makers_models
            
            # not_vehicle
            result = conn.execute(text("""
                SELECT maker, model FROM vehicle_definitions WHERE powertrain = 'not_vehicle' ORDER BY id
            """))
            not_vehicles = result.fetchall()
            
            # Should classify as not_vehicle: BOSCH, MARELLI, OBD2
            assert len(not_vehicles) >= 2, f"Expected at least 2 not_vehicle entries, got {len(not_vehicles)}: {not_vehicles}"
            makers = [row[0] for row in not_vehicles]
            assert 'BOSCH' in makers
            assert 'MARELLI' in makers
            
            # unknown (ambiguous cases like Tucson, Ray EV extendedpids)
            result = conn.execute(text("""
                SELECT maker, model FROM vehicle_definitions WHERE powertrain = 'unknown' ORDER BY id
            """))
            unknown_vehicles = result.fetchall()
            
            # Tucson should stay unknown (no clear evidence)
            makers_models = [(row[0], row[1]) for row in unknown_vehicles]
            assert ('Hyundai', 'Tucson') in makers_models, f"Tucson should remain unknown, got: {unknown_vehicles}"
            
            conn.close()
        
        # Dispose engine and wait for connections to close
        engine.dispose()
        
        # Force disconnect all sessions before dropping
        admin_engine = create_engine(admin_db_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as admin_conn:
            admin_conn.execute(text(f"""
                SELECT pg_terminate_backend(pid) 
                FROM pg_stat_activity 
                WHERE datname = '{test_db_name}' AND pid <> pg_backend_pid()
            """))
        admin_engine.dispose()
    
    finally:
        # Restore original environment
        if old_db_url is not None:
            os.environ["TEST_MIGRATION_DATABASE_URL"] = old_db_url
        elif "TEST_MIGRATION_DATABASE_URL" in os.environ:
            del os.environ["TEST_MIGRATION_DATABASE_URL"]
        
        # Cleanup database
        admin_engine = create_engine(admin_db_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as admin_conn:
            admin_conn.execute(text(f"DROP DATABASE IF EXISTS {test_db_name}"))
        admin_engine.dispose()
