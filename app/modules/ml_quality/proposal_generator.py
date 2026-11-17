"""Improvement proposal generation (v2.2.22 Phase 1).

Rule-based proposal generation by default.
AI-assisted only if AI key is configured, using masked aggregated data.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func

from app.extensions import db
from app.modules.ml_quality.models import ScanQualitySignal, ImprovementProposal
from app.modules.scans.models import Scan


# Configurable thresholds
MIN_SAMPLE_COUNT = 10  # Minimum number of scans to detect a pattern
MIN_PATTERN_FREQUENCY = 0.7  # 70% occurrence rate to be considered a pattern


def generate_proposals(manufacturer: str | None = None, model: str | None = None) -> list[ImprovementProposal]:
    """Generate improvement proposals based on quality signals.
    
    Analyzes quality signals and generates rule-based proposals for recurring patterns.
    
    Args:
        manufacturer: Filter by manufacturer (None = all)
        model: Filter by model (None = all)
    
    Returns:
        List of generated proposals (not yet committed)
    """
    proposals = []
    
    # Aggregate quality signals by manufacturer/model
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    
    # Use group_concat for SQLite, array_agg for PostgreSQL
    is_sqlite = db.engine.name == 'sqlite'
    if is_sqlite:
        signal_ids_expr = func.group_concat(ScanQualitySignal.id).label('signal_ids')
    else:
        signal_ids_expr = func.array_agg(ScanQualitySignal.id).label('signal_ids')
    
    query = (
        select(
            Scan.car_maker,
            Scan.car_model,
            func.count(ScanQualitySignal.id).label('signal_count'),
            signal_ids_expr
        )
        .join(Scan, ScanQualitySignal.scan_id == Scan.id)
        .where(ScanQualitySignal.collected_at >= recent_cutoff)
        .group_by(Scan.car_maker, Scan.car_model)
        .having(func.count(ScanQualitySignal.id) >= MIN_SAMPLE_COUNT)
    )
    
    if manufacturer:
        query = query.where(Scan.car_maker == manufacturer)
    if model:
        query = query.where(Scan.car_model == model)
    
    aggregates = db.session.execute(query).all()
    
    for agg in aggregates:
        maker, car_model, count, signal_ids_raw = agg
        # Convert signal_ids from string (SQLite) or list (PostgreSQL) to list of ints
        if is_sqlite and isinstance(signal_ids_raw, str):
            signal_ids = [int(x) for x in signal_ids_raw.split(',')]
        else:
            signal_ids = signal_ids_raw
        
        # Analyze decode failures
        decode_proposal = _analyze_decode_failures(maker, car_model, signal_ids, count)
        if decode_proposal:
            proposals.append(decode_proposal)
        
        # Analyze unmeasurable items
        unmeasurable_proposal = _analyze_unmeasurable_items(maker, car_model, signal_ids, count)
        if unmeasurable_proposal:
            proposals.append(unmeasurable_proposal)
        
        # Analyze SOH unavailable reasons
        soh_proposal = _analyze_soh_unavailable(maker, car_model, signal_ids, count)
        if soh_proposal:
            proposals.append(soh_proposal)
    
    return proposals


def _analyze_decode_failures(manufacturer: str, model: str, signal_ids: list, total_count: int) -> ImprovementProposal | None:
    """Analyze decode failures and generate proposal if pattern found."""
    # Query all decode failures for these signals
    signals = db.session.execute(
        select(ScanQualitySignal)
        .where(ScanQualitySignal.id.in_(signal_ids))
        .where(ScanQualitySignal.decode_failures.isnot(None))
    ).scalars().all()
    
    if not signals:
        return None
    
    # Count failures by DID
    failures_by_did = defaultdict(lambda: {"count": 0, "reasons": set(), "scan_ids": []})
    for signal in signals:
        for did, reason in (signal.decode_failures or {}).items():
            failures_by_did[did]["count"] += 1
            failures_by_did[did]["reasons"].add(reason)
            failures_by_did[did]["scan_ids"].append(signal.scan_id)
    
    # Find recurring failures (>= 70% occurrence)
    recurring_failures = {}
    for did, data in failures_by_did.items():
        frequency = data["count"] / total_count
        if frequency >= MIN_PATTERN_FREQUENCY:
            recurring_failures[did] = {
                "count": data["count"],
                "frequency": f"{frequency:.1%}",
                "reasons": list(data["reasons"]),
                "scan_ids": data["scan_ids"][:10]  # Sample of scan IDs
            }
    
    if not recurring_failures:
        return None
    
    # Generate proposal
    proposal = ImprovementProposal(
        status="pending",
        manufacturer=manufacturer,
        model=model,
        proposal_type="decoder_mapping",
        evidence={
            "pattern": "recurring_decode_failures",
            "sample_size": total_count,
            "failures": recurring_failures
        },
        config_delta={
            "action": "add_decoder_mappings",
            "dids": list(recurring_failures.keys()),
            "details": recurring_failures
        },
        expected_effect=f"Reduce decode failures for {len(recurring_failures)} DIDs occurring in {MIN_PATTERN_FREQUENCY:.0%}+ of scans",
        generation_method="rule_based"
    )
    
    return proposal


def _analyze_unmeasurable_items(manufacturer: str, model: str, signal_ids: list, total_count: int) -> ImprovementProposal | None:
    """Analyze unmeasurable items and generate proposal if pattern found."""
    signals = db.session.execute(
        select(ScanQualitySignal)
        .where(ScanQualitySignal.id.in_(signal_ids))
        .where(ScanQualitySignal.unmeasurable_items.isnot(None))
    ).scalars().all()
    
    if not signals:
        return None
    
    # Count unmeasurable by item
    unmeasurable_by_item = defaultdict(lambda: {"count": 0, "reasons": set(), "scan_ids": []})
    for signal in signals:
        for item, reason in (signal.unmeasurable_items or {}).items():
            unmeasurable_by_item[item]["count"] += 1
            unmeasurable_by_item[item]["reasons"].add(str(reason))
            unmeasurable_by_item[item]["scan_ids"].append(signal.scan_id)
    
    # Find recurring unmeasurable items
    recurring_unmeasurable = {}
    for item, data in unmeasurable_by_item.items():
        frequency = data["count"] / total_count
        if frequency >= MIN_PATTERN_FREQUENCY:
            recurring_unmeasurable[item] = {
                "count": data["count"],
                "frequency": f"{frequency:.1%}",
                "reasons": list(data["reasons"]),
                "scan_ids": data["scan_ids"][:10]
            }
    
    if not recurring_unmeasurable:
        return None
    
    proposal = ImprovementProposal(
        status="pending",
        manufacturer=manufacturer,
        model=model,
        proposal_type="measurement_threshold",
        evidence={
            "pattern": "recurring_unmeasurable_items",
            "sample_size": total_count,
            "unmeasurable": recurring_unmeasurable
        },
        config_delta={
            "action": "adjust_measurement_thresholds",
            "items": list(recurring_unmeasurable.keys()),
            "details": recurring_unmeasurable
        },
        expected_effect=f"Improve measurement success for {len(recurring_unmeasurable)} items",
        generation_method="rule_based"
    )
    
    return proposal


def _analyze_soh_unavailable(manufacturer: str, model: str, signal_ids: list, total_count: int) -> ImprovementProposal | None:
    """Analyze SOH unavailable reasons and generate proposal if pattern found."""
    signals = db.session.execute(
        select(ScanQualitySignal)
        .where(ScanQualitySignal.id.in_(signal_ids))
        .where(ScanQualitySignal.soh_unavailable_reason.isnot(None))
    ).scalars().all()
    
    if not signals:
        return None
    
    # Count by reason
    reasons_count = defaultdict(lambda: {"count": 0, "scan_ids": []})
    for signal in signals:
        reason = signal.soh_unavailable_reason
        if reason:
            reasons_count[reason]["count"] += 1
            reasons_count[reason]["scan_ids"].append(signal.scan_id)
    
    # Find dominant reason
    dominant_reason = None
    max_count = 0
    for reason, data in reasons_count.items():
        frequency = data["count"] / total_count
        if frequency >= MIN_PATTERN_FREQUENCY and data["count"] > max_count:
            dominant_reason = reason
            max_count = data["count"]
    
    if not dominant_reason:
        return None
    
    proposal = ImprovementProposal(
        status="pending",
        manufacturer=manufacturer,
        model=model,
        proposal_type="soh_parameter",
        evidence={
            "pattern": "recurring_soh_unavailable",
            "sample_size": total_count,
            "dominant_reason": dominant_reason,
            "count": max_count,
            "frequency": f"{max_count/total_count:.1%}",
            "scan_ids": reasons_count[dominant_reason]["scan_ids"][:10]
        },
        config_delta={
            "action": "adjust_soh_parameters",
            "reason": dominant_reason,
            "manufacturer": manufacturer,
            "model": model
        },
        expected_effect=f"Enable SOH calculation for scans currently failing with: {dominant_reason}",
        generation_method="rule_based"
    )
    
    return proposal
