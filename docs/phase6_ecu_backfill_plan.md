# Phase 6: ECU/Category Backfill Plan

## Current State (from Phase 5 Audit)
- Commands ecu_module UNKNOWN/NULL: 64.9% (target: <10%)
- DBC signals ecu_module UNKNOWN/NULL: 90.5% (target: <10%)
- DBC signals signal_category other/UNKNOWN/NULL: 80.1% (target: <10%)

## Strategy

### 1. Evidence-Based Classification Only
- Extract ECU/category info ONLY from source files that explicitly state it
- Never guess or infer
- Common sources of evidence:
  - DBC file comments (e.g., `BO_ 123 BMS_Status: ...`)
  - File path structure (e.g., `/BMS/commands/`, `/MCU/signals/`)
  - Command labels with ECU prefix (e.g., `BMS_CellVoltage`, `MCU_Speed`)
  - Signal sender/receiver fields in DBC

### 2. ECU Module Mapping
Priority ECU modules (from existing data):
- BMS (Battery Management System)
- MCU (Motor Control Unit)
- OBC (On-Board Charger)
- VCU (Vehicle Control Unit)
- ECM (Engine Control Module)
- TCM (Transmission Control Module)
- BCM (Body Control Module)
- ABS/ESP (Brake systems)

### 3. Signal Category Mapping  
Common categories:
- battery_soc, battery_soh, battery_voltage, battery_current, battery_temp
- motor_speed, motor_torque, motor_temp
- vehicle_speed, odometer
- charging_status, charging_power
- dtc (diagnostic trouble codes)

### 4. Implementation Steps
1. Create backfill script that:
   - Reads definition_sources and associated commands/signals
   - Extracts ECU/category from file paths, comments, names
   - Updates only where evidence exists
   - Logs source of classification for audit

2. Add CLI command `flask definitions backfill-ecu`:
   - Shows before/after UNKNOWN counts
   - --report-only mode for dry run
   - --yes to apply changes

3. Test with 0 failures

4. Commit, merge, publish
