"""DTC and BMS extras extraction for Phase 8.

Extract additional diagnostic information from scan responses:
- Freeze frame data for DTCs
- BMS cell voltage distribution
- Temperature sensor arrays
- Historical fault data
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import re

from app.extensions import db
from sqlalchemy import text


@dataclass
class DTCExtras:
    """Extended DTC information."""
    dtc_code: str
    status_byte: Optional[str]
    occurrence_count: Optional[int]
    freeze_frame: Optional[Dict[str, Any]]
    aging_counter: Optional[int]
    fault_detection_counter: Optional[int]
    priority: Optional[str]  # 'high', 'medium', 'low'
    
    def to_dict(self) -> dict:
        return {
            'dtc_code': self.dtc_code,
            'status_byte': self.status_byte,
            'occurrence_count': self.occurrence_count,
            'freeze_frame': self.freeze_frame,
            'aging_counter': self.aging_counter,
            'fault_detection_counter': self.fault_detection_counter,
            'priority': self.priority
        }


@dataclass
class BMSExtras:
    """Extended BMS information."""
    cell_voltages: List[float]
    cell_voltage_min: float
    cell_voltage_max: float
    cell_voltage_delta: float
    cell_voltage_avg: float
    cell_voltage_std: float
    temperature_sensors: List[float]
    temperature_min: float
    temperature_max: float
    temperature_delta: float
    temperature_avg: float
    balancing_status: Optional[List[bool]]
    isolation_resistance: Optional[float]
    
    def to_dict(self) -> dict:
        return {
            'cell_voltages': self.cell_voltages,
            'cell_voltage_min': self.cell_voltage_min,
            'cell_voltage_max': self.cell_voltage_max,
            'cell_voltage_delta': self.cell_voltage_delta,
            'cell_voltage_avg': self.cell_voltage_avg,
            'cell_voltage_std': self.cell_voltage_std,
            'temperature_sensors': self.temperature_sensors,
            'temperature_min': self.temperature_min,
            'temperature_max': self.temperature_max,
            'temperature_delta': self.temperature_delta,
            'temperature_avg': self.temperature_avg,
            'balancing_status': self.balancing_status,
            'isolation_resistance': self.isolation_resistance
        }


class ExtrasExtractor:
    """Extract additional diagnostic information from scan responses."""
    
    def extract_dtc_extras(
        self,
        dtc_code: str,
        response_data: str,
        ecu_address: str
    ) -> Optional[DTCExtras]:
        """Extract extended DTC information from response.
        
        Args:
            dtc_code: DTC code (e.g., 'P0301')
            response_data: Hex response string
            ecu_address: ECU address
            
        Returns:
            DTCExtras if extraction successful, None otherwise
        """
        try:
            # Parse status byte (byte following DTC in UDS 19 02 response)
            # Byte format: bit 0-1: test failed, bit 2: pending, bit 3: confirmed, etc.
            status_byte = None
            if len(response_data) >= 8:  # Need at least 3 bytes + status
                status_byte = response_data[6:8]
            
            # Parse occurrence counter from 19 06 response (if available)
            occurrence_count = None
            
            # Priority based on DTC prefix
            priority = self._determine_priority(dtc_code)
            
            return DTCExtras(
                dtc_code=dtc_code,
                status_byte=status_byte,
                occurrence_count=occurrence_count,
                freeze_frame=None,  # Extracted separately via 19 04
                aging_counter=None,
                fault_detection_counter=None,
                priority=priority
            )
        except Exception:
            return None
    
    def extract_freeze_frame(
        self,
        dtc_code: str,
        response_data: str
    ) -> Optional[Dict[str, Any]]:
        """Extract freeze frame data for a DTC (UDS 19 04 response).
        
        Args:
            dtc_code: DTC code
            response_data: Hex response from 19 04 <DTC> FF
            
        Returns:
            Dict of PID values at time of fault
        """
        try:
            # Parse 19 04 response format:
            # 59 04 <DTC 3 bytes> <status> <num_dids> <did1> <data1> <did2> <data2> ...
            
            if not response_data or len(response_data) < 16:
                return None
            
            freeze_frame = {}
            
            # Skip service (59), subfunction (04), DTC (3 bytes), status (1 byte)
            offset = 16  # 8 bytes * 2 hex chars
            
            # Parse DIDs and data
            while offset < len(response_data):
                if offset + 4 > len(response_data):
                    break
                
                did = response_data[offset:offset+4]
                offset += 4
                
                # Read data for this DID (assume 2 bytes for simplicity)
                if offset + 4 <= len(response_data):
                    data = response_data[offset:offset+4]
                    freeze_frame[did] = data
                    offset += 4
            
            return freeze_frame if freeze_frame else None
        except Exception:
            return None
    
    def extract_bms_extras(
        self,
        cell_voltage_responses: List[str],
        temperature_responses: List[str]
    ) -> Optional[BMSExtras]:
        """Extract extended BMS information from multiple responses.
        
        Args:
            cell_voltage_responses: List of hex responses containing cell voltages
            temperature_responses: List of hex responses containing temperatures
            
        Returns:
            BMSExtras with aggregated statistics
        """
        try:
            # Parse cell voltages
            cell_voltages = []
            for response in cell_voltage_responses:
                voltages = self._parse_cell_voltages(response)
                cell_voltages.extend(voltages)
            
            if not cell_voltages:
                return None
            
            # Parse temperatures
            temperatures = []
            for response in temperature_responses:
                temps = self._parse_temperatures(response)
                temperatures.extend(temps)
            
            # Calculate statistics
            import statistics
            
            cell_v_min = min(cell_voltages)
            cell_v_max = max(cell_voltages)
            cell_v_avg = statistics.mean(cell_voltages)
            cell_v_std = statistics.stdev(cell_voltages) if len(cell_voltages) > 1 else 0.0
            
            temp_min = min(temperatures) if temperatures else 0.0
            temp_max = max(temperatures) if temperatures else 0.0
            temp_avg = statistics.mean(temperatures) if temperatures else 0.0
            
            return BMSExtras(
                cell_voltages=cell_voltages,
                cell_voltage_min=cell_v_min,
                cell_voltage_max=cell_v_max,
                cell_voltage_delta=cell_v_max - cell_v_min,
                cell_voltage_avg=cell_v_avg,
                cell_voltage_std=cell_v_std,
                temperature_sensors=temperatures,
                temperature_min=temp_min,
                temperature_max=temp_max,
                temperature_delta=temp_max - temp_min,
                temperature_avg=temp_avg,
                balancing_status=None,  # Would need separate response
                isolation_resistance=None  # Would need separate response
            )
        except Exception:
            return None
    
    def _parse_cell_voltages(self, response: str) -> List[float]:
        """Parse cell voltages from hex response.
        
        Typical format: 62 <DID> <volt1_high> <volt1_low> <volt2_high> <volt2_low> ...
        Scaling: millivolts / 50
        """
        voltages = []
        
        # Skip service (62) and DID (4 chars)
        offset = 6
        
        while offset + 4 <= len(response):
            try:
                high = int(response[offset:offset+2], 16)
                low = int(response[offset+2:offset+4], 16)
                voltage_mv = (high * 256 + low) / 50.0
                voltages.append(voltage_mv)
                offset += 4
            except (ValueError, IndexError):
                break
        
        return voltages
    
    def _parse_temperatures(self, response: str) -> List[float]:
        """Parse temperatures from hex response.
        
        Typical format: 62 <DID> <temp1> <temp2> ...
        Scaling: byte - 40 (Celsius)
        """
        temperatures = []
        
        # Skip service (62) and DID (4 chars)
        offset = 6
        
        while offset + 2 <= len(response):
            try:
                temp_byte = int(response[offset:offset+2], 16)
                temp_c = temp_byte - 40
                temperatures.append(temp_c)
                offset += 2
            except (ValueError, IndexError):
                break
        
        return temperatures
    
    def _determine_priority(self, dtc_code: str) -> str:
        """Determine DTC priority based on code prefix."""
        if not dtc_code or len(dtc_code) < 2:
            return 'low'
        
        # P0xxx: Powertrain (generic)
        # P1xxx: Powertrain (manufacturer-specific)
        # C0xxx: Chassis
        # B0xxx: Body
        # U0xxx: Network
        
        prefix = dtc_code[0].upper()
        
        if prefix == 'P':
            # High priority for engine/powertrain critical codes
            if dtc_code.startswith('P0') and int(dtc_code[2], 16) in [0, 1, 2, 3]:
                return 'high'
            return 'medium'
        elif prefix == 'C':
            return 'high'  # Chassis/safety systems
        elif prefix == 'U':
            return 'low'  # Network communication
        else:
            return 'medium'


# Global extractor instance
extras_extractor = ExtrasExtractor()
