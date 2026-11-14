"""Powertrain classification and conflict resolution service."""
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy import text
from app.extensions import db
from app.core import audit


def save_powertrain_override(
    user_id: int,
    vehicle_definition_id: Optional[int] = None,
    scan_id: Optional[int] = None,
    new_powertrain: str = None,
    new_fuel: Optional[str] = None,
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """Save manual powertrain override with audit trail.
    
    Args:
        user_id: User making the override
        vehicle_definition_id: Vehicle definition ID (one of this or scan_id required)
        scan_id: Scan ID (one of this or vehicle_definition_id required)
        new_powertrain: New powertrain value (BEV, PHEV, HEV, FCEV, ICE, not_vehicle, unknown)
        new_fuel: Optional new fuel value
        reason: Optional reason for override
    
    Returns:
        Dict with updated record and audit ID
    """
    if not vehicle_definition_id and not scan_id:
        raise ValueError("Either vehicle_definition_id or scan_id required")
    
    if vehicle_definition_id:
        # Get current values
        current = db.session.execute(text("""
            SELECT powertrain, powertrain_source, powertrain_conflict
            FROM vehicle_definitions
            WHERE id = :id
        """), {"id": vehicle_definition_id}).fetchone()
        
        if not current:
            raise ValueError(f"Vehicle definition {vehicle_definition_id} not found")
        
        previous_powertrain = current[0]
        previous_source = current[1]
        
        # Update vehicle_definitions
        db.session.execute(text("""
            UPDATE vehicle_definitions
            SET powertrain = :powertrain,
                powertrain_source = 'manual_override',
                powertrain_confidence = 1.0,
                powertrain_conflict = false
            WHERE id = :id
        """), {
            "id": vehicle_definition_id,
            "powertrain": new_powertrain
        })
        
        # Create audit record
        audit_id = db.session.execute(text("""
            INSERT INTO powertrain_override_audit 
            (vehicle_definition_id, user_id, previous_powertrain, new_powertrain,
             previous_source, new_source, reason, created_at)
            VALUES (:vd_id, :user_id, :prev_pt, :new_pt, :prev_src, :new_src, :reason, NOW())
            RETURNING id
        """), {
            "vd_id": vehicle_definition_id,
            "user_id": user_id,
            "prev_pt": previous_powertrain,
            "new_pt": new_powertrain,
            "prev_src": previous_source,
            "new_src": "manual_override",
            "reason": reason
        }).scalar()
        
        db.session.commit()
        
        return {
            "success": True,
            "audit_id": audit_id,
            "previous_powertrain": previous_powertrain,
            "new_powertrain": new_powertrain
        }
    
    else:  # scan_id
        # Similar logic for scans
        current = db.session.execute(text("""
            SELECT type, type_source, powertrain_conflict
            FROM scans
            WHERE id = :id
        """), {"id": scan_id}).fetchone()
        
        if not current:
            raise ValueError(f"Scan {scan_id} not found")
        
        previous_type = current[0]
        previous_source = current[1]
        
        # Map powertrain to scan type
        type_map = {
            'BEV': 'ev',
            'PHEV': 'hev',
            'HEV': 'hev',
            'FCEV': 'ev',
            'ICE': 'ice',
            'not_vehicle': 'ice',  # fallback
            'unknown': 'ice'  # fallback
        }
        scan_type = type_map.get(new_powertrain, 'ice')
        
        db.session.execute(text("""
            UPDATE scans
            SET type = :type,
                type_source = 'manual_override',
                powertrain_conflict = false
            WHERE id = :id
        """), {
            "id": scan_id,
            "type": scan_type
        })
        
        audit_id = db.session.execute(text("""
            INSERT INTO powertrain_override_audit 
            (scan_id, user_id, previous_powertrain, new_powertrain,
             previous_source, new_source, reason, created_at)
            VALUES (:scan_id, :user_id, :prev_pt, :new_pt, :prev_src, :new_src, :reason, NOW())
            RETURNING id
        """), {
            "scan_id": scan_id,
            "user_id": user_id,
            "prev_pt": previous_type,
            "new_pt": new_powertrain,
            "prev_src": previous_source,
            "new_src": "manual_override",
            "reason": reason
        }).scalar()
        
        db.session.commit()
        
        return {
            "success": True,
            "audit_id": audit_id,
            "previous_powertrain": previous_type,
            "new_powertrain": new_powertrain
        }


def revert_to_automatic(
    vehicle_definition_id: Optional[int] = None,
    scan_id: Optional[int] = None
) -> Dict[str, Any]:
    """Revert manual override back to automatic classification.
    
    Re-runs classification and removes manual_override source.
    """
    if vehicle_definition_id:
        # Get vehicle data
        vehicle = db.session.execute(text("""
            SELECT vd.maker, vd.model, vd.submodel, vd.vin, ds.file_path
            FROM vehicle_definitions vd
            LEFT JOIN definition_sources ds ON vd.source_id = ds.id
            WHERE vd.id = :id
        """), {"id": vehicle_definition_id}).fetchone()
        
        if not vehicle:
            raise ValueError(f"Vehicle definition {vehicle_definition_id} not found")
        
        # Re-classify
        from app.modules.definitions.vehicle_classifier import classify_vehicle_powertrain
        pt, src, conf, conflict = classify_vehicle_powertrain(
            maker=vehicle[0],
            model=vehicle[1],
            submodel=vehicle[2],
            file_path=vehicle[4],
            vin=vehicle[3]
        )
        
        # Update with automatic classification
        db.session.execute(text("""
            UPDATE vehicle_definitions
            SET powertrain = :powertrain,
                powertrain_source = :source,
                powertrain_confidence = :confidence
            WHERE id = :id
        """), {
            "id": vehicle_definition_id,
            "powertrain": pt,
            "source": src,
            "confidence": conf
        })
        
        db.session.commit()
        
        return {
            "success": True,
            "powertrain": pt,
            "source": src,
            "confidence": conf
        }
    
    raise NotImplementedError("Scan revert not yet implemented")
