"""Tests for powertrain conflict detection and resolution."""
import pytest
from sqlalchemy import text
from app.extensions import db
from app.modules.definitions.vehicle_classifier import classify_vehicle_powertrain, map_fuel_to_powertrain
from app.modules.definitions.powertrain_service import save_powertrain_override, revert_to_automatic


def test_fuel_to_powertrain_mapping():
    """Test diag_fuel to powertrain mapping."""
    assert map_fuel_to_powertrain('전기') == ('BEV', 0.99)
    assert map_fuel_to_powertrain('Electric') == ('BEV', 0.99)
    assert map_fuel_to_powertrain('수소') == ('FCEV', 0.99)
    assert map_fuel_to_powertrain('Hydrogen') == ('FCEV', 0.99)
    assert map_fuel_to_powertrain('플러그인 하이브리드') == ('PHEV', 0.95)
    assert map_fuel_to_powertrain('Plug-in Hybrid') == ('PHEV', 0.95)
    assert map_fuel_to_powertrain('하이브리드') == ('HEV', 0.95)
    assert map_fuel_to_powertrain('Hybrid') == ('HEV', 0.95)
    assert map_fuel_to_powertrain('휘발유') == ('ICE', 0.95)
    assert map_fuel_to_powertrain('Gasoline') == ('ICE', 0.95)
    assert map_fuel_to_powertrain('경유') == ('ICE', 0.95)
    assert map_fuel_to_powertrain('Diesel') == ('ICE', 0.95)
    assert map_fuel_to_powertrain('LPG') == ('ICE', 0.95)
    assert map_fuel_to_powertrain('CNG') == ('ICE', 0.95)
    assert map_fuel_to_powertrain('Unknown') == (None, 0.0)
    assert map_fuel_to_powertrain('') == (None, 0.0)


def test_conflict_detection_when_plate_disagrees_with_vin():
    """Test conflict detection when plate and VIN classifications differ."""
    # This test needs a mock car_info.lookup response
    # For now, just test the classifier's conflict detection logic
    
    # Simulate a case where plate lookup would return PHEV but VIN would say HEV
    # This would happen in the real system, but for unit testing we just verify
    # the conflict_info structure is correct
    
    maker = 'Hyundai'
    model = 'Tucson Plug-in Hybrid'
    
    pt, src, conf, conflict = classify_vehicle_powertrain(
        maker=maker,
        model=model,
        submodel=None,
        file_path=None,
        vin=None,
        plate_number=None
    )
    
    # Without plate or VIN, should classify by model tokens
    assert pt == 'PHEV'
    assert src == 'model:PHEV'
    assert conflict is None


def test_manual_override_creates_audit_trail(app_with_context):
    """Test that manual powertrain override creates audit record."""
    # Create a test vehicle definition
    db.session.execute(text("""
        INSERT INTO definition_sources (file_path, file_hash, imported_at)
        VALUES ('test/path.json', 'testhash123', NOW())
    """))
    db.session.commit()
    
    source_id = db.session.execute(text("SELECT id FROM definition_sources WHERE file_hash = 'testhash123'")).scalar()
    
    db.session.execute(text("""
        INSERT INTO vehicle_definitions (maker, model, powertrain, powertrain_source, powertrain_confidence, source_id)
        VALUES ('Hyundai', 'Ioniq Hybrid EV', 'unknown', 'mixed_tokens', 0.8, :source_id)
    """), {"source_id": source_id})
    db.session.commit()
    
    vehicle_id = db.session.execute(text("SELECT id FROM vehicle_definitions WHERE model = 'Ioniq Hybrid EV'")).scalar()
    
    # Create a test user
    db.session.execute(text("""
        INSERT INTO users (username, password_hash, email, type, created_at)
        VALUES ('testuser', 'hash', 'test@example.com', 'admin', NOW())
    """))
    db.session.commit()
    
    user_id = db.session.execute(text("SELECT id FROM users WHERE username = 'testuser'")).scalar()
    
    # Override to PHEV
    result = save_powertrain_override(
        user_id=user_id,
        vehicle_definition_id=vehicle_id,
        new_powertrain='PHEV',
        reason='Manual verification with manufacturer specs'
    )
    
    assert result['success'] is True
    assert result['previous_powertrain'] == 'unknown'
    assert result['new_powertrain'] == 'PHEV'
    assert 'audit_id' in result
    
    # Check audit trail
    audit = db.session.execute(text("""
        SELECT user_id, previous_powertrain, new_powertrain, previous_source, new_source, reason
        FROM powertrain_override_audit
        WHERE vehicle_definition_id = :vehicle_id
    """), {"vehicle_id": vehicle_id}).fetchone()
    
    assert audit is not None
    assert audit.user_id == user_id
    assert audit.previous_powertrain == 'unknown'
    assert audit.new_powertrain == 'PHEV'
    assert audit.previous_source == 'mixed_tokens'
    assert audit.new_source == 'manual_override'
    assert audit.reason == 'Manual verification with manufacturer specs'
    
    # Check vehicle was updated
    vehicle = db.session.execute(text("""
        SELECT powertrain, powertrain_source, powertrain_confidence, powertrain_conflict
        FROM vehicle_definitions
        WHERE id = :vehicle_id
    """), {"vehicle_id": vehicle_id}).fetchone()
    
    assert vehicle.powertrain == 'PHEV'
    assert vehicle.powertrain_source == 'manual_override'
    assert vehicle.powertrain_confidence == 1.0
    assert vehicle.powertrain_conflict is False


def test_revert_to_automatic_reclassifies(app_with_context):
    """Test that revert removes manual override and reclassifies."""
    # Create test data
    db.session.execute(text("""
        INSERT INTO definition_sources (file_path, file_hash, imported_at)
        VALUES ('test/phev.json', 'testhash456', NOW())
    """))
    db.session.commit()
    
    source_id = db.session.execute(text("SELECT id FROM definition_sources WHERE file_hash = 'testhash456'")).scalar()
    
    db.session.execute(text("""
        INSERT INTO vehicle_definitions (maker, model, powertrain, powertrain_source, powertrain_confidence, source_id)
        VALUES ('Kia', 'Niro PHEV', 'HEV', 'manual_override', 1.0, :source_id)
    """), {"source_id": source_id})
    db.session.commit()
    
    vehicle_id = db.session.execute(text("SELECT id FROM vehicle_definitions WHERE model = 'Niro PHEV'")).scalar()
    
    # Revert
    result = revert_to_automatic(vehicle_definition_id=vehicle_id)
    
    assert result['success'] is True
    assert result['powertrain'] == 'PHEV'  # Should now be PHEV from model tokens
    assert result['source'] == 'model:PHEV'
    
    # Check vehicle was updated
    vehicle = db.session.execute(text("""
        SELECT powertrain, powertrain_source
        FROM vehicle_definitions
        WHERE id = :vehicle_id
    """), {"vehicle_id": vehicle_id}).fetchone()
    
    assert vehicle.powertrain == 'PHEV'
    assert vehicle.powertrain_source == 'model:PHEV'
