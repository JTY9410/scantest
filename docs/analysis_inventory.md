# Analysis Inventory

## Overview
This document tracks the analysis methods and data interpretation techniques used across the WESCAN platform. It ensures transparency and reusability of existing commands and formulas.

## Battery Management System (BMS)

### State of Charge (SOC)
**ECU**: 7E4 (BMS)  
**Commands**:
- `22 0101` - Hyundai/Kia BMS SOC (%)
- `22 0105` - Hyundai/Kia BMS detailed SOC

**Formula**: `(byte3 * 256 + byte4) / 2`  
**Unit**: %  
**Source**: OBDb, WiCAN logs  
**Confidence**: High (validated across multiple vehicles)

### State of Health (SOH)
**ECU**: 7E4 (BMS)  
**Commands**:
- `21 01` - KWP2000 SOH request (older vehicles)
- `22 0105` - UDS SOH request (newer vehicles)

**Formula**: `byte5 / 2` or `(byte3 * 256 + byte4) / 2`  
**Unit**: %  
**Source**: OBDb, CanZE  
**Confidence**: High (cross-validated with Torque definitions)

### Cell Voltages
**ECU**: 7E4 (BMS)  
**Commands**:
- Vehicle-specific DIDs (varies by model)
- Typically `22 01xx` to `22 05xx` range

**Formula**: `(byte_n * 256 + byte_n+1) / 50` (millivolts)  
**Unit**: mV  
**Source**: OBDb, manufacturer-specific definitions  
**Confidence**: Medium (requires per-model validation)

### Battery Temperature
**ECU**: 7E4 (BMS)  
**Commands**:
- `22 0101` - Multiple temperature sensors
- `22 0105` - Detailed temperature array

**Formula**: `byte_n - 40` (Celsius)  
**Unit**: °C  
**Source**: OBDb, CanZE  
**Confidence**: High

## Motor Control Unit (MCU)

### Motor Speed (RPM)
**ECU**: 7E1, 7E5 (MCU)  
**Commands**:
- `01 0C` - Standard OBD2 engine RPM
- `22 xxxx` - Manufacturer-specific motor RPM

**Formula**: `(A * 256 + B) / 4`  
**Unit**: RPM  
**Source**: SAE J1979, OBDb  
**Confidence**: High

### Motor Torque
**ECU**: 7E1, 7E5 (MCU)  
**Commands**:
- `22 xxxx` - Manufacturer-specific torque requests

**Formula**: Varies by manufacturer  
**Unit**: Nm  
**Source**: OBDb, manufacturer definitions  
**Confidence**: Medium (requires validation)

### Motor Temperature
**ECU**: 7E5 (MCU)  
**Commands**:
- `22 xxxx` - Motor/inverter temperature

**Formula**: `byte_n - 40`  
**Unit**: °C  
**Source**: OBDb  
**Confidence**: Medium

## Vehicle Control Unit (VCU)

### Vehicle Speed
**ECU**: 7E0, 7DF (broadcast)  
**Commands**:
- `01 0D` - Standard OBD2 vehicle speed
- `22 xxxx` - Manufacturer-specific speed

**Formula**: `A` (km/h)  
**Unit**: km/h  
**Source**: SAE J1979  
**Confidence**: High

### Odometer
**ECU**: 7C6 (Cluster), 7E5 (VCU)  
**Commands**:
- `01 A6` - Standard OBD2 odometer (newer vehicles)
- `22 B002`, `22 B004`, `22 B001`, `22 B003` - Hyundai/Kia cluster
- `22 1050` - EV odometer

**Formula**: `(byte1 * 16777216 + byte2 * 65536 + byte3 * 256 + byte4)` or `/ 10` for km  
**Unit**: km  
**Source**: SAE J1979, OBDb, WiCAN  
**Confidence**: High

## On-Board Charger (OBC)

### Charging Status
**ECU**: 7E2, 7E4 (OBC/BMS)  
**Commands**:
- `22 xxxx` - Charging state requests

**Formula**: Bit flags or enum values  
**Unit**: Status code  
**Source**: OBDb, manufacturer definitions  
**Confidence**: Medium

### Charging Power
**ECU**: 7E2 (OBC)  
**Commands**:
- `22 xxxx` - Charging voltage/current

**Formula**: `(voltage_bytes) * (current_bytes) / scaling_factor`  
**Unit**: kW  
**Source**: OBDb  
**Confidence**: Medium

## Diagnostic Trouble Codes (DTC)

### Read DTCs
**ECU**: All (broadcast 7DF or specific ECUs)  
**Commands**:
- `03` - OBD2 request stored DTCs
- `07` - OBD2 request pending DTCs
- `19 02 FF` - UDS read DTCs by status mask
- `19 02 09` - UDS confirmed DTCs
- `19 02 04` - UDS pending DTCs

