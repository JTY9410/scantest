"""정의 데이터 분류 컬럼 추가 및 백필.

Revision ID: d7a3e8f6b2c9
Revises: c9f8d4e5a3b7
Create Date: 2026-11-13 12:37:38

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7a3e8f6b2c9'
down_revision = 'c9f8d4e5a3b7'
branch_labels = None
depends_on = None


def upgrade():
    # VehicleDefinition에 powertrain 추가
    op.add_column('vehicle_definitions', sa.Column('powertrain', sa.String(20), nullable=True))
    
    # DbcSignal에 분류 컬럼 추가
    op.add_column('dbc_signals', sa.Column('protocol', sa.String(20), nullable=True))
    op.add_column('dbc_signals', sa.Column('ecu_module', sa.String(50), nullable=True))
    op.add_column('dbc_signals', sa.Column('signal_category', sa.String(30), nullable=True))
    
    # DiagnosticCommand에 분류 컬럼 추가
    op.add_column('diagnostic_commands', sa.Column('protocol', sa.String(20), nullable=True))
    op.add_column('diagnostic_commands', sa.Column('ecu_module', sa.String(50), nullable=True))
    
    # 인덱스 추가
    op.create_index('ix_vehicle_definitions_powertrain', 'vehicle_definitions', ['powertrain'])
    op.create_index('ix_dbc_signals_protocol', 'dbc_signals', ['protocol'])
    op.create_index('ix_dbc_signals_ecu_module', 'dbc_signals', ['ecu_module'])
    op.create_index('ix_dbc_signals_signal_category', 'dbc_signals', ['signal_category'])
    op.create_index('ix_diagnostic_commands_protocol', 'diagnostic_commands', ['protocol'])
    op.create_index('ix_diagnostic_commands_ecu_module', 'diagnostic_commands', ['ecu_module'])
    
    # 백필 (deterministic rules)
    # 1. Powertrain from model names
    op.execute("""
        UPDATE vehicle_definitions
        SET powertrain = CASE
            WHEN model ILIKE '%EV%' OR model ILIKE '%ioniq%' OR model ILIKE '%kona electric%' 
                OR model ILIKE '%niro ev%' OR model ILIKE '%soul ev%' THEN 'BEV'
            WHEN model ILIKE '%plug%' OR model ILIKE '%phev%' THEN 'PHEV'
            WHEN model ILIKE '%hybrid%' OR model ILIKE '%hev%' THEN 'HEV'
            ELSE 'ICE'
        END
        WHERE powertrain IS NULL
    """)
    
    # 2. Protocol from source type or file path
    op.execute("""
        UPDATE dbc_signals
        SET protocol = CASE
            WHEN EXISTS (
                SELECT 1 FROM definition_sources ds 
                WHERE ds.id = dbc_signals.source_id 
                AND (ds.source_type = 'dbc' OR ds.file_path LIKE '%.dbc')
            ) THEN 'CAN'
            ELSE 'CAN'
        END
        WHERE protocol IS NULL
    """)
    
    op.execute("""
        UPDATE diagnostic_commands
        SET protocol = CASE
            WHEN service_id IN ('01', '02', '09') THEN 'OBD-II'
            WHEN service_id IN ('10', '11', '14', '19', '22', '27', '2E', '31', '3E') THEN 'UDS'
            WHEN service_id IN ('21', '22', '23', '24') AND mode IS NOT NULL THEN 'KWP2000'
            ELSE 'UDS'
        END
        WHERE protocol IS NULL
    """)
    
    # 3. ECU module from signal/command name patterns
    op.execute("""
        UPDATE dbc_signals
        SET ecu_module = CASE
            WHEN signal_name ILIKE '%bms%' OR signal_name ILIKE '%battery%' OR signal_name ILIKE '%soc%' OR signal_name ILIKE '%soh%' THEN 'BMS'
            WHEN signal_name ILIKE '%motor%' OR signal_name ILIKE '%inverter%' OR signal_name ILIKE '%mccu%' THEN 'MCU'
            WHEN signal_name ILIKE '%obc%' OR signal_name ILIKE '%charger%' OR signal_name ILIKE '%charge%' THEN 'OBC'
            WHEN signal_name ILIKE '%vcu%' OR signal_name ILIKE '%vehicle%' THEN 'VCU'
            WHEN signal_name ILIKE '%cluster%' OR signal_name ILIKE '%dashboard%' THEN 'CLUSTER'
            WHEN signal_name ILIKE '%bcm%' OR signal_name ILIKE '%body%' THEN 'BCM'
            WHEN signal_name ILIKE '%abs%' OR signal_name ILIKE '%brake%' THEN 'ABS'
            ELSE 'UNKNOWN'
        END
        WHERE ecu_module IS NULL
    """)
    
    op.execute("""
        UPDATE diagnostic_commands
        SET ecu_module = CASE
            WHEN unit_name ILIKE '%bms%' OR unit_name ILIKE '%battery%' THEN 'BMS'
            WHEN unit_name ILIKE '%motor%' OR unit_name ILIKE '%mcu%' THEN 'MCU'
            WHEN unit_name ILIKE '%charger%' OR unit_name ILIKE '%obc%' THEN 'OBC'
            WHEN unit_name ILIKE '%vcu%' OR unit_name ILIKE '%vehicle%' THEN 'VCU'
            WHEN unit_name ILIKE '%ecm%' OR unit_name ILIKE '%engine%' THEN 'ECM'
            WHEN unit_name ILIKE '%tcm%' OR unit_name ILIKE '%transmission%' THEN 'TCM'
            ELSE 'UNKNOWN'
        END
        WHERE ecu_module IS NULL
    """)
    
    # 4. Signal category from signal name keywords
    op.execute("""
        UPDATE dbc_signals
        SET signal_category = CASE
            WHEN signal_name ILIKE '%soc%' OR signal_name ILIKE '%state%charge%' THEN 'battery_soc'
            WHEN signal_name ILIKE '%soh%' OR signal_name ILIKE '%state%health%' THEN 'battery_soh'
            WHEN signal_name ILIKE '%voltage%' OR signal_name ILIKE '%volt%' THEN 'battery_voltage'
            WHEN signal_name ILIKE '%current%' OR signal_name ILIKE '%ampere%' THEN 'battery_current'
            WHEN signal_name ILIKE '%temp%' OR signal_name ILIKE '%temperature%' THEN 'temperature'
            WHEN signal_name ILIKE '%cell%' AND (signal_name ILIKE '%volt%' OR signal_name ILIKE '%voltage%') THEN 'cell_voltage'
            WHEN signal_name ILIKE '%charge%' AND signal_name ILIKE '%power%' THEN 'charging_power'
            WHEN signal_name ILIKE '%dtc%' OR signal_name ILIKE '%fault%' OR signal_name ILIKE '%error%' THEN 'dtc'
            WHEN signal_name ILIKE '%speed%' OR signal_name ILIKE '%velocity%' THEN 'drive_speed'
            WHEN signal_name ILIKE '%torque%' THEN 'drive_torque'
            WHEN signal_name ILIKE '%power%' AND NOT signal_name ILIKE '%charge%' THEN 'drive_power'
            ELSE 'other'
        END
        WHERE signal_category IS NULL
    """)


def downgrade():
    op.drop_index('ix_diagnostic_commands_ecu_module', table_name='diagnostic_commands')
    op.drop_index('ix_diagnostic_commands_protocol', table_name='diagnostic_commands')
    op.drop_index('ix_dbc_signals_signal_category', table_name='dbc_signals')
    op.drop_index('ix_dbc_signals_ecu_module', table_name='dbc_signals')
    op.drop_index('ix_dbc_signals_protocol', table_name='dbc_signals')
    op.drop_index('ix_vehicle_definitions_powertrain', table_name='vehicle_definitions')
    
    op.drop_column('diagnostic_commands', 'ecu_module')
    op.drop_column('diagnostic_commands', 'protocol')
    op.drop_column('dbc_signals', 'signal_category')
    op.drop_column('dbc_signals', 'ecu_module')
    op.drop_column('dbc_signals', 'protocol')
    op.drop_column('vehicle_definitions', 'powertrain')
