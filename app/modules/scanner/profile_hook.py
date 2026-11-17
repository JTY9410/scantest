"""Hook for applying collection profiles to scans (v2.2.25)."""

from typing import Optional

from app.extensions import db


def apply_profile_if_enabled(
    steps: list[dict],
    car_maker: Optional[str],
    car_model: Optional[str],
    force_full_scan: bool = False
) -> tuple[list[dict], Optional[int], bool]:
    """
    Apply collection profile to scan steps if feature is enabled.
    
    Returns:
        (filtered_steps, profile_id, was_full_scan)
    """
    if not car_maker:
        return steps, None, True
    
    try:
        from app.modules.adaptive_collection.scan_integration import apply_profile_to_plan
        
        # Get scan count for this model
        from app.modules.scans.models import Scan
        from sqlalchemy import select, func
        
        scan_count = db.session.execute(
            select(func.count()).select_from(Scan).where(
                Scan.car_maker == car_maker,
                Scan.car_model == car_model
            )
        ).scalar() or 0
        
        return apply_profile_to_plan(
            steps,
            car_maker,
            car_model,
            force_full_scan=force_full_scan,
            scan_count=scan_count + 1  # +1 for current scan
        )
    except Exception:
        # If anything fails, fall back to full scan
        return steps, None, True


def record_usage_if_enabled(
    car_maker: Optional[str],
    car_model: Optional[str],
    requested_steps: list[dict],
    responses: dict
):
    """Record signal usage statistics if feature is enabled."""
    if not car_maker:
        return
    
    try:
        from app.modules.adaptive_collection.scan_integration import update_usage_stats
        update_usage_stats(car_maker, car_model, requested_steps, responses)
    except Exception:
        # Silently fail - don't break scans if stats recording fails
        pass
