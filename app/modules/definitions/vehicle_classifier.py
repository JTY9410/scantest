"""Vehicle powertrain classification with source tracking.

Handles real-world data formats: underscores, spaces, colons, dashes,
Korean text, mixed case, etc.
"""
import re
from typing import Optional, Tuple
from sqlalchemy import text

from app.extensions import db
from app.utils.vin_decoder import decode_powertrain_from_vin, validate_vin


def normalize_text(text: Optional[str]) -> str:
    """Normalize text for matching: lowercase, remove special chars, split tokens."""
    if not text:
        return ""
    
    # Lowercase
    text = text.lower()
    
    # Replace underscores, colons, dashes, slashes with spaces
    text = re.sub(r'[_:/\-]+', ' ', text)
    
    # Remove extra spaces
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def extract_tokens(text: str) -> set:
    """Extract alphanumeric tokens from text."""
    # Split on non-alphanumerics
    tokens = re.findall(r'[a-z0-9가-힣]+', text)
    return set(tokens)


# Known BEV models (normalized tokens)
BEV_TOKENS = {
    'ioniq5', 'ioniq6', 'ioniq7',
    'ev3', 'ev4', 'ev5', 'ev6', 'ev9',
    'kona', 'niro', 'soul', 'ray',
    'gv60', 'gv70', 'g80', 'gv80', 'electrified',
    'model3', 'models', 'modelx', 'modely', 'tesla', 'roadster', 'cybertruck',
    'leaf', 'ariya',
    'bolt', 'hummer', 'lyriq', 'equinox', 'blazer',
    'mustang', 'mache', 'f150', 'lightning', 'etransit',
    'id3', 'id4', 'id5', 'id7', 'buzz',
    'etron', 'q4', 'q8',
    'taycan', 'macan',
    'ipace', 'eqs', 'eqe', 'eqc',
    'atto3', 'seal', 'dolphin', 'tang', 'han',
    'zoe', 'ph2',  # Renault ZOE
    'ec4', 'czero',  # Citroën
    'imiev',  # Mitsubishi
    'smart',  # Smart #1
    'polestar',
}

# BEV combinations (must have multiple tokens present)
# Note: 'electric' is handled as a combination token, not standalone
BEV_COMBINATIONS = [
    {'e', 'golf'},  # e-Golf
    {'kona', 'electric'}, {'kona', 'ev'},
    {'niro', 'ev'}, {'soul', 'ev'}, {'ray', 'ev'},
    {'gv70', 'electric'}, {'g80', 'electrified'}, {'gv80', 'electrified'},
    {'mustang', 'mache'}, {'f150', 'lightning'},
]

# PHEV tokens
PHEV_TOKENS = {'phev', 'plugin', 'plugin', '4xe', 'rechargeable', 'ehybrid', '플러그인'}

# HEV tokens (but not PHEV)
HEV_TOKENS = {'hybrid', 'hev', 'selfcharging', '하이브리드'}

# Known HEV models
HEV_MODEL_TOKENS = {'prius', 'camry', 'accord', 'ioniq'}

# ICE indicators
ICE_TOKENS = {'diesel', 'turbo', 'gdi', 'crdi', 'tci'}

# ECU vendor / protocol patterns (not_vehicle)
NOT_VEHICLE_PATTERNS = [
    r'_ecu_장비_프로토콜',
    r'_공통_프로토콜',
    r'/obd2/',
    r'/obdii/',
]

NOT_VEHICLE_MAKERS = {
    'bosch', 'delphi', 'marelli', 'teves', 'continental', 'denso',
    'aim', 'stack', 'life', 'motec', 'haltech', 'link',
    'dallara',  # Race car manufacturer, not street vehicles
}


def is_not_vehicle(maker: Optional[str], model: Optional[str], file_path: Optional[str]) -> bool:
    """Check if this is an ECU vendor or protocol, not a vehicle."""
    # Check file path patterns
    if file_path:
        file_lower = file_path.lower()
        for pattern in NOT_VEHICLE_PATTERNS:
            if re.search(pattern, file_lower):
                return True
    
    # Check maker
    if maker:
        maker_tokens = extract_tokens(normalize_text(maker))
        if maker_tokens & NOT_VEHICLE_MAKERS:
            return True
    
    # Check model
    if model:
        model_tokens = extract_tokens(normalize_text(model))
        if model_tokens & NOT_VEHICLE_MAKERS:
            return True
    
    return False


