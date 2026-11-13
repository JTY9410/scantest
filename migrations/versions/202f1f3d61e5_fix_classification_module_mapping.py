"""fix classification module mapping

Revision ID: 202f1f3d61e5
Revises: b3c4d5e6f7a8
Create Date: 2026-11-13 21:10:00.000000

분류 모듈 매핑 수정:
- 조향(steering)/MDPS/EPS → STEERING (not ABS)
- 에어백(airbag)/SRS → SRS (not ABS)  
- VCU/LDC/HVAC/TPMS/GATEWAY → 각각의 모듈

Allowed ecu_module values:
BMS, MCU, OBC, VCU, ECM, TCM, ABS, ESC, STEERING, SRS, CLUSTER, BCM, HVAC, TPMS, LDC, GATEWAY, UNKNOWN
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '202f1f3d61e5'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade():
    # Re-classify incorrectly mapped ECUs from f1a2b3c4d5e6
    # This updates ONLY the incorrect mappings, leaving correct ones intact
    
    # Steering was incorrectly mapped to ABS - fix to STEERING
    op.execute("""
        UPDATE diagnostic_commands
        SET ecu_module = 'STEERING'
        WHERE ecu_module = 'ABS'
        AND (ecu_name ~* '(조향|MDPS|EPS|steering)' 
             OR label ~* 'steering')
    """)
    
    op.execute("""
        UPDATE dbc_signals
        SET ecu_module = 'STEERING'
        WHERE ecu_module = 'ABS'
        AND signal_name ~* '(steering|MDPS|EPS|steer)'
    """)
    
    # Airbag was incorrectly mapped to ABS - fix to SRS
    op.execute("""
        UPDATE diagnostic_commands
        SET ecu_module = 'SRS'
        WHERE ecu_module = 'ABS'
        AND (ecu_name ~* '(에어백|SRS|airbag)'
             OR label ~* '(airbag|SRS)')
    """)
    
    op.execute("""
        UPDATE dbc_signals
        SET ecu_module = 'SRS'
        WHERE ecu_module = 'ABS'
        AND signal_name ~* '(airbag|SRS)'
    """)
    
    # ESC (stability control) should be separate from ABS
    op.execute("""
        UPDATE diagnostic_commands
        SET ecu_module = 'ESC'
        WHERE ecu_module = 'ABS'
        AND (ecu_name ~* '(ESC|stability|electronic.*stability)'
             OR label ~* '(ESC|stability)')
    """)
    
    # Now apply the corrected classification rules to UNKNOWN modules
    # This is the fixed version of what f1a2b3c4d5e6 should have done
    
    op.execute("""
        UPDATE diagnostic_commands
        SET ecu_module = CASE
            -- Korean ECU names with correct mapping
            WHEN ecu_name ~* '(배터리|베터리|밧데리)' OR label ~* '(배터리|베터리|밧데리)' THEN 'BMS'
            WHEN ecu_name ~* '(모터|인버터)' OR label ~* '(모터|인버터)' THEN 'MCU'
            WHEN ecu_name ~* '(충전|OBC)' OR label ~* '(충전|OBC)' THEN 'OBC'
            WHEN ecu_name ~* '(차량제어|VCU)' OR label ~* '(차량제어|VCU)' THEN 'VCU'
            WHEN ecu_name ~* '(엔진|ECM)' OR label ~* '(엔진)' THEN 'ECM'
            WHEN ecu_name ~* '(변속기|TCM)' OR label ~* '(변속기|기어)' THEN 'TCM'
            WHEN ecu_name ~* '(계기판|클러스터)' THEN 'CLUSTER'
            WHEN ecu_name ~* '(바디|BCM)' THEN 'BCM'
            
            -- Correct Korean classifications
            WHEN ecu_name ~* '(조향|MDPS|EPS)' THEN 'STEERING'
            WHEN ecu_name ~* '(에어백|SRS)' THEN 'SRS'
            WHEN ecu_name ~* '(브레이크|ABS)' OR label ~* '(브레이크|ABS)' THEN 'ABS'
            WHEN ecu_name ~* '(안정성|ESC)' THEN 'ESC'
            WHEN ecu_name ~* '(에어컨|HVAC|FATC)' THEN 'HVAC'
            WHEN ecu_name ~* '(타이어|TPMS)' THEN 'TPMS'
            WHEN ecu_name ~* '(게이트웨이|gateway)' THEN 'GATEWAY'
            WHEN ecu_name ~* '(LDC|DC.*DC|컨버터)' THEN 'LDC'
            
            -- English keywords with correct mapping
            WHEN ecu_name ~* 'VCU|vehicle.?control' OR label ~* 'VCU' THEN 'VCU'
            WHEN ecu_name ~* 'LDC|DC.*converter' THEN 'LDC'
            WHEN ecu_name ~* 'MDPS|EPS|steering' OR label ~* 'steering' THEN 'STEERING'
            WHEN ecu_name ~* 'ESC|stability' THEN 'ESC'
            WHEN ecu_name ~* 'SRS|airbag' THEN 'SRS'
            WHEN ecu_name ~* 'HVAC|FATC|climate|A/C' THEN 'HVAC'
            WHEN ecu_name ~* 'TPMS|tire.?pressure' THEN 'TPMS'
            WHEN ecu_name ~* 'gateway|CGW' THEN 'GATEWAY'
            
            -- 29-bit CAN headers
            WHEN ecu_address ~* '^18D[A-F]' THEN CASE
                WHEN ecu_address ~* '18DA.*F1' THEN 'ECM'
                WHEN ecu_address ~* '18DA.*(E2|E4)' THEN 'BMS'
                WHEN ecu_address ~* '18DA.*E1' THEN 'MCU'
                WHEN ecu_address ~* '18DA.*E5' THEN 'OBC'
                ELSE ecu_module
            END
            
            -- Standard addresses
            WHEN ecu_address IN ('7E2', '7EA') THEN 'MCU'
            WHEN ecu_address IN ('7E4', '7EC') THEN 'BMS'
            WHEN ecu_address IN ('7E5', '7ED') THEN 'OBC'
            WHEN ecu_address IN ('7E0', '7E1', '7E8', '7E9', '7DF') THEN 'ECM'
            WHEN ecu_address IN ('7E3', '7EB') THEN 'TCM'
            WHEN ecu_address = '7C0' THEN 'CLUSTER'
            WHEN ecu_address IN ('7A0', '7A8') THEN 'BCM'
            
            ELSE ecu_module
        END
        WHERE ecu_module = 'UNKNOWN' OR ecu_module IS NULL
    """)
    
    # Apply to signals as well
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
            
            -- Correct mappings
            WHEN signal_name ~* '(steering|steer|MDPS|EPS)' THEN 'STEERING'
            WHEN signal_name ~* '(airbag|SRS)' THEN 'SRS'
            WHEN signal_name ~* '(abs|brake)' THEN 'ABS'
            WHEN signal_name ~* '(ESC|stability)' THEN 'ESC'
            WHEN signal_name ~* '(HVAC|climate|A/C)' THEN 'HVAC'
            WHEN signal_name ~* '(TPMS|tire.*pressure)' THEN 'TPMS'
            WHEN signal_name ~* '(LDC|DC.*DC)' THEN 'LDC'
            WHEN signal_name ~* 'gateway' THEN 'GATEWAY'
            
            ELSE ecu_module
        END
        WHERE ecu_module = 'UNKNOWN' OR ecu_module IS NULL
    """)


def downgrade():
    # Revert to the incorrect mappings from f1a2b3c4d5e6
    op.execute("""
        UPDATE diagnostic_commands
        SET ecu_module = 'ABS'
        WHERE ecu_module IN ('STEERING', 'SRS', 'ESC')
    """)
    
    op.execute("""
        UPDATE dbc_signals
        SET ecu_module = 'ABS'
        WHERE ecu_module IN ('STEERING', 'SRS', 'ESC')
    """)
    
    op.execute("""
        UPDATE diagnostic_commands
        SET ecu_module = 'UNKNOWN'
        WHERE ecu_module IN ('VCU', 'LDC', 'HVAC', 'TPMS', 'GATEWAY')
    """)
    
    op.execute("""
        UPDATE dbc_signals
        SET ecu_module = 'UNKNOWN'
        WHERE ecu_module IN ('VCU', 'LDC', 'HVAC', 'TPMS', 'GATEWAY')
    """)
