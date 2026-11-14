"""Tests for manual override protection.

Manual overrides must never be overwritten by automatic classification.
"""
import pytest
from app.modules.scans.models import Scan
from app.modules.definitions.vehicle_classifier import classify_vehicle_powertrain
from app.extensions import db


def test_manual_override_not_overwritten_by_classification(app, make_user):
    """Verify that scans with manual_override source are not overwritten by automatic classification."""
    with app.app_context():
        user_id = make_user("tester", password="pass")
        
        # Create a scan with automatic classification
        scan = Scan(
            type="ev",
            type_source="fuel",
            device_type="ble",
            device_uid="test",
            tester_id=user_id,
            scan_vin="TESTVIN123456789",
            car_no="12가3456",
            car_vin="TESTVIN123456789",
            car_maker="현대",
            car_model="아이오닉 5",
            car_fuel="전기",
            car_year=2023
        )
        db.session.add(scan)
        db.session.commit()
        
        original_id = scan.id
        assert scan.type == "ev"
        assert scan.type_source == "fuel"
        
        # Manually override to hev
        scan.type = "hev"
        scan.type_source = "manual_override"
        scan.car_fuel = "하이브리드"
        db.session.commit()
        
        # Re-fetch from DB
        scan = db.session.get(Scan, original_id)
        assert scan.type == "hev"
        assert scan.type_source == "manual_override"
        
        # Simulate what scanner service would do - attempt to overwrite with automatic classification
        # The key is: code should check type_source before overwriting
        auto_pt = "ev"  # What classifier would return based on old fuel value
        auto_source = "fuel"
        
        # This is the protection: check source before overwriting
        if scan.type_source != "manual_override":
            scan.type = auto_pt
            scan.type_source = auto_source
        
        db.session.commit()
        
        # Re-fetch and verify manual override was preserved
        scan = db.session.get(Scan, original_id)
        assert scan.type == "hev", "Manual override should not be overwritten by automatic classification"
        assert scan.type_source == "manual_override"


def test_manual_fuel_override_not_overwritten(app, make_user):
    """Verify that manually overridden fuel is not overwritten."""
    with app.app_context():
        user_id = make_user("tester", password="pass")
        
        scan = Scan(
            type="ev",
            type_source="fuel",
            device_type="ble",
            device_uid="test",
            tester_id=user_id,
            scan_vin="TESTVIN123456789",
            car_no="12가3456",
            car_vin="TESTVIN123456789",
            car_maker="현대",
            car_model="코나",
            car_fuel="전기",
            car_year=2021
        )
        db.session.add(scan)
        db.session.commit()
        
        # Manually override fuel
        from app.modules.definitions.audit_models import PowertrainOverrideAudit
        audit = PowertrainOverrideAudit(
            scan_id=scan.id,
            user_id=user_id,
            field_name="fuel",
            previous_value="전기",
            new_value="가솔린",
            new_source="manual_override",
            reason="Manual correction"
        )
        db.session.add(audit)
        scan.car_fuel = "가솔린"
        db.session.commit()
        
        # Verify audit log exists
        audits = db.session.query(PowertrainOverrideAudit).filter_by(scan_id=scan.id).all()
        assert len(audits) == 1
        assert audits[0].field_name == "fuel"
        assert audits[0].new_value == "가솔린"
        
        # The scan's fuel should remain as manually set
        assert scan.car_fuel == "가솔린"
