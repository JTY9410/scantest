"""Quality signal collection after each scan (v2.2.22 Phase 1).

Collects structured quality signals: decode failures, unmeasurable items,
out-of-range values, SOH reasons, contradictions, consistency score,
excluded steps, and DTC status-unknown counts.
"""
from datetime import datetime, timezone

from app.extensions import db
from app.modules.ml_quality.models import ScanQualitySignal


def collect_quality_signals(scan, result: dict) -> ScanQualitySignal:
    """Collect structured quality signals from scan result.
    
    Args:
        scan: Scan model instance
        result: Scan result dict from scanner service
    
    Returns:
        ScanQualitySignal instance (not yet committed)
    """
    signals = ScanQualitySignal(
        scan_id=scan.id,
        collected_at=datetime.now(timezone.utc)
    )
    
    # Decode failures: collect from errors
    decode_failures = {}
    for error in result.get("errors") or []:
        if error.get("type") == "decode_error":
            did = error.get("did")
            reason = error.get("message") or "Unknown decode error"
            if did:
                decode_failures[did] = reason
    if decode_failures:
        signals.decode_failures = decode_failures
    
    # Unmeasurable items: extract from ML features if present
    bms_data = scan.bms_data or {}
    ml_features = bms_data.get("ml_features") or {}
    unmeasurable = ml_features.get("unmeasurable_items")
    if unmeasurable:
        signals.unmeasurable_items = unmeasurable
    
    # Out-of-range values: extract from errors
    out_of_range = {}
    for error in result.get("errors") or []:
        if error.get("type") == "out_of_range":
            signal = error.get("signal")
            if signal:
                out_of_range[signal] = {
                    "value": error.get("value"),
                    "range": error.get("range")
                }
    if out_of_range:
        signals.out_of_range_values = out_of_range
    
    # SOH unavailable reason
    if not scan.soh_pct and scan.soh_message:
        signals.soh_unavailable_reason = scan.soh_message
    
    # Consistency score (if available in bms_data)
    consistency = bms_data.get("consistency_score")
    if consistency is not None:
        signals.consistency_score = consistency
    
    # Excluded steps: collect steps that were skipped
    excluded = []
    for step in result.get("steps") or []:
        if step.get("excluded"):
            excluded.append({
                "command": step.get("command"),
                "reason": step.get("exclude_reason")
            })
    if excluded:
        signals.excluded_steps = excluded
    
    # DTC status-unknown count: count DTCs without status_class
    dtc_unknown = 0
    for dtc in result.get("dtcs") or []:
        if not dtc.get("status"):  # No status byte available
            dtc_unknown += 1
    if dtc_unknown > 0:
        signals.dtc_status_unknown_count = dtc_unknown
    
    # Contradictions: look for conflicting values
    contradictions = []
    # Example: SOC vs voltage contradiction
    wescan = result.get("wescan") or {}
    soc = wescan.get("soc")
    voltage = wescan.get("pack_voltage")
    if soc is not None and voltage is not None:
        # Very basic contradiction detection
        # (In production, this would use proper logic)
        if soc > 90 and voltage < 300:  # Example threshold
            contradictions.append({
                "field1": "soc",
                "field2": "pack_voltage",
                "reason": f"High SOC ({soc}%) with low voltage ({voltage}V)"
            })
    if contradictions:
        signals.contradictions = contradictions
    
    return signals
