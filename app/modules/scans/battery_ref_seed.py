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
    old_format_count = db.session.query(BatteryReferenceCapacity).filter(
        BatteryReferenceCapacity.source_file.is_(None)
    ).count()
    
    if old_format_count > 0:
        current_app.logger.info(f"Found {old_format_count} old-format rows, will re-import")
        return True
    
    # Check for invalid rows with NULL capacity (unusable for SOH calculations)
    from sqlalchemy import or_
    null_capacity_count = db.session.query(BatteryReferenceCapacity).filter(
        or_(
            BatteryReferenceCapacity.gross_capacity_kwh.is_(None),
            BatteryReferenceCapacity.net_capacity_kwh.is_(None)
        )
    ).count()
    
    if null_capacity_count > 0:
        current_app.logger.info(f"Found {null_capacity_count} rows with NULL capacity, will re-import")
        return True
    
    # Check if we have the expected count (223 importable rows)
    if total_count < 223:
        current_app.logger.info(f"Found only {total_count} rows, expected 223, will re-import")
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
    
    # Delete old-format rows and rows with NULL capacity
    from sqlalchemy import or_
    bad_rows = db.session.query(BatteryReferenceCapacity).filter(
        or_(
            BatteryReferenceCapacity.source_file.is_(None),
            BatteryReferenceCapacity.gross_capacity_kwh.is_(None),
            BatteryReferenceCapacity.net_capacity_kwh.is_(None)
        )
    ).delete()
    if bad_rows > 0:
        db.session.commit()
        current_app.logger.info(f"Removed {bad_rows} old-format or NULL-capacity rows")
    
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
    
    # Import each xlsx file
    from app.modules.scans.battery_ref_import import import_battery_reference
    
    for xlsx_path in xlsx_files:
        try:
            current_app.logger.info(f"Importing {xlsx_path.name}...")
            rows_imported = import_battery_reference(str(xlsx_path), clear=False)
            current_app.logger.info(f"✓ Imported {rows_imported} rows from {xlsx_path.name}")
        except Exception as exc:
            current_app.logger.error(f"Failed to import {xlsx_path.name}: {exc}", exc_info=True)
    
    total = db.session.query(BatteryReferenceCapacity).count()
    current_app.logger.info(f"Battery reference seeding complete: {total} total rows")
