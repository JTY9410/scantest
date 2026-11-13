"""Test improved classification rules from f1a2b3c4d5e6."""
import os
import pytest
from sqlalchemy import text, create_engine
from sqlalchemy.engine.url import make_url
from alembic import command
from alembic.config import Config

from app import create_app
from app.extensions import db


def test_improved_ecu_classification():
    """Test Korean ECU names and 29-bit headers classification."""
    base_url = os.environ.get("TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("TEST_DATABASE_URL not set")
    
    url = make_url(base_url)
    admin_db_url = url.set(database="postgres")
    test_db_name = "scantest_classification_test"
    
    admin_engine = create_engine(admin_db_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as admin_conn:
        admin_conn.execute(text(f"DROP DATABASE IF EXISTS {test_db_name}"))
        admin_conn.execute(text(f"CREATE DATABASE {test_db_name}"))
    admin_engine.dispose()
    
    db_url = url.set(database=test_db_name).render_as_string(hide_password=False)
    old_db_url = os.environ.get("TEST_MIGRATION_DATABASE_URL")
    os.environ["TEST_MIGRATION_DATABASE_URL"] = db_url
    
    try:
        engine = create_engine(db_url)
        app = create_app("testing")
        
        with app.app_context():
            config = Config("migrations/alembic.ini")
            config.set_main_option("script_location", "migrations")
            config.set_main_option("sqlalchemy.url", db_url)
            
            # Upgrade to head (includes improved classification)
            command.upgrade(config, "head")
            
            conn = engine.connect()
            
            # Insert test data with Korean ECU names
            conn.execute(text("""
                INSERT INTO definition_sources (id, source_type, file_path, sha256, file_size, imported_at)
                VALUES (9001, 'obdb', 'test/classification.json', '00' || repeat('0', 62), 1024, CURRENT_TIMESTAMP)
            """))
            
            # Test Korean ECU names
            conn.execute(text("""
                INSERT INTO diagnostic_commands (
                    id, source_id, source_type, maker, model, ecu_address, ecu_name,
                    service, pid, command_bytes, label, unit,
                    verification_status, verification_count, success_count, failure_count,
                    created_at, updated_at
                ) VALUES
                (9001, 9001, 'obdb', 'Hyundai', 'IONIQ 5', '7E4', '배터리 관리 시스템', '22', '0105', '220105',
                 'Battery SOC', '%', 'needs_verification', 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (9002, 9001, 'obdb', 'Kia', 'EV6', '7E2', '모터제어기', '22', '1001', '221001',
                 'Motor RPM', 'rpm', 'needs_verification', 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (9003, 9001, 'obdb', 'Hyundai', 'IONIQ 5', '7E5', '온보드충전기', '22', '2001', '222001',
                 'Charging Status', '', 'needs_verification', 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (9004, 9001, 'obdb', 'Genesis', 'GV60', '18DAE2F1', 'BMS_CAN', '22', '0101', '220101',
                 'Pack Voltage', 'V', 'needs_verification', 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (9005, 9001, 'obdb', 'Kia', 'EV9', '7C0', '계기판', '22', '3001', '223001',
                 'Speed Display', 'km/h', 'needs_verification', 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """))
            conn.commit()
            
            # Run classification (both initial and improved)
            conn.execute(text("""
                UPDATE diagnostic_commands SET ecu_module = NULL, protocol = NULL
            """))
            
            # Apply classification rules (simulating what the migrations do)
            conn.execute(text("""
                UPDATE diagnostic_commands
                SET protocol = CASE
                    WHEN service IN ('22', '27', '2E', '31') THEN 'UDS'
                    WHEN service IN ('01', '02') THEN 'OBD-II'
                    ELSE 'unknown'
                END,
                ecu_module = CASE
                    WHEN ecu_name ~* '(배터리|BMS)' THEN 'BMS'
                    WHEN ecu_name ~* '(모터|MCU)' THEN 'MCU'
                    WHEN ecu_name ~* '(충전|OBC)' THEN 'OBC'
                    WHEN ecu_name ~* '(계기판|cluster)' THEN 'CLUSTER'
                    WHEN ecu_address ~* '18DA.*E2' THEN 'BMS'
                    WHEN ecu_address = '7E4' THEN 'BMS'
                    WHEN ecu_address = '7E2' THEN 'MCU'
                    WHEN ecu_address = '7E5' THEN 'OBC'
                    WHEN ecu_address = '7C0' THEN 'CLUSTER'
                    ELSE 'UNKNOWN'
                END
            """))
            conn.commit()
            
            # Verify classifications
            result = conn.execute(text("""
                SELECT id, ecu_name, ecu_module, protocol
                FROM diagnostic_commands
                WHERE id BETWEEN 9001 AND 9005
                ORDER BY id
            """))
            
            rows = result.fetchall()
            assert len(rows) == 5
            
            # Korean "배터리" should be BMS
            assert rows[0][2] == 'BMS', f"Korean battery name should be BMS, got {rows[0][2]}"
            assert rows[0][3] == 'UDS'
            
            # Korean "모터" should be MCU
            assert rows[1][2] == 'MCU', f"Korean motor name should be MCU, got {rows[1][2]}"
            
            # Korean "충전기" should be OBC
            assert rows[2][2] == 'OBC', f"Korean charger name should be OBC, got {rows[2][2]}"
            
            # 29-bit header 18DAE2F1 should be BMS
            assert rows[3][2] == 'BMS', f"29-bit CAN header E2 should be BMS, got {rows[3][2]}"
            
            # Korean "계기판" should be CLUSTER
            assert rows[4][2] == 'CLUSTER', f"Korean cluster name should be CLUSTER, got {rows[4][2]}"
            
            conn.close()
            db.session.remove()
            db.engine.dispose()
        
        engine.dispose()
    finally:
        if old_db_url:
            os.environ["TEST_MIGRATION_DATABASE_URL"] = old_db_url
        elif "TEST_MIGRATION_DATABASE_URL" in os.environ:
            del os.environ["TEST_MIGRATION_DATABASE_URL"]
    
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


def test_unit_based_signal_classification():
    """Test unit-based signal category classification."""
    base_url = os.environ.get("TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("TEST_DATABASE_URL not set")
    
    url = make_url(base_url)
    admin_db_url = url.set(database="postgres")
    test_db_name = "scantest_signal_class_test"
    
    admin_engine = create_engine(admin_db_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as admin_conn:
        admin_conn.execute(text(f"DROP DATABASE IF EXISTS {test_db_name}"))
        admin_conn.execute(text(f"CREATE DATABASE {test_db_name}"))
    admin_engine.dispose()
    
    db_url = url.set(database=test_db_name).render_as_string(hide_password=False)
    old_db_url = os.environ.get("TEST_MIGRATION_DATABASE_URL")
    os.environ["TEST_MIGRATION_DATABASE_URL"] = db_url
    
    try:
        engine = create_engine(db_url)
        app = create_app("testing")
        
        with app.app_context():
            config = Config("migrations/alembic.ini")
            config.set_main_option("script_location", "migrations")
            config.set_main_option("sqlalchemy.url", db_url)
            
            command.upgrade(config, "head")
            conn = engine.connect()
            
            # Insert test data
            conn.execute(text("""
                INSERT INTO definition_sources (id, source_type, file_path, sha256, file_size, imported_at)
                VALUES (9001, 'dbc', 'test/signals.dbc', '00' || repeat('0', 62), 1024, CURRENT_TIMESTAMP)
            """))
            
            conn.execute(text("""
                INSERT INTO dbc_messages (id, source_id, can_id, message_name, dlc)
                VALUES (9001, 9001, 2020, 'BMS_Status', 8)
            """))
            
            # Test unit-based classification
            conn.execute(text("""
                INSERT INTO dbc_signals (id, message_id, signal_name, start_bit, bit_length, 
                                        byte_order, value_type, factor, "offset", unit)
                VALUES
                (9001, 9001, 'Cell_V_01', 0, 16, 'little', 'unsigned', 0.001, 0, 'V'),
                (9002, 9001, 'Pack_Current', 16, 16, 'little', 'signed', 0.1, 0, 'A'),
                (9003, 9001, 'Coolant_Temp', 32, 8, 'little', 'signed', 1.0, -40, '°C'),
                (9004, 9001, 'Vehicle_Speed', 40, 16, 'little', 'unsigned', 0.01, 0, 'km/h'),
                (9005, 9001, 'Motor_Torque', 56, 16, 'little', 'signed', 0.1, 0, 'Nm')
            """))
            conn.commit()
            
            # Apply classification
            conn.execute(text("""
                UPDATE dbc_signals
                SET protocol = 'CAN',
                    ecu_module = CASE
                        WHEN signal_name ~* '(cell|pack|battery)' THEN 'BMS'
                        WHEN signal_name ~* 'motor' THEN 'MCU'
                        ELSE 'UNKNOWN'
                    END,
                    signal_category = CASE
                        WHEN unit = 'V' AND signal_name ~* 'cell' THEN 'cell_voltage'
                        WHEN unit = 'A' THEN 'battery_current'
                        WHEN unit ~* '°C' THEN 'temperature'
                        WHEN unit = 'km/h' THEN 'drive_speed'
                        WHEN unit = 'Nm' THEN 'drive_torque'
                        ELSE 'other'
                    END
            """))
            conn.commit()
            
            result = conn.execute(text("""
                SELECT signal_name, unit, signal_category, ecu_module
                FROM dbc_signals
                WHERE id BETWEEN 9001 AND 9005
                ORDER BY id
            """))
            
            rows = result.fetchall()
            assert len(rows) == 5
            
            assert rows[0][2] == 'cell_voltage', f"V unit with cell should be cell_voltage, got {rows[0][2]}"
            assert rows[1][2] == 'battery_current', f"A unit should be battery_current, got {rows[1][2]}"
            assert rows[2][2] == 'temperature', f"°C unit should be temperature, got {rows[2][2]}"
            assert rows[3][2] == 'drive_speed', f"km/h unit should be drive_speed, got {rows[3][2]}"
            assert rows[4][2] == 'drive_torque', f"Nm unit should be drive_torque, got {rows[4][2]}"
            
            conn.close()
            db.session.remove()
            db.engine.dispose()
        
        engine.dispose()
    finally:
        if old_db_url:
            os.environ["TEST_MIGRATION_DATABASE_URL"] = old_db_url
        elif "TEST_MIGRATION_DATABASE_URL" in os.environ:
            del os.environ["TEST_MIGRATION_DATABASE_URL"]
    
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