def classify_vehicle_powertrain(
    maker: Optional[str],
    model: Optional[str],
    submodel: Optional[str],
    file_path: Optional[str],
    vin: Optional[str] = None
) -> Tuple[str, str, float]:
    """Classify vehicle powertrain with source and confidence.
    
    Returns:
        (powertrain, source, confidence)
        - powertrain: BEV, PHEV, HEV, ICE, not_vehicle, or unknown
        - source: vin_rule, model_name, path_token, or unknown
        - confidence: 0.0-1.0
    """
    # Priority 1: VIN-based (if available)
    if vin and validate_vin(vin):
        # Load VIN rules from database
        vin_rules = db.session.execute(text("""
            SELECT wmi_pattern, vds_position, vds_value_pattern, powertrain, confidence
            FROM vin_decode_rules
            ORDER BY confidence DESC
        """)).fetchall()
        
        rules_list = [dict(row._mapping) for row in vin_rules]
        powertrain_vin, source_vin, conf_vin = decode_powertrain_from_vin(vin, rules_list)
        
        if powertrain_vin and powertrain_vin != 'unknown' and source_vin == 'vin_rule':
            return (powertrain_vin, 'vin_rule', conf_vin)
    
    # Priority 2: Check if not_vehicle
    if is_not_vehicle(maker, model, file_path):
        return ('not_vehicle', 'path_token', 0.95)
    
    # Priority 3: Model/submodel/file_path tokens
    all_text = ' '.join(filter(None, [maker, model, submodel, file_path or '']))
    normalized = normalize_text(all_text)
    tokens = extract_tokens(normalized)
    
    # Check PHEV first (before general hybrid)
    if tokens & PHEV_TOKENS:
        return ('PHEV', 'model_name', 0.85)
    
    # Check BEV combinations
    for combo in BEV_COMBINATIONS:
        if combo.issubset(tokens):
            return ('BEV', 'model_name', 0.90)
    
    # Check BEV tokens
    if tokens & BEV_TOKENS:
        return ('BEV', 'model_name', 0.85)
    
    # Check HEV (after filtering out PHEV)
    if tokens & HEV_TOKENS or tokens & HEV_MODEL_TOKENS:
        # Double-check not PHEV
        if not (tokens & PHEV_TOKENS):
            return ('HEV', 'model_name', 0.80)
    
    # Check ICE indicators
    if tokens & ICE_TOKENS:
        return ('ICE', 'model_name', 0.70)
    
    # Unable to classify
    return ('unknown', 'unknown', 0.0)


def reclassify_all_vehicles():
    """Reclassify all vehicle powertrains with source tracking.
    
    Returns dict of before/after counts.
    """
    # Get before counts
    before = db.session.execute(text("""
        SELECT powertrain, COUNT(*) as count
        FROM vehicle_definitions
        GROUP BY powertrain
        ORDER BY count DESC
    """)).fetchall()
    
    before_counts = {row.powertrain or 'NULL': row.count for row in before}
    
    print("📊 Reclassifying vehicle powertrains...")
    print(f"  Before: {before_counts}")
    
    # Get all vehicles
    vehicles = db.session.execute(text("""
        SELECT 
            vd.id,
            vd.maker,
            vd.model,
            vd.submodel,
            vd.vin,
            ds.file_path
        FROM vehicle_definitions vd
        LEFT JOIN definition_sources ds ON vd.source_id = ds.id
    """)).fetchall()
    
    updated = 0
    for vehicle in vehicles:
        powertrain, source, confidence = classify_vehicle_powertrain(
            vehicle.maker,
            vehicle.model,
            vehicle.submodel,
            vehicle.file_path,
            vehicle.vin
        )
        
        # Update if changed
        db.session.execute(text("""
            UPDATE vehicle_definitions
            SET 
                powertrain = :powertrain,
                powertrain_source = :source,
                powertrain_confidence = :confidence
            WHERE id = :id
        """), {
            'id': vehicle.id,
            'powertrain': powertrain,
            'source': source,
            'confidence': confidence
        })
        updated += 1
    
    db.session.commit()
    
    # Get after counts
    after = db.session.execute(text("""
        SELECT powertrain, COUNT(*) as count
        FROM vehicle_definitions
        GROUP BY powertrain
        ORDER BY count DESC
    """)).fetchall()
    
    after_counts = {row.powertrain or 'NULL': row.count for row in after}
    
    print(f"  After: {after_counts}")
    print(f"  Updated {updated} vehicles")
    
    return {
        'before': before_counts,
        'after': after_counts,
        'updated': updated
    }
