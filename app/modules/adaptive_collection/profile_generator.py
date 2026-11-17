"""Collection profile generation logic (v2.2.24 Phase 3)."""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func

from app.extensions import db
from app.modules.adaptive_collection.models import (
    SignalUsageStats,
    CollectionProfile,
    SignalWhitelist,
    ProfileStatus
)


def generate_collection_profile(
    manufacturer: str,
    model: Optional[str] = None,
    skip_threshold_scans: int = 20,
    full_rescan_interval: int = 10
) -> Optional[CollectionProfile]:
    """
    Generate a collection profile based on usage statistics.
    
    Args:
        manufacturer: Vehicle manufacturer
        model: Vehicle model (None = manufacturer-level)
        skip_threshold_scans: Minimum scans before considering skip
        full_rescan_interval: Every Nth scan is a full rescan
    
    Returns:
        CollectionProfile (draft status, not yet saved) or None if no candidates
    """
    # Get usage stats for this scope
    query = select(SignalUsageStats).where(
        SignalUsageStats.manufacturer == manufacturer,
        SignalUsageStats.model == model
    )
    
    stats = db.session.execute(query).scalars().all()
    
    if not stats:
        return None
    
    # Get active whitelist
    whitelist_query = select(SignalWhitelist).where(
        SignalWhitelist.is_active == True
    )
    whitelisted_signals = {
        w.signal_identifier for w in db.session.execute(whitelist_query).scalars().all()
    }
    
    # Identify signals to skip
    signals_to_skip = []
    evidence = {
        'total_signals_analyzed': len(stats),
        'whitelisted_signals_protected': len(whitelisted_signals),
        'skip_candidates': []
    }
    
    for stat in stats:
        # Never skip whitelisted signals
        if stat.signal_identifier in whitelisted_signals:
            continue
        
        # Check if signal meets skip criteria
        if stat.requested_count < skip_threshold_scans:
            continue  # Not enough data yet
        
        # Skip if:
        # 1. Never responded
        # 2. Never decoded
        # 3. Never used in any context
        should_skip = (
            stat.responded_count == 0 or
            stat.decoded_count == 0 or
            (stat.used_in_report_count == 0 and
             stat.used_in_soh_count == 0 and
             stat.used_in_verdict_count == 0 and
             stat.used_in_ml_quality_count == 0 and
             stat.used_in_soh_inference_count == 0)
        )
        
        if should_skip:
            signals_to_skip.append(stat.signal_identifier)
            evidence['skip_candidates'].append({
                'signal': stat.signal_identifier,
                'requested': stat.requested_count,
                'responded': stat.responded_count,
                'decoded': stat.decoded_count,
                'used_total': (stat.used_in_report_count + 
                             stat.used_in_soh_count + 
                             stat.used_in_verdict_count +
                             stat.used_in_ml_quality_count +
                             stat.used_in_soh_inference_count)
            })
    
    if not signals_to_skip:
        return None
    
    # Generate version
    model_suffix = f"-{model}" if model else ""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    version = f"profile-{manufacturer}{model_suffix}-{timestamp}"
    
    # Create draft profile
    profile = CollectionProfile(
        version=version,
        status=ProfileStatus.DRAFT.value,
        manufacturer=manufacturer,
        model=model,
        skip_threshold_scans=skip_threshold_scans,
        full_rescan_interval=full_rescan_interval,
        signals_to_skip=signals_to_skip,
        generation_evidence=evidence
    )
    
    return profile


def check_reenable_signals(
    manufacturer: str,
    model: Optional[str] = None,
    profile_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Check if any skipped signals should be re-enabled.
    
    Analyzes recent usage of signals that are currently skipped
    to detect if they've become useful.
    
    Returns:
        List of reenable proposals with evidence
    """
    if not profile_id:
        # Find active profile for this scope
        profile = db.session.execute(
            select(CollectionProfile).where(
                CollectionProfile.manufacturer == manufacturer,
                CollectionProfile.model == model,
                CollectionProfile.status == ProfileStatus.APPROVED.value
            ).order_by(CollectionProfile.approved_at.desc())
        ).scalar_one_or_none()
        
        if not profile:
            return []
        
        profile_id = profile.id
    else:
        profile = db.session.get(CollectionProfile, profile_id)
    
    if not profile or not profile.signals_to_skip:
        return []
    
    proposals = []
    
    # Check each skipped signal
    for signal_id in profile.signals_to_skip:
        stat = db.session.execute(
            select(SignalUsageStats).where(
                SignalUsageStats.manufacturer == manufacturer,
                SignalUsageStats.model == model,
                SignalUsageStats.signal_identifier == signal_id
            )
        ).scalar_one_or_none()
        
        if not stat:
            continue
        
        # Propose re-enable if:
        # - Now responding and decoded
        # - Being used in at least one context
        is_responding = stat.responded_count > 0 and stat.decoded_count > 0
        is_used = (stat.used_in_report_count > 0 or
                  stat.used_in_soh_count > 0 or
                  stat.used_in_verdict_count > 0 or
                  stat.used_in_ml_quality_count > 0 or
                  stat.used_in_soh_inference_count > 0)
        
        if is_responding and is_used:
            proposals.append({
                'signal': signal_id,
                'responded_count': stat.responded_count,
                'decoded_count': stat.decoded_count,
                'usage': {
                    'report': stat.used_in_report_count,
                    'soh': stat.used_in_soh_count,
                    'verdict': stat.used_in_verdict_count,
                    'ml_quality': stat.used_in_ml_quality_count,
                    'soh_inference': stat.used_in_soh_inference_count
                },
                'last_seen': stat.last_seen_at.isoformat() if stat.last_seen_at else None
            })
    
    return proposals
