"""Classification migration backfill test."""
import pytest
from sqlalchemy import text, create_engine
from alembic import command
from alembic.config import Config

from app import create_app
from app.extensions import db


@pytest.fixture(scope="module")
def alembic_config():
    """Alembic config for migrations."""
    config = Config("migrations/alembic.ini")
    config.set_main_option("script_location", "migrations")
    return config


def test_classification_migration_backfill(tmp_path):
    """Test classification migration with representative data.
    
    1. Create DB at e24341200b29
    2. Insert representative rows
    3. Upgrade to head (d7a3e8f6b2c9)
    4. Check backfilled classifications
    5. Downgrade
    """
    # Create temporary test database
    db_path = tmp_path / "test_migration.db"
    db_url = f"sqlite:///{db_path}"
    
    # Create engine and run migrations to e24341200b29
    engine = create_engine(db_url)
    
    app = create_app("testing")
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    
    with app.app_context():
        # Create tables up to e24341200b29
        from alembic.runtime.migration import MigrationContext
        from alembic.operations import Operations
        
        conn = engine.connect()
        ctx = MigrationContext.configure(conn)
        op = Operations(ctx)
        
        # Run upgrade to e24341200b29
        config = Config("migrations/alembic.ini")
        config.set_main_option("script_location", "migrations")
        config.set_main_option("sqlalchemy.url", db_url)
        
        command.upgrade(config, "e24341200b29")
        
        # Insert representative data
        conn.execute(text("""
            INSERT INTO definition_sources (id, source_type, file_path, sha256, file_size, imported_at)
            VALUES 
            (1, 'dbc', 'hyundai/egmp_can.dbc', '0123456789abcdef' || repeat('0', 48), 1024, CURRENT_TIMESTAMP),
            (2, 'obdb', 'hyundai/ioniq5_pids.json', '1234567890abcdef' || repeat('0', 48), 2048, CURRENT_TIMESTAMP),
            (3, 'wican', 'kia/ev6_commands.json', '234567890abcdef0' || repeat('0', 48), 1536, CURRENT_TIMESTAMP)
        """))
        
        conn.execute(text("""
            INSERT INTO vehicle_definitions (id, source_id, maker, model, year_from, created_at)
            VALUES
            (1, 1, 'Hyundai', 'IONIQ 6', 2023, CURRENT_TIMESTAMP),
            (2, 1, 'Hyundai', 'TUCSON HYBRID', 2022, CURRENT_TIMESTAMP),
            (3, 1, 'Kia', 'EV6', 2022, CURRENT_TIMESTAMP),
            (4, 1, 'Tesla', 'MODEL 3', 2023, CURRENT_TIMESTAMP),
            (5, 1, 'Hyundai', 'SONATA PLUG-IN', 2021, CURRENT_TIMESTAMP),
            (6, 1, 'Generic', 'UNKNOWN CAR', NULL, CURRENT_TIMESTAMP)
        """))
        
        conn.execute(text("""
            INSERT INTO dbc_messages (id, source_id, can_id, message_name, dlc)
            VALUES
            (1, 1, 2020, 'BMS_Status', 8),
            (2, 1, 2021, 'Motor_Status', 8)
        """))
        
        conn.execute(text("""
            INSERT INTO dbc_signals (id, message_id, signal_name, start_bit, bit_length, byte_order, value_type, factor, offset)
            VALUES
            (1, 1, 'Battery_SOC', 0, 16, 'little', 'unsigned', 0.1, 0),
            (2, 1, 'Battery_SOH', 16, 16, 'little', 'unsigned', 0.1, 0),
            (3, 1, 'Cell_Voltage_01', 32, 16, 'little', 'unsigned', 0.001, 0),
            (4, 1, 'Pack_Voltage', 48, 16, 'little', 'unsigned', 0.1, 0),
            (5, 2, 'Motor_Torque', 0, 16, 'little', 'signed', 0.1, 0),
            (6, 2, 'Vehicle_Speed', 16, 16, 'little', 'unsigned', 0.01, 0)
        """))
        
        conn.execute(text("""
            INSERT INTO diagnostic_commands (
                id, source_id, source_type, maker, model, ecu_address, ecu_name,
                service, pid, command_bytes, label, formula, unit,
                verification_status, verification_count, success_count, failure_count,
                created_at, updated_at
            ) VALUES
            (1, 2, 'obdb', 'Hyundai', 'IONIQ 5', '7E4', 'BMS', '22', '0105', '220105', 
             'Battery SOC', 'A*0.5', '%', 'needs_verification', 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            (2, 2, 'obdb', 'Hyundai', 'IONIQ 5', '7E4', 'BMS', '22', '0101', '220101',
             'Battery SOH', 'A', '%', 'needs_verification', 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            (3, 3, 'wican', 'Kia', 'EV6', '7E2', 'Motor Control Unit', '22', '1001', '221001',
             'Motor RPM', 'A*10', 'rpm', 'needs_verification', 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            (4, 2, 'obdb', NULL, NULL, '7DF', 'ECM', '01', '0C', '010C',
             'Engine RPM', '((A*256)+B)/4', 'rpm', 'needs_verification', 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))
        
        conn.commit()
        
        # Upgrade to head (d7a3e8f6b2c9)
        command.upgrade(config, "head")
        
        # Check backfilled classifications
        # 1. Check vehicle powertrains
        result = conn.execute(text("""
            SELECT model, powertrain FROM vehicle_definitions ORDER BY id
        """))
        powertrains = {row[0]: row[1] for row in result}
        
        assert powertrains['IONIQ 6'] == 'BEV', "IONIQ 6 should be BEV"
        assert powertrains['EV6'] == 'BEV', "EV6 should be BEV"
        assert powertrains['MODEL 3'] == 'BEV', "MODEL 3 should be BEV"
        assert powertrains['TUCSON HYBRID'] == 'HEV', "TUCSON HYBRID should be HEV"
        assert powertrains['SONATA PLUG-IN'] == 'PHEV', "SONATA PLUG-IN should be PHEV"
        assert powertrains['UNKNOWN CAR'] == 'unknown', "Unknown car should be 'unknown'"
        
        # 2. Check DBC signal classifications
        result = conn.execute(text("""
            SELECT signal_name, protocol, ecu_module, signal_category 
            FROM dbc_signals ORDER BY id
        """))
        signals = {row[0]: {'protocol': row[1], 'ecu': row[2], 'category': row[3]} for row in result}
        
        assert signals['Battery_SOC']['protocol'] == 'CAN', "All DBC signals should be CAN"
        assert signals['Battery_SOC']['ecu'] == 'BMS', "Battery_SOC should be BMS"
        assert signals['Battery_SOC']['category'] == 'battery_soc', "Battery_SOC category"
        
        assert signals['Battery_SOH']['ecu'] == 'BMS'
        assert signals['Battery_SOH']['category'] == 'battery_soh'
        
        assert signals['Cell_Voltage_01']['ecu'] == 'BMS'
        assert signals['Cell_Voltage_01']['category'] == 'cell_voltage'
        
        assert signals['Pack_Voltage']['ecu'] == 'BMS'
        assert signals['Pack_Voltage']['category'] == 'battery_voltage'
        
        assert signals['Motor_Torque']['ecu'] == 'MCU'
        assert signals['Motor_Torque']['category'] == 'drive_torque'
        
        assert signals['Vehicle_Speed']['category'] == 'drive_speed'
        
        # 3. Check diagnostic command classifications
        result = conn.execute(text("""
            SELECT label, protocol, ecu_module 
            FROM diagnostic_commands ORDER BY id
        """))
        commands = {row[0]: {'protocol': row[1], 'ecu': row[2]} for row in result}
        
        assert commands['Battery SOC']['protocol'] == 'UDS', "Service 22 should be UDS"
        assert commands['Battery SOC']['ecu'] == 'BMS', "Battery commands should be BMS"
        
        assert commands['Battery SOH']['protocol'] == 'UDS'
        assert commands['Battery SOH']['ecu'] == 'BMS'
        
        assert commands['Motor RPM']['protocol'] == 'UDS'
        assert commands['Motor RPM']['ecu'] == 'MCU', "Motor should be MCU"
        
        assert commands['Engine RPM']['protocol'] == 'OBD-II', "Service 01 should be OBD-II"
        assert commands['Engine RPM']['ecu'] == 'ECM', "Engine should be ECM"
        
        # Get classification counts
        powertrain_counts = conn.execute(text("""
            SELECT powertrain, COUNT(*) FROM vehicle_definitions GROUP BY powertrain
        """)).fetchall()
        
        signal_category_counts = conn.execute(text("""
            SELECT signal_category, COUNT(*) FROM dbc_signals GROUP BY signal_category
        """)).fetchall()
        
        protocol_counts = conn.execute(text("""
            SELECT protocol, COUNT(*) FROM diagnostic_commands GROUP BY protocol
        """)).fetchall()
        
        print("\nClassification counts:")
        print("Powertrains:", dict(powertrain_counts))
        print("Signal categories:", dict(signal_category_counts))
        print("Protocols:", dict(protocol_counts))
        
        # Downgrade
        command.downgrade(config, "c9f8d4e5a3b7")
        
        # Verify columns removed
        result = conn.execute(text("PRAGMA table_info(dbc_signals)"))
        signal_columns = {row[1] for row in result}
        assert 'protocol' not in signal_columns, "protocol should be removed"
        assert 'ecu_module' not in signal_columns, "ecu_module should be removed"
        assert 'signal_category' not in signal_columns, "signal_category should be removed"
        
        conn.close()
