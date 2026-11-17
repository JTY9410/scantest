"""v2.2.28 force_full_scan feature tests."""

import pytest

from app.extensions import db
from app.modules.scans.models import Scan
from app.modules.adaptive_collection.models import (
    CollectionProfile,
    ProfileStatus
)


class TestScanModelFields:
    """Test scan model has required fields."""
    
    def test_force_full_scan_columns_exist(self, app):
        """Scan model has force_full_scan columns."""
        from sqlalchemy import inspect
        
        with app.app_context():
            mapper = inspect(Scan)
            column_names = [c.key for c in mapper.columns]
            
            assert 'force_full_scan' in column_names
            assert 'was_full_scan' in column_names
            assert 'is_rescan_sample' in column_names
            assert 'collection_profile_id' in column_names
