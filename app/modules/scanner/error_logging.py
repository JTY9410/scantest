"""Structured error logging for Phase 7.

Logs scan errors in a structured format for analysis and debugging.
"""
from typing import Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass, asdict
import json
import logging

from app.extensions import db
from sqlalchemy import text


logger = logging.getLogger(__name__)


@dataclass
class ScanError:
    """Structured scan error."""
    scan_id: int
    timestamp: str
    error_type: str  # 'timeout', 'nrc', 'protocol', 'transport', 'parse', 'unknown'
    error_code: Optional[str]  # NRC code, transport error code, etc.
    error_message: str
    context: Dict[str, Any]  # {ecu: str, command: str, step: str, ...}
    severity: str  # 'warning', 'error', 'critical'
    recoverable: bool
    
    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


class ErrorLogger:
    """Structured error logger for scan operations."""
    
    # NRC (Negative Response Code) descriptions from ISO 14229
    NRC_DESCRIPTIONS = {
        '10': 'General Reject',
        '11': 'Service Not Supported',
        '12': 'Sub-Function Not Supported',
        '13': 'Incorrect Message Length',
        '14': 'Response Too Long',
        '22': 'Conditions Not Correct',
        '24': 'Request Sequence Error',
        '31': 'Request Out Of Range',
        '33': 'Security Access Denied',
        '35': 'Invalid Key',
        '36': 'Exceeded Number Of Attempts',
        '37': 'Required Time Delay Not Expired',
        '70': 'Upload/Download Not Accepted',
        '71': 'Transfer Data Suspended',
        '72': 'General Programming Failure',
        '73': 'Wrong Block Sequence Counter',
        '78': 'Request Correctly Received - Response Pending',
        '7E': 'Sub-Function Not Supported In Active Session',
        '7F': 'Service Not Supported In Active Session',
    }
    
    def __init__(self):
        self._session_errors: Dict[int, list[ScanError]] = {}
    
    def log_error(
        self,
        scan_id: int,
        error_type: str,
        error_message: str,
        error_code: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        severity: str = 'error',
        recoverable: bool = True
    ) -> ScanError:
        """Log a structured error."""
        error = ScanError(
            scan_id=scan_id,
            timestamp=datetime.utcnow().isoformat(),
            error_type=error_type,
            error_code=error_code,
            error_message=error_message,
            context=context or {},
            severity=severity,
            recoverable=recoverable
        )
        
        # Add to session cache
        if scan_id not in self._session_errors:
            self._session_errors[scan_id] = []
        self._session_errors[scan_id].append(error)
        
        # Log to application logger
        log_level = {
            'warning': logging.WARNING,
            'error': logging.ERROR,
            'critical': logging.CRITICAL
        }.get(severity, logging.ERROR)
        
        logger.log(
            log_level,
            f"Scan {scan_id} {error_type}: {error_message}",
            extra={'scan_error': error.to_dict()}
        )
        
        return error
    
    def log_nrc(
        self,
        scan_id: int,
        nrc_code: str,
        ecu: str,
        command: str,
        severity: str = 'warning'
    ) -> ScanError:
        """Log a Negative Response Code (NRC) error."""
        nrc_desc = self.NRC_DESCRIPTIONS.get(nrc_code, f'Unknown NRC {nrc_code}')
        
        return self.log_error(
            scan_id=scan_id,
            error_type='nrc',
            error_code=nrc_code,
            error_message=f'NRC {nrc_code}: {nrc_desc}',
            context={
                'ecu': ecu,
                'command': command,
                'nrc_description': nrc_desc
            },
            severity=severity,
            recoverable=True
        )
    
    def log_timeout(
        self,
        scan_id: int,
        ecu: str,
        command: str,
        timeout_ms: int,
        severity: str = 'warning'
    ) -> ScanError:
        """Log a command timeout error."""
        return self.log_error(
            scan_id=scan_id,
            error_type='timeout',
            error_message=f'Command timeout after {timeout_ms}ms',
            context={
                'ecu': ecu,
                'command': command,
                'timeout_ms': timeout_ms
            },
            severity=severity,
            recoverable=True
        )
    
    def log_transport_error(
        self,
        scan_id: int,
        transport_type: str,
        error_message: str,
        context: Optional[Dict[str, Any]] = None,
        severity: str = 'error'
    ) -> ScanError:
        """Log a transport layer error."""
        return self.log_error(
            scan_id=scan_id,
            error_type='transport',
            error_message=error_message,
            context={
                'transport_type': transport_type,
                **(context or {})
            },
            severity=severity,
            recoverable=False
        )
    
    def log_protocol_error(
        self,
        scan_id: int,
        protocol: str,
        error_message: str,
        context: Optional[Dict[str, Any]] = None,
        severity: str = 'error'
    ) -> ScanError:
        """Log a protocol-level error."""
        return self.log_error(
            scan_id=scan_id,
            error_type='protocol',
            error_message=error_message,
            context={
                'protocol': protocol,
                **(context or {})
            },
            severity=severity,
            recoverable=True
        )
    
    def get_errors(self, scan_id: int) -> list[ScanError]:
        """Get all errors for a scan."""
        return self._session_errors.get(scan_id, [])
    
    def get_error_summary(self, scan_id: int) -> Dict[str, Any]:
        """Get error summary statistics."""
        errors = self.get_errors(scan_id)
        
        if not errors:
            return {
                'total_errors': 0,
                'by_type': {},
                'by_severity': {},
                'recoverable_count': 0,
                'critical_count': 0
            }
        
        by_type = {}
        by_severity = {}
        recoverable_count = 0
        
        for error in errors:
            # Count by type
            by_type[error.error_type] = by_type.get(error.error_type, 0) + 1
            
            # Count by severity
            by_severity[error.severity] = by_severity.get(error.severity, 0) + 1
            
            # Count recoverable
            if error.recoverable:
                recoverable_count += 1
        
        return {
            'total_errors': len(errors),
            'by_type': by_type,
            'by_severity': by_severity,
            'recoverable_count': recoverable_count,
            'critical_count': by_severity.get('critical', 0)
        }
    
    def clear_errors(self, scan_id: int) -> None:
        """Clear errors for a scan (after review)."""
        self._session_errors.pop(scan_id, None)
    
    def persist_errors(self, scan_id: int) -> None:
        """Persist errors to database for long-term storage."""
        errors = self.get_errors(scan_id)
        
        if not errors:
            return
        
        # Store as JSON in scan_logs or a dedicated error table
        # For now, just log the summary
        summary = self.get_error_summary(scan_id)
        logger.info(
            f"Scan {scan_id} completed with {summary['total_errors']} errors: {summary}"
        )


# Global error logger instance
error_logger = ErrorLogger()
