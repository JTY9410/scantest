"""Auto-seed battery reference capacity data on startup."""

import os
from pathlib import Path
from flask import current_app
from app.extensions import db
from app.modules.scans.battery_capacity import BatteryReferenceCapacity


def should_seed_battery_references() -> bool:
    """Check if battery reference data needs seeding."""
    count = db.session.query(BatteryReferenceCapacity).count()
    return count == 0


def seed_battery_references():
    """Idempotently import battery reference data from xlsx files."""
    if not should_seed_battery_references():
        current_app.logger.info("Battery reference data already seeded, skipping")
        return
    
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
    from app.cli.battery_ref_import import import_battery_reference
    
    for xlsx_path in xlsx_files:
        try:
            current_app.logger.info(f"Importing {xlsx_path.name}...")
            rows_imported = import_battery_reference(str(xlsx_path), clear=False)
            current_app.logger.info(f"✓ Imported {rows_imported} rows from {xlsx_path.name}")
        except Exception as exc:
            current_app.logger.error(f"Failed to import {xlsx_path.name}: {exc}", exc_info=True)
    
    total = db.session.query(BatteryReferenceCapacity).count()
    current_app.logger.info(f"Battery reference seeding complete: {total} total rows")
