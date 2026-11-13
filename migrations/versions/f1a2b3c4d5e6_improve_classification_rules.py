"""improve classification rules

Revision ID: f1a2b3c4d5e6
Revises: 3b4b2ec6cbe3
Create Date: 2026-11-13 20:55:00.000000

개선된 분류 규칙:
- ECU: Korean names, 29-bit headers, common keywords (VCU/LDC/MDPS/ESC/EPS/HVAC/FATC/TPMS/gateway/SRS/airbag)
- Signals: unit-based categories (V/A/°C/%/km/h/rpm/Nm/kW/kWh/bar/kPa)
- Vehicles: model name patterns, BMS presence, fuel type
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = '3b4b2ec6cbe3'
branch_labels = None
depends_on = None


def upgrade():
    # Re-classify UNKNOWN ECUs with improved rules
    # Add Korean ECU names and additional keywords
    op.execute(r"""
        UPDATE diagnostic_commands
        SET ecu_module = CASE
            -- Korean ECU names
            WHEN ecu_name ~* '(배터리|베터리|밧데리)' OR label ~* '(배터리|베터리|밧데리)' THEN 'BMS'
            WHEN ecu_name ~* '(모터|인버터)' OR label ~* '(모터|인버터)' THEN 'MCU'
            WHEN ecu_name ~* '(충전|OBC)' OR label ~* '(충전|OBC)' THEN 'OBC'
            WHEN ecu_name ~* '(차량제어|VCU)' OR label ~* '(차량제어|VCU)' THEN 'VCU'
            WHEN ecu_name ~* '(엔진|ECM)' OR label ~* '(엔진)' THEN 'ECM'
            WHEN ecu_name ~* '(변속기|TCM)' OR label ~* '(변속기|기어)' THEN 'TCM'
            WHEN ecu_name ~* '(계기판|클러스터)' THEN 'CLUSTER'
            WHEN ecu_name ~* '(바디|BCM)' THEN 'BCM'
            WHEN ecu_name ~* '(브레이크|ABS|ESC)' OR label ~* '(브레이크|ABS)' THEN 'ABS'
            WHEN ecu_name ~* '(에어백|SRS)' THEN 'ABS'  -- SRS often grouped with chassis/safety
            WHEN ecu_name ~* '(조향|MDPS|EPS)' THEN 'ABS'  -- steering grouped with chassis
            WHEN ecu_name ~* '(에어컨|HVAC|FATC)' THEN 'HVAC'
            WHEN ecu_name ~* '(타이어|TPMS)' THEN 'TPMS'
            WHEN ecu_name ~* '(게이트웨이|gateway)' THEN 'GATEWAY'
            WHEN ecu_name ~* '(LDC|DC.*DC|컨버터)' THEN 'LDC'
            
            -- Additional English keywords
            WHEN ecu_name ~* 'VCU|vehicle.?control' OR label ~* 'VCU' THEN 'VCU'
            WHEN ecu_name ~* 'LDC|DC.*converter' THEN 'LDC'
            WHEN ecu_name ~* 'MDPS|EPS|steering' OR label ~* 'steering' THEN 'ABS'
            WHEN ecu_name ~* 'ESC|stability' THEN 'ABS'
            WHEN ecu_name ~* 'SRS|airbag' THEN 'ABS'
            WHEN ecu_name ~* 'HVAC|FATC|climate|A/C' THEN 'HVAC'
            WHEN ecu_name ~* 'TPMS|tire.?pressure' THEN 'TPMS'
            WHEN ecu_name ~* 'gateway|CGW' THEN 'GATEWAY'
            
            -- 29-bit CAN headers (18DA..F1 format for UDS)
            WHEN ecu_address ~* '^18D[A-F]' THEN CASE
                WHEN ecu_address ~* '18DA.*F1' THEN 'ECM'
                WHEN ecu_address ~* '18DA.*(E2|E4)' THEN 'BMS'
                WHEN ecu_address ~* '18DA.*E1' THEN 'MCU'
                WHEN ecu_address ~* '18DA.*E5' THEN 'OBC'
                ELSE 'UNKNOWN'
            END
            
            -- Standard 11-bit addresses
            WHEN ecu_address IN ('7E2', '7EA') THEN 'MCU'
            WHEN ecu_address IN ('7E4', '7EC') THEN 'BMS'
            WHEN ecu_address IN ('7E5', '7ED') THEN 'OBC'
            WHEN ecu_address IN ('7E0', '7E1', '7E8', '7E9') THEN 'ECM'
            WHEN ecu_address IN ('7E3', '7EB') THEN 'TCM'
            WHEN ecu_address = '7DF' THEN 'ECM'  -- broadcast
            WHEN ecu_address = '7C0' THEN 'CLUSTER'
            WHEN ecu_address IN ('7A0', '7A8') THEN 'BCM'
            
            ELSE ecu_module  -- keep existing if none match
        END
        WHERE ecu_module = 'UNKNOWN'
    """)
    
    # Re-classify 'other' signals with unit-based rules
    op.execute(r"""
        UPDATE dbc_signals
        SET signal_category = CASE
            -- Unit-based classification (most reliable)
            WHEN unit ~* '^(V|volt)' AND signal_name ~* 'cell' THEN 'cell_voltage'
            WHEN unit ~* '^(V|volt)' AND signal_name ~* '(pack|battery|HV)' THEN 'battery_voltage'
            WHEN unit ~* '^(V|volt)' THEN 'voltage'
            WHEN unit ~* '^(A|amp)' AND signal_name ~* '(pack|battery|HV)' THEN 'battery_current'
            WHEN unit ~* '^(A|amp)' THEN 'current'
            WHEN unit ~* '^(°C|degC|celsius)' OR unit = 'C' THEN 'temperature'
            WHEN unit ~* '^%' AND signal_name ~* '(SOC|charge)' THEN 'battery_soc'
            WHEN unit ~* '^%' AND signal_name ~* '(SOH|health)' THEN 'battery_soh'
            WHEN unit ~* '^%' THEN 'percentage'
            WHEN unit ~* '^(km/h|kph|mph)' THEN 'drive_speed'
            WHEN unit ~* '^(rpm|RPM)' AND signal_name ~* 'motor' THEN 'motor_speed'
            WHEN unit ~* '^(rpm|RPM)' AND signal_name ~* 'engine' THEN 'engine_speed'
            WHEN unit ~* '^(rpm|RPM)' THEN 'rotation_speed'
            WHEN unit ~* '^(Nm|N\.m)' THEN 'drive_torque'
            WHEN unit ~* '^kW' AND signal_name ~* 'charg' THEN 'charging_power'
            WHEN unit ~* '^kW' THEN 'power'
            WHEN unit ~* '^kWh' THEN 'energy'
            WHEN unit ~* '^(bar|kPa|psi|Pa)' THEN 'pressure'
            
            -- Name-based rules (fallback when unit is missing)
            WHEN signal_name ~* '(SOC|state.*of.*charge)' THEN 'battery_soc'
            WHEN signal_name ~* '(SOH|state.*of.*health)' THEN 'battery_soh'
            WHEN signal_name ~* 'cell.*(volt|V\d)' THEN 'cell_voltage'
            WHEN signal_name ~* '(pack|battery|HV).*(volt|V\d)' THEN 'battery_voltage'
            WHEN signal_name ~* '(pack|battery|HV).*(current|amp|A\d)' THEN 'battery_current'
            WHEN signal_name ~* '(temp|temperature)' THEN 'temperature'
            WHEN signal_name ~* '(vehicle|car|wheel).*(speed|velocity)' THEN 'drive_speed'
            WHEN signal_name ~* '(motor|drive).*(torque|Nm)' THEN 'drive_torque'
            WHEN signal_name ~* '(motor|engine).*(speed|rpm)' THEN 'motor_speed'
            WHEN signal_name ~* 'charg.*(power|kW)' THEN 'charging_power'
            WHEN signal_name ~* '(motor|drive|inverter).*(power|kW)' THEN 'drive_power'
            WHEN signal_name ~* '(dtc|fault|error|warning|diagnostic)' THEN 'dtc'
            WHEN signal_name ~* '(pressure|bar|kPa|psi)' THEN 'pressure'
            WHEN signal_name ~* '(odometer|mileage|distance)' THEN 'distance'
            WHEN signal_name ~* '(gear|shift)' THEN 'transmission'
            
            ELSE signal_category  -- keep existing if none match
        END
        WHERE signal_category = 'other'
    """)
    
    # Re-classify unknown vehicle powertrains
    op.execute(r"""
        UPDATE vehicle_definitions
        SET powertrain = CASE
            -- Pure EV model names
            WHEN model ~* '(^EV\d|EV6|EV9|IONIQ.*5|IONIQ.*6|GV60|GV70.*electrified)' THEN 'BEV'
            WHEN model ~* '(leaf|model.*[3sxy]|bolt|kona.*electric|niro.*ev|e-?tron|i[34]|iX|taycan)' THEN 'BEV'
            WHEN model ~* '(ID\.[34]|mach-e|F-150.*lightning|rivian|lucid|polestar)' THEN 'BEV'
            
            -- Hybrid keywords
            WHEN model ~* '(hybrid|HEV)' AND NOT model ~* '(plug|PHEV)' THEN 'HEV'
            WHEN model ~* '(plug.*hybrid|PHEV)' THEN 'PHEV'
            
            -- Fuel type from definitions (if available)
            -- This would need to check a fuel_type column if it exists
            
            ELSE powertrain  -- keep existing if none match
        END
        WHERE powertrain = 'unknown'
    """)
    
    # Classify vehicles by BMS command presence (run after definitions loaded)
    # This requires joining with diagnostic_commands, best done via app command
    # Left as TODO for flask definitions classify command


def downgrade():
    # No downgrade - classification improvements are additive
    pass
