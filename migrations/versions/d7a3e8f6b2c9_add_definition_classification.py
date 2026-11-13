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
    # VehicleDefinition.powertrain은 이미 존재 (eea77f2e08ba에서 생성)
    
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
    
    # 백필 (deterministic rules) - REAL schema 기준
    # 1. Powertrain from model names (word boundaries)
    op.execute("""
        UPDATE vehicle_definitions
        SET powertrain = CASE
            WHEN model ~* '\\m(EV6|EV9|IONIQ 5|IONIQ 6|KONA ELECTRIC|KONA EV|NIRO EV|SOUL EV|E-GMP|GV60|GV70 ELECTRIC|ID\\.4|ID\\.3|ID\\.7|MODEL [3SXY]|LEAF|ARIYA|BOLT EV|BOLT EUV|E-TRON|TAYCAN|I-PACE|MACH-E)\\M' THEN 'BEV'
            WHEN model ~* '\\m(PLUG-?IN|PHEV|NIRO PLUG|SORENTO PLUG|SPORTAGE PLUG|TUCSON PLUG|OUTLANDER PHEV)\\M' THEN 'PHEV'
            WHEN model ~* '\\m(HYBRID|HEV|PRIUS|CAMRY HYBRID|TUCSON HYBRID|SONATA HYBRID|ACCORD HYBRID)\\M' 
                AND NOT model ~* '\\m(PLUG)\\M' THEN 'HEV'
            ELSE 'unknown'
        END
        WHERE powertrain IS NULL
    """)
    
    # 2. DBC signals are always CAN protocol
    op.execute("""
        UPDATE dbc_signals
        SET protocol = 'CAN'
        WHERE protocol IS NULL
    """)
    
    # 3. Protocol for diagnostic commands (use `service` column, not service_id)
    op.execute("""
        UPDATE diagnostic_commands
        SET protocol = CASE
            WHEN service IN ('01', '02', '03', '04', '05', '06', '07', '08', '09', '0A') THEN 'OBD-II'
            WHEN service IN ('10', '11', '14', '19', '22', '27', '2E', '2F', '31', '3E', '85') THEN 'UDS'
            WHEN service IN ('21', '23') THEN 'KWP2000'
            ELSE 'unknown'
        END
        WHERE protocol IS NULL
    """)
    
    # 4. ECU module from signal name patterns
    op.execute("""
        UPDATE dbc_signals
        SET ecu_module = CASE
            WHEN signal_name ~* '(bms|battery|pack|cell|soc|soh)' THEN 'BMS'
            WHEN signal_name ~* '(motor|inverter|mccu|mcu)' THEN 'MCU'
            WHEN signal_name ~* '(obc|charger|charge(?!_discharge))' THEN 'OBC'
            WHEN signal_name ~* '(vcu|vehicle_control)' THEN 'VCU'
            WHEN signal_name ~* '(ecm|engine)' THEN 'ECM'
            WHEN signal_name ~* '(tcm|transmission)' THEN 'TCM'
            WHEN signal_name ~* '(cluster|dashboard|display)' THEN 'CLUSTER'
            WHEN signal_name ~* '(bcm|body)' THEN 'BCM'
            WHEN signal_name ~* '(abs|brake)' THEN 'ABS'
            ELSE 'UNKNOWN'
        END
        WHERE ecu_module IS NULL
    """)
    
    # 5. ECU module from ecu_name and label (REAL columns: ecu_name, label, NOT unit_name/signal_name)
    op.execute("""
        UPDATE diagnostic_commands
        SET ecu_module = CASE
            WHEN ecu_name ~* '(bms|battery)' OR label ~* '(battery|pack|cell|soc|soh)' THEN 'BMS'
            WHEN ecu_name ~* '(motor|mcu|inverter)' OR label ~* '(motor|inverter)' THEN 'MCU'
            WHEN ecu_name ~* '(obc|charger)' OR label ~* '(charger|charging)' THEN 'OBC'
            WHEN ecu_name ~* '(vcu|vehicle)' OR label ~* '(vehicle_control)' THEN 'VCU'
            WHEN ecu_name ~* '(ecm|engine)' OR label ~* '(engine|rpm|coolant)' THEN 'ECM'
            WHEN ecu_name ~* '(tcm|transmission)' OR label ~* '(transmission|gear)' THEN 'TCM'
            WHEN ecu_name ~* '(cluster|dashboard)' THEN 'CLUSTER'
            WHEN ecu_name ~* '(bcm|body)' THEN 'BCM'
            WHEN ecu_name ~* '(abs|brake)' OR label ~* '(abs|brake)' THEN 'ABS'
            ELSE 'UNKNOWN'
        END
        WHERE ecu_module IS NULL
    """)
    
    # 6. Signal category from signal name keywords
    op.execute("""
        UPDATE dbc_signals
        SET signal_category = CASE
            WHEN signal_name ~* '\\m(soc|state.*charge)\\M' THEN 'battery_soc'
            WHEN signal_name ~* '\\m(soh|state.*health)\\M' THEN 'battery_soh'
            WHEN signal_name ~* 'cell.*volt' THEN 'cell_voltage'
            WHEN signal_name ~* '(pack|battery).*(voltage|volt)' THEN 'battery_voltage'
            WHEN signal_name ~* '(pack|battery).*(current|amp)' THEN 'battery_current'
            WHEN signal_name ~* '(temp|temperature)' THEN 'temperature'
            WHEN signal_name ~* 'charg.*power' THEN 'charging_power'
            WHEN signal_name ~* '(dtc|fault|error|warning)' THEN 'dtc'
            WHEN signal_name ~* '(vehicle|car).*speed' THEN 'drive_speed'
            WHEN signal_name ~* 'torque' THEN 'drive_torque'
            WHEN signal_name ~* 'motor.*power' OR signal_name ~* 'drive.*power' THEN 'drive_power'
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
    # powertrain은 기본 테이블 정의이므로 삭제하지 않음