**Format**: 
- OBD2: 2-byte code (P0301 = 03 01)
- UDS: 3-byte code + status byte

**Source**: SAE J1979, ISO 14229  
**Confidence**: High

### Freeze Frame Data
**ECU**: All  
**Commands**:
- `02 xx` - OBD2 freeze frame for specific PID
- `19 04 <DTC>` - UDS snapshot data

**Formula**: Same as corresponding PID  
**Source**: SAE J1979, ISO 14229  
**Confidence**: High

## Standard OBD2 PIDs

### Mode 01 (Live Data)
- `01 00`, `01 20`, `01 40`, `01 60`, `01 80`, `01 A0`, `01 C0` - Supported PIDs bitmaps
- `01 01` - Monitor status
- `01 04` - Calculated engine load (%)
- `01 05` - Engine coolant temperature (°C)
- `01 0C` - Engine RPM
- `01 0D` - Vehicle speed (km/h)
- `01 0F` - Intake air temperature (°C)
- `01 11` - Throttle position (%)

**Source**: SAE J1979 (ISO 15031-5)  
**Confidence**: High

### Mode 06 (Test Results)
**Commands**: `06 xx` for each supported MID  
**Source**: SAE J1979  
**Confidence**: High (manufacturer-specific interpretation)

### Mode 09 (Vehicle Information)
- `09 02` - VIN (17 characters)
- `09 04` - Calibration ID
- `09 06` - Calibration verification number
- `09 0A` - ECU name

**Source**: SAE J1979  
**Confidence**: High

## Analysis Methods by Category

### battery_soc
- **Primary**: `22 0101` byte3-4 (Hyundai/Kia)
- **Fallback**: DBC signal `SOC` from BMS CAN messages
- **Validation**: Cross-check with dashboard display

### battery_soh
- **Primary**: `21 01` or `22 0105` (manufacturer-specific)
- **Fallback**: Calculated from capacity degradation
- **Validation**: Compare with OEM diagnostic tools

### battery_voltage
- **Primary**: `22 0101` pack voltage bytes
- **Secondary**: Sum of cell voltages
- **Validation**: Compare pack voltage to cell voltage sum

### battery_current
- **Primary**: `22 0101` current bytes
- **Formula**: Signed 16-bit integer with scaling
- **Validation**: Power = Voltage × Current

### battery_temp
- **Primary**: Multiple sensor array from `22 0101` or `22 0105`
- **Formula**: `byte - 40` (offset Celsius)
- **Validation**: Sanity check against ambient temp

### motor_speed
- **Primary**: `01 0C` (standard RPM)
- **Secondary**: Manufacturer-specific motor RPM DIDs
- **Validation**: Compare to vehicle speed

### vehicle_speed
- **Primary**: `01 0D` (standard speed)
- **Fallback**: Calculated from wheel speed sensors
- **Unit**: km/h

### odometer
- **Primary**: `01 A6` (if supported)
- **Secondary**: `22 B002` (Hyundai/Kia cluster)
- **Tertiary**: `22 1050` (EV-specific)
- **Validation**: Cross-check multiple sources

## Reuse Strategy

### Existing Command Application
1. **Exact match**: Use existing command if maker/model/ECU/service/PID match exactly
2. **Maker match**: Apply generic maker commands when model is unknown
3. **Standard fallback**: Always include SAE J1979 standard commands
4. **Profile enhancement**: Add manufacturer-specific commands from WESCAN profiles

### Formula Reuse
1. Check existing formulas in `diagnostic_commands.formula`
2. Validate unit consistency
3. Apply scaling factors from source definitions
4. Document any modifications

### Validation Requirements
- **High confidence**: Validated across ≥3 vehicles from same manufacturer
- **Medium confidence**: Validated on 1-2 vehicles, matches manufacturer documentation
- **Low confidence**: Derived from single source, needs validation

## Source Priority
1. **OBDb**: Community-validated definitions (highest priority)
2. **WiCAN**: Real-world logged data
3. **Torque**: User-contributed PIDs (validate before use)
4. **CanZE**: Renault/Nissan specific (high confidence for those makers)

## Updates and Maintenance
- Add new commands as they are validated
- Update confidence levels as more data becomes available
- Document anomalies and special cases
- Link to specific vehicle models where applicable

## Notes
- Always prefer standard SAE J1979 commands when available
- Manufacturer-specific commands should include vehicle scoping
- Formula validation should include unit tests with known input/output pairs
- Each analysis method should reference its source definition
