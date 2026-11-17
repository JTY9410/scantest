"""Apply collection profiles to scan plans (v2.2.25)."""

from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import select, func

from app.extensions import db
from app.modules.adaptive_collection.models import (
    CollectionProfile,
    SignalWhitelist,
    SignalUsageStats,
    ProfileStatus
)


def get_active_profile(manufacturer: str, model: Optional[str] = None) -> Optional[CollectionProfile]:
    """
    Get active collection profile for manufacturer/model.
    Model-specific profile takes precedence over manufacturer-level.
    
    Returns:
        Active profile or None
    """
    # Try model-specific first
    if model:
        profile = db.session.execute(
            select(CollectionProfile).where(
                CollectionProfile.manufacturer == manufacturer,
                CollectionProfile.model == model,
                CollectionProfile.status == ProfileStatus.APPROVED.value
            ).order_by(CollectionProfile.approved_at.desc())
        ).scalar_one_or_none()
        
        if profile:
            return profile
    
    # Fall back to manufacturer-level
    profile = db.session.execute(
        select(CollectionProfile).where(
            CollectionProfile.manufacturer == manufacturer,
            CollectionProfile.model.is_(None),
            CollectionProfile.status == ProfileStatus.APPROVED.value
        ).order_by(CollectionProfile.approved_at.desc())
    ).scalar_one_or_none()
    
    return profile


def get_whitelisted_signals() -> set[str]:
    """Get all active whitelisted signal identifiers."""
    whitelist = db.session.execute(
        select(SignalWhitelist.signal_identifier).where(
            SignalWhitelist.is_active == True
        )
    ).scalars().all()
    
    return set(whitelist)


def should_include_step(step: dict, profile: Optional[CollectionProfile], whitelist: set[str]) -> bool:
    """
    Determine if a scan step should be included.
    
    Args:
        step: Scan step dict with 'command', 'header', etc.
        profile: Active collection profile (if any)
        whitelist: Set of whitelisted signal identifiers
        
    Returns:
        True if step should be included
    """
    if not profile:
        return True
    
    # Construct signal identifier from step
    # Format: "did:XXXX" for UDS DIDs, "pid:XX" for OBD PIDs, etc.
    signal_id = _step_to_signal_id(step)
    
    if not signal_id:
        # Can't identify signal, include it
        return True
    
    # Whitelisted signals always included
    if signal_id in whitelist:
        return True
    
    # Check if in skip list
    if signal_id in profile.signals_to_skip:
        return False
    
    return True


def _step_to_signal_id(step: dict) -> Optional[str]:
    """
    Convert scan step to signal identifier.
    
    Examples:
        22F190 -> did:F190
        0101 -> pid:01
        190209 -> uds:190209
    """
    command = (step.get('command') or '').strip().upper()
    
    if not command or command.startswith('AT'):
        return None
    
    # UDS Read Data By Identifier (22 XXXX)
    if command.startswith('22') and len(command) >= 6:
        did = command[2:6]
        return f"did:{did}"
    
    # OBD Mode 01 PID
    if command.startswith('01') and len(command) >= 4:
        pid = command[2:4]
        return f"pid:{pid}"
    
    # UDS Read DTC (19 XX...)
    if command.startswith('19'):
        return f"uds:{command}"
    
    # Other commands - use full command as ID
    return f"cmd:{command}"


def apply_profile_to_plan(
    steps: list[dict],
    manufacturer: str,
    model: Optional[str] = None,
    force_full_scan: bool = False,
    scan_count: int = 0
) -> tuple[list[dict], Optional[int], bool]:
    """
    Apply collection profile to filter scan steps.
    
    Args:
        steps: Original scan plan steps
        manufacturer: Vehicle manufacturer
        model: Vehicle model
        force_full_scan: Skip profile and do full scan
        scan_count: Total scans for this model (for Nth-scan sampling)
        
    Returns:
        (filtered_steps, profile_id, was_full_scan)
    """
    # Force full scan bypasses profile
    if force_full_scan:
        return steps, None, True
    
    profile = get_active_profile(manufacturer, model)
    
    # No profile, do full scan
    if not profile:
        return steps, None, True
    
    # Check Nth-scan sampling
    if profile.full_rescan_interval > 0:
        if scan_count % profile.full_rescan_interval == 0:
            # This is the Nth scan, force full rescan sample
            return steps, profile.id, True
    
    # Apply profile
    whitelist = get_whitelisted_signals()
    filtered_steps = [
        step for step in steps
        if should_include_step(step, profile, whitelist)
    ]
    
    return filtered_steps, profile.id, False


def update_usage_stats(
    manufacturer: str,
    model: Optional[str],
    requested_signals: list[dict],
    response_data: dict
):
    """
    Update usage statistics from scan results.
    
    Args:
        manufacturer: Vehicle manufacturer  
        model: Vehicle model
        requested_signals: List of requested signal dicts
        response_data: Scan response data with timing and decoded info
    """
    now = datetime.now(timezone.utc)
    
    for signal in requested_signals:
        signal_id = _step_to_signal_id(signal)
        if not signal_id:
            continue
        
        # Get or create stats
        stat = db.session.execute(
            select(SignalUsageStats).where(
                SignalUsageStats.manufacturer == manufacturer,
                SignalUsageStats.model == model,
                SignalUsageStats.signal_identifier == signal_id
            )
        ).scalar_one_or_none()
        
        if not stat:
            stat = SignalUsageStats(
                manufacturer=manufacturer,
                model=model,
                signal_identifier=signal_id,
                requested_count=0,
                responded_count=0,
                decoded_count=0
            )
            db.session.add(stat)
        
        # Update counts
        stat.requested_count += 1
        stat.last_seen_at = now
        
        # Check if responded
        signal_key = signal.get('id') or signal.get('command')
        if signal_key and response_data.get(signal_key):
            stat.responded_count += 1
            
            # Check if decoded successfully
            response = response_data[signal_key]
            if response.get('decoded') or response.get('value'):
                stat.decoded_count += 1
            
            # Update response time
            if response.get('elapsed_ms'):
                elapsed = response['elapsed_ms']
                stat.total_response_time_ms += elapsed
                stat.avg_response_time_ms = stat.total_response_time_ms / stat.responded_count
    
    db.session.commit()
