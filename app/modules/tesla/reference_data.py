"""Tesla battery reference capacity seed data.

DEPRECATED: This hardcoded seed function is deprecated. All Tesla reference data
should come from the xlsx import (data/battery_reference/tesla_vin_pack_db.xlsx).

The seed_tesla_reference_data() function is kept only for backward compatibility
with existing tests and CLI commands, but it no longer inserts any rows.

All battery reference data is now managed through:
- data/battery_reference/*.xlsx files (single source of truth)
- flask battery-ref-seed command (idempotent import from xlsx)
- Automatic seed on app startup via battery_ref_seed.py
"""

from app.extensions import db
from app.modules.scans.battery_capacity import BatteryReferenceCapacity


# DEPRECATED: Hardcoded data is no longer used. Kept for reference only.
# All Tesla battery data is now in data/battery_reference/tesla_vin_pack_db.xlsx
TESLA_REFERENCE_DATA = []


def seed_tesla_reference_data():
    """DEPRECATED: No-op function for backward compatibility.
    
    This function no longer inserts any rows. All battery reference data
    comes from xlsx imports via flask battery-ref-seed.
    
    Kept for backward compatibility with existing CLI commands and tests.
    """
    # Do nothing - all data comes from xlsx imports now
    pass
