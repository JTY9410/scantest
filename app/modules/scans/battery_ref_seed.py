"""Auto-seed battery reference capacity data on startup."""

import os
from pathlib import Path
from flask import current_app
from app.extensions import db
from app.modules.scans.battery_capacity import BatteryReferenceCapacity


def should_seed_battery_references() -> bool:
    """Check if battery reference data needs seeding.
    
    Checks for:
    - Empty table
    - Old-format rows (no source_file) that need migrating
    - Rows with NULL capacity (invalid references)
    - Insufficient row count
    """
    total_count = db.session.query(BatteryReferenceCapacity).count()
    if total_count == 0:
        return True
    
    # Check if old-format rows exist (rows without source_file - from v2.2.8)
    # or manual rows (source_file='manual') that shouldn't be in the catalog
    from sqlalchemy import or_
    bad_source_count = db.session.query(BatteryReferenceCapacity).filter(
        or_(
            BatteryReferenceCapacity.source_file.is_(None),
            BatteryReferenceCapacity.source_file == 'manual'
        )
    ).count()
    
    if bad_source_count > 0:
        current_app.logger.info(f"Found {bad_source_count} non-xlsx rows (old-format or manual), will re-import")
        return True
    
    # Check for invalid rows with ALL capacity columns NULL (unusable for SOH calculations)
    from sqlalchemy import and_
    null_capacity_count = db.session.query(BatteryReferenceCapacity).filter(
        and_(
            BatteryReferenceCapacity.gross_capacity_kwh.is_(None),
            BatteryReferenceCapacity.net_capacity_kwh.is_(None),
            BatteryReferenceCapacity.official_capacity_kwh.is_(None)
        )
    ).count()
    
    if null_capacity_count > 0:
        current_app.logger.info(f"Found {null_capacity_count} rows with NULL capacity, will re-import")
        return True
    
    # Check if we have the expected count (221 valid rows after filtering)
    if total_count < 221:
        current_app.logger.info(f"Found only {total_count} rows, expected 221, will re-import")
        return True
    
    return False


def seed_battery_references():
    """Idempotently import battery reference data from xlsx files.
    
    Handles:
    - Empty table
    - Old-format rows from v2.2.8 (no source_file) - deletes and re-imports
    - Partial data - fills in missing rows
    """
    if not should_seed_battery_references():
        total = db.session.query(BatteryReferenceCapacity).count()
        current_app.logger.info(f"Battery reference data already complete ({total} rows), skipping")
        return
    
    # Delete old-format rows, manual rows, and rows with ALL capacity columns NULL
    from sqlalchemy import or_, and_
    bad_rows = db.session.query(BatteryReferenceCapacity).filter(
        or_(
            BatteryReferenceCapacity.source_file.is_(None),
            BatteryReferenceCapacity.source_file == 'manual',
            and_(
                BatteryReferenceCapacity.gross_capacity_kwh.is_(None),
                BatteryReferenceCapacity.net_capacity_kwh.is_(None),
                BatteryReferenceCapacity.official_capacity_kwh.is_(None)
            )
        )
    ).delete()
    if bad_rows > 0:
        db.session.commit()
        current_app.logger.info(f"Removed {bad_rows} non-xlsx or NULL-capacity rows")
    
    current_app.logger.info("Seeding battery reference capacity data...")
    
    # Find xlsx files in data/battery_reference/
    data_dir = Path(__file__).parent.parent.parent.parent / 'data' / 'battery_reference'
    
    if not data_dir.exists():
        current_app.logger.warning(f"Battery reference data directory not found: {data_dir}")
        return
    
    xlsx_files = list(data_dir.glob('*.xlsx'))
    
    if not xlsx_files:
        current_app.logger.warning(f"No xlsx files found in {data_dir}")
        return
    
    # Parse all files (pure function, no DB)
    from app.modules.scans.battery_ref_parser import parse_reference_rows
    
    current_app.logger.info(f"Parsing {len(xlsx_files)} xlsx files...")
    parsed_rows = parse_reference_rows(xlsx_files)
    
    current_app.logger.info(f"Parsed {len(parsed_rows)} rows from xlsx files")
    
    # One transaction: DELETE old data, INSERT new data (idempotent by construction)
    try:
        # Delete all existing reference data (old formats + current formats)
        deleted = db.session.query(BatteryReferenceCapacity).filter(
            or_(
                BatteryReferenceCapacity.source_file.in_(['tesla', 'import7', 'manual']),
                BatteryReferenceCapacity.source_file.is_(None)
            )
        ).delete()
        current_app.logger.info(f"Deleted {deleted} old reference rows")
        
        # Bulk insert all parsed rows (no deduplication)
        if parsed_rows:
            db.session.bulk_insert_mappings(BatteryReferenceCapacity, parsed_rows)
        
        db.session.commit()
        current_app.logger.info(f"✓ Battery reference seeding complete: {len(parsed_rows)} rows")
        
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(f"Failed to seed battery references: {exc}", exc_info=True)
        raise
