"""Real-time scan progress tracking for Phase 7.

Provides SSE (Server-Sent Events) streaming and polling endpoints for scan progress.
"""
from typing import Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass, asdict
import json

from flask import Response
from app.extensions import db
from app.modules.scans.models import Scan


@dataclass
class ScanProgress:
    """Scan progress state."""
    scan_id: int
    status: str  # 'running', 'completed', 'failed'
    progress_pct: float
    current_step: str
    total_steps: int
    completed_steps: int
    ecu_progress: Dict[str, Any]  # {ecu_address: {sent: int, received: int, errors: int}}
    last_error: Optional[str]
    timestamp: str
    
    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


class ScanProgressTracker:
    """Track and broadcast scan progress in real-time."""
    
    def __init__(self):
        # In-memory progress cache (for development; use Redis in production)
        self._progress_cache: Dict[int, ScanProgress] = {}
    
    def start_scan(self, scan_id: int, total_steps: int) -> None:
        """Initialize progress tracking for a new scan."""
        self._progress_cache[scan_id] = ScanProgress(
            scan_id=scan_id,
            status='running',
            progress_pct=0.0,
            current_step='Initializing',
            total_steps=total_steps,
            completed_steps=0,
            ecu_progress={},
            last_error=None,
            timestamp=datetime.utcnow().isoformat()
        )
    
    def update_progress(
        self,
        scan_id: int,
        current_step: str,
        completed_steps: Optional[int] = None,
        ecu_address: Optional[str] = None,
        ecu_status: Optional[Dict[str, int]] = None,
        error: Optional[str] = None
    ) -> None:
        """Update scan progress."""
        if scan_id not in self._progress_cache:
            return
        
        progress = self._progress_cache[scan_id]
        progress.current_step = current_step
        progress.timestamp = datetime.utcnow().isoformat()
        
        if completed_steps is not None:
            progress.completed_steps = completed_steps
            progress.progress_pct = (completed_steps / progress.total_steps * 100) if progress.total_steps > 0 else 0
        
        if ecu_address and ecu_status:
            progress.ecu_progress[ecu_address] = ecu_status
        
        if error:
            progress.last_error = error
    
    def complete_scan(self, scan_id: int, success: bool = True, error: Optional[str] = None) -> None:
        """Mark scan as completed or failed."""
        if scan_id not in self._progress_cache:
            return
        
        progress = self._progress_cache[scan_id]
        progress.status = 'completed' if success else 'failed'
        progress.progress_pct = 100.0 if success else progress.progress_pct
        progress.timestamp = datetime.utcnow().isoformat()
        
        if error:
            progress.last_error = error
    
    def get_progress(self, scan_id: int) -> Optional[ScanProgress]:
        """Get current progress for a scan."""
        return self._progress_cache.get(scan_id)
    
    def clear_progress(self, scan_id: int) -> None:
        """Remove progress from cache (after scan is complete and viewed)."""
        self._progress_cache.pop(scan_id, None)
    
    def stream_progress(self, scan_id: int) -> Response:
        """Stream progress updates via Server-Sent Events (SSE)."""
        def generate():
            # Send initial state
            progress = self.get_progress(scan_id)
            if progress:
                yield f"data: {progress.to_json()}\n\n"
            
            # Stream updates (poll every 500ms)
            import time
            while True:
                progress = self.get_progress(scan_id)
                if progress:
                    yield f"data: {progress.to_json()}\n\n"
                    
                    # Stop streaming if scan is complete
                    if progress.status in ('completed', 'failed'):
                        break
                
                time.sleep(0.5)
        
        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'  # Disable nginx buffering
            }
        )


# Global tracker instance
progress_tracker = ScanProgressTracker()


def get_scan_progress(scan_id: int) -> Optional[Dict[str, Any]]:
    """Get progress for a scan (polling endpoint)."""
    progress = progress_tracker.get_progress(scan_id)
    return progress.to_dict() if progress else None
