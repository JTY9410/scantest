"""Vehicle powertrain classification with source tracking.

Handles real-world data formats: underscores, spaces, colons, dashes,
Korean text, mixed case, etc.

Priority order for powertrain determination:
1. Manual override (user-corrected conflicts) - never overwritten
2. Plate lookup (차량번호 from existing Wecar API) - PRIMARY source
3. VIN rules (manufacturer-specific VDS rules) - CROSS-CHECK
4. vPIC API (NHTSA) - fallback for VIN
5. Model name/path tokens - heuristic
6. BMS evidence - heuristic
"""
import re
from typing import Optional, Tuple, Dict, Any
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


# Known BEV models (specific, unambiguous, BEV-only nameplates)
BEV_SPECIFIC_TOKENS = {
    # Hyundai/Kia specific models (NOT base names)
    'ioniq5', 'ioniq6', 'ioniq7', 'ioniq9',  # Specific IONIQ numbers
    'ev3', 'ev4', 'ev5', 'ev6', 'ev9',  # Kia EV series
    'gv60',  # Genesis
    
    # Tesla (all models are BEV-only)
    'model3', 'models', 'modelx', 'modely', 'tesla', 'roadster', 'cybertruck',
    
    # Nissan
    'leaf', 'ariya',
    
    # GM/Chevrolet
    'bolt', 'bolteuc', 'bolt ev', 'hummer', 'lyriq', 'equinox', 'blazer', 'silverado',
    
    # Ford
    'mache', 'mustangmache', 'lightning', 'f150lightning', 'etransit',  # BEV-only nameplates
    
    # VW Group
    'id3', 'id4', 'id5', 'id7', 'buzz', 'enyaq', 'born',  # VW/Skoda/Cupra BEVs
    'bz4x',  # Toyota bZ4X
    
    # Audi (specific e-tron models, not A3)
    'q4', 'q8', 'rsetron',
    
    # Porsche
    'taycan',
    
    # Jaguar
    'ipace',
    
    # Mercedes
    'eqs', 'eqe', 'eqc', 'eqa', 'eqb',
    
    # BYD
    'atto3', 'atto', 'seal', 'dolphin', 'tang', 'han',
    
    # Renault/Dacia
    'zoe', 'ph2', 'spring',
    
    # Citroën/Peugeot
    'ec4', 'czero', 'e208', 'e2008',
    
    # Mitsubishi
    'imiev',
    
    # Smart
    'smart',
    
    # Polestar (all models BEV)
    'polestar', 'polestar2',
    
    # BMW
    'ix3', 'ix1', 'ix',
    
    # Subaru/Toyota
    'solterra',  # Subaru Solterra BEV-only nameplate
    
    # Rivian/Lucid (all models BEV)
    'rivian', 'r1t', 'r1s', 'lucid', 'air',
    
    # Volvo
    'xc40recharge',  # XC40 Recharge is BEV (not PHEV)
    
    # Others
    'evx',  # Torres EVX
    'amperee',  # Opel Ampere-E
}

# Ambiguous base names that need a qualifier (EV/Electric/etc.)
# These alone should NOT trigger BEV
AMBIGUOUS_BASE_NAMES = {
    'kona', 'niro', 'soul', 'ioniq',  # Have ICE/HEV/BEV variants
    'macan',  # Macan vs Macan-Electric
    'tucson', 'sportage', 'sorento',  # Have multiple powertrains
    'prius',  # Prius vs Prius Prime
}

# BEV qualifier tokens (when combined with base names or standalone)
BEV_QUALIFIERS = {
    'electric', 'bev', 'ev',  # General electric
    'etron', 'etrongt',  # Audi naming
    'sierraev',  # GMC Sierra EV
}

# BEV combinations (must have multiple tokens)
BEV_COMBINATIONS = [
    {'e', 'golf'},
    {'e', 'tron'},  # Audi e-tron (becomes 'e' + 'tron')
    {'e', '208'}, {'e', '2008'},  # Peugeot e-208, e-2008
    {'kona', 'electric'}, {'kona', 'ev'},
    {'niro', 'ev'},
    {'soul', 'ev'},
    {'ray', 'ev'},
    {'ioniq', 'electric'},  # Ioniq Electric (but not just Ioniq)
    {'ioniq', '5'}, {'ioniq', '6'}, {'ioniq', '7'}, {'ioniq', '9'},  # IONIQ-5/6/7/9
    {'gv70', 'electric'}, {'g80', 'electrified'}, {'gv80', 'electrified'},
    {'mustang', 'mache'},
    {'f150', 'lightning'},
    {'macan', 'electric'},
    {'xc40', 'bev'},
    {'zs', 'ev'},
    {'sierra', 'ev'},
    {'torres', 'evx'},
    {'ampera', 'e'},  # Opel Ampera-E / Ampere-E
    {'ampere', 'e'},  # Alternative spelling
]

# PHEV tokens (must win over HEV)
PHEV_TOKENS = {
    'phev', 'plugin',
    '4xe',
    'prime',  # Prius Prime, RAV4 Prime
    'energi',  # Ford Energi models
    'rechargeable', 'ehybrid',
    'volt', 'ampera',  # Chevrolet Volt, Opel Ampera (PHEV versions)
    '플러그인',
}

# PHEV combinations (multi-token patterns)
PHEV_COMBINATIONS = [
    {'plug', 'in'},  # Plug-in becomes 'plug' + 'in'
    {'a3', 'e', 'tron'},  # Audi A3 e-tron (PHEV)
]

# HEV tokens (but ONLY if no PHEV tokens present)
HEV_TOKENS = {'hybrid', 'selfcharging', '하이브리드'}

# Known HEV models (specific)
# Prius: all models are HEV except Prime (which is PHEV)
HEV_MODEL_TOKENS = {
    'prius', 'priusv',  # Toyota Prius (all non-Prime variants)
    'camry', 'accord',
}

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
    'mectronik',  # Aftermarket ECU vendor
}


def is_not_vehicle(maker: Optional[str], model: Optional[str], file_path: Optional[str]) -> bool:
    """Check if this is an ECU vendor, protocol, or shared definitions, not a vehicle."""
    # Check file path patterns
    if file_path:
        file_lower = file_path.lower()
        for pattern in NOT_VEHICLE_PATTERNS:
            if re.search(pattern, file_lower):
                return True
    
    # Check maker for shared/common folders (공용)
    if maker:
        maker_lower = maker.lower()
        # Shared definitions folders like 'Volkswagen_Group_공용', 'Hyundai_Kia_Genesis_공용'
        if '공용' in maker_lower or '_공용' in maker:
            return True
        
        maker_tokens = extract_tokens(normalize_text(maker))
        if maker_tokens & NOT_VEHICLE_MAKERS:
            return True
    
    # Check model
    if model:
        model_tokens = extract_tokens(normalize_text(model))
        if model_tokens & NOT_VEHICLE_MAKERS:
            return True
    
    return False


def map_fuel_to_powertrain(diag_fuel: str) -> Tuple[Optional[str], float]:
    """Map Wecar diag_fuel to powertrain classification.
    
    Args:
        diag_fuel: Fuel type from Wecar API (e.g., '전기', '하이브리드')
    
    Returns:
        Tuple of (powertrain, confidence) or (None, 0.0) if unmapped
    """
    if not diag_fuel:
        return (None, 0.0)
    
    fuel_norm = diag_fuel.strip().lower()
    
    # Electric (전기)
    if '전기' in fuel_norm or 'electric' in fuel_norm or 'bev' in fuel_norm:
        return ('BEV', 0.99)
    
    # Hydrogen / Fuel Cell (수소, 연료전지)
    if '수소' in fuel_norm or '연료전지' in fuel_norm or 'hydrogen' in fuel_norm or 'fcev' in fuel_norm:
        return ('FCEV', 0.99)
    
    # Plug-in Hybrid (플러그인)
    if '플러그인' in fuel_norm or 'plug-in' in fuel_norm or 'plugin' in fuel_norm or 'phev' in fuel_norm:
        return ('PHEV', 0.95)
    
    # Hybrid (하이브리드) - but not mild/마일드 which is ICE
    if '마일드' in fuel_norm or 'mild' in fuel_norm or '48v' in fuel_norm:
        return ('ICE', 0.95)
    if '하이브리드' in fuel_norm or 'hybrid' in fuel_norm or 'hev' in fuel_norm:
        return ('HEV', 0.95)
    
    # ICE fuels
    if any(ice in fuel_norm for ice in ['휘발유', 'gasoline', '가솔린', '경유', 'diesel', 'lpg', 'lpi', 'cng', 'lng']):
        return ('ICE', 0.95)
    
    # Unknown fuel type
    return (None, 0.0)


def classify_vehicle_powertrain(
    maker: Optional[str],
    model: Optional[str],
    submodel: Optional[str],
    file_path: Optional[str],
    vin: Optional[str] = None,
    has_bms_commands: bool = False
) -> Tuple[str, str, float]:
    """Classify vehicle powertrain with source and confidence.
    
    Priority order:
    1. VIN-based rules (highest confidence)
    2. not_vehicle detection
    3. File path folder evidence (e.g., "Ioniq HEV" folder, "Niro HEV" folder)
    4. PHEV tokens (must win over HEV)
    5. HEV tokens (but only 'hev' or 'hybrid', not substring of 'ev')
    6. BEV specific tokens and combinations
    7. Ambiguous base names without qualifiers → unknown
    8. BMS evidence (if has_bms_commands=True)
    
    Returns:
        (powertrain, source, confidence)
    """
    # Priority 1: VIN-based (if available and database accessible)
    if vin and validate_vin(vin):
        try:
            vin_rules = db.session.execute(text("""
                SELECT wmi_pattern, vds_position, vds_value_pattern, powertrain, confidence
                FROM vin_decode_rules
                ORDER BY confidence DESC
            """)).fetchall()
            
            rules_list = [dict(row._mapping) for row in vin_rules]
            powertrain_vin, source_vin, conf_vin = decode_powertrain_from_vin(vin, rules_list)
            
            if powertrain_vin and powertrain_vin != 'unknown' and source_vin == 'vin_rule':
                return (powertrain_vin, 'vin_rule', conf_vin)
        except Exception:
            # Database not available (e.g., in tests without app context)
            pass
    
    # Priority 2: Check if not_vehicle
    if is_not_vehicle(maker, model, file_path):
        return ('not_vehicle', 'path_token', 0.95)
    
    # Priority 3: File path folder evidence (explicit powertrain in folder name)
    # This wins over token matching because it's specific context
    if file_path:
        path_lower = file_path.lower()
        # Look for explicit folder markers like "Ioniq HEV", "Niro HEV", "Ioniq EV"
        # Use word boundaries to avoid false matches
        if re.search(r'/(.*?\s+|\b)hev\b', path_lower) or re.search(r'/.*?_hev[/_]', path_lower):
            return ('HEV', 'path_folder:HEV', 0.95)
        if re.search(r'/(.*?\s+|\b)phev\b', path_lower) or re.search(r'/.*?_phev[/_]', path_lower):
            return ('PHEV', 'path_folder:PHEV', 0.95)
        # EV folder markers (but not inside "HEV")
        if re.search(r'/.*?\s+ev\b', path_lower) or re.search(r'/.*?_ev[/_\-]', path_lower) or re.search(r'/.*?-ev[/_\-]', path_lower):
            # Double-check it's not "HEV"
            if not re.search(r'hev', path_lower):
                return ('BEV', 'path_folder:EV', 0.95)
    
    # Normalize all text for token matching
    all_text = ' '.join(filter(None, [maker, model, submodel, file_path or '']))
    normalized = normalize_text(all_text)
    tokens = extract_tokens(normalized)
    
    # Priority 4: PHEV tokens and combinations (must win over HEV)
    # Check PHEV combinations first
    for combo in PHEV_COMBINATIONS:
        if combo.issubset(tokens):
            return ('PHEV', 'model_name:PHEV_combo', 0.90)
    
    # Check PHEV tokens
    if tokens & PHEV_TOKENS:
        return ('PHEV', 'model_name:PHEV_token', 0.85)
    
    # Priority 5: Check for mixed powertrain (both HEV and BEV evidence)
    # If both hybrid and BEV tokens appear (and no PHEV), it's ambiguous/mixed
    has_hev_token = 'hev' in tokens or 'hybrid' in tokens or 'selfcharging' in tokens or '하이브리드' in tokens
    has_bev_evidence = bool(tokens & (BEV_SPECIFIC_TOKENS | BEV_QUALIFIERS))
    has_phev_evidence = bool(tokens & PHEV_TOKENS)
    
    if has_hev_token and has_bev_evidence and not has_phev_evidence:
        # Mixed powertrain (e.g., "Ioniq Hybrid EV" covers both) → unknown
        return ('unknown', 'mixed_powertrain', 0.0)
    
    # Priority 6: HEV detection
    # Check Toyota Prius models (all are HEV except Prime which is PHEV)
    if 'prius' in tokens or 'priusv' in tokens:
        # If it has PHEV tokens, it's already been caught above
        # Otherwise, Prius is HEV
        return ('HEV', 'model_name:Prius_HEV', 0.90)
    
    # Check Lexus/Toyota 'h' suffix (e.g., ES-300h, RX450h)
    # 'h' suffix = HEV, 'h+' or '450h+' = PHEV
    if model or maker:
        text_for_suffix = ' '.join(filter(None, [maker, model]))
        # Check for PHEV h+ patterns
        if re.search(r'\d+h\+', text_for_suffix.lower()) or 'h+' in text_for_suffix.lower():
            return ('PHEV', 'model_name:Lexus_h+', 0.90)
        # Check for HEV h suffix (but not h+)
        if re.search(r'\d+h\b', text_for_suffix.lower()) or re.search(r'-\d+h\b', text_for_suffix.lower()):
            return ('HEV', 'model_name:Lexus_h', 0.90)
    
    if has_hev_token and not has_phev_evidence:
        # Also check HEV model tokens (other than Prius which is handled above)
        if tokens & HEV_MODEL_TOKENS:
            return ('HEV', 'model_name:HEV_model', 0.80)
        return ('HEV', 'model_name:HEV_token', 0.80)
    
    # Priority 6: BEV specific tokens and combinations
    # Check BEV combinations first (more specific)
    for combo in BEV_COMBINATIONS:
        if combo.issubset(tokens):
            return ('BEV', 'model_name:BEV_combo', 0.90)
    
    # Check BEV specific tokens
    if tokens & BEV_SPECIFIC_TOKENS:
        return ('BEV', 'model_name:BEV_specific', 0.85)
    
    # Check BEV qualifiers (electric, bev, ev, e-tron)
    if tokens & BEV_QUALIFIERS:
        # But NOT if it's an ambiguous base name without context
        # Check if we only have an ambiguous base + qualifier
        if tokens & AMBIGUOUS_BASE_NAMES:
            # It's something like "Kona Electric" or "Niro EV" - these are BEV
            # But just "Kona" or "Niro" alone would be ambiguous
            base_names_present = tokens & AMBIGUOUS_BASE_NAMES
            qualifiers_present = tokens & BEV_QUALIFIERS
            
            # If we have both base and qualifier, it's BEV
            if base_names_present and qualifiers_present:
                return ('BEV', 'model_name:base+BEV_qualifier', 0.85)
        else:
            # No ambiguous base, just qualifiers (e.g., "e-tron")
            return ('BEV', 'model_name:BEV_qualifier', 0.85)
    
    # Priority 7: Check if it's an ambiguous base name alone (no qualifiers)
    if tokens & AMBIGUOUS_BASE_NAMES:
        # Check if there are NO powertrain qualifiers
        has_qualifiers = bool(tokens & (BEV_QUALIFIERS | PHEV_TOKENS | {'hev', 'hybrid', '하이브리드'}))
        if not has_qualifiers:
            # Ambiguous base name without qualifier → stay unknown
            return ('unknown', 'ambiguous_base', 0.0)
    
    # Check ICE indicators
    if tokens & ICE_TOKENS:
        return ('ICE', 'model_name:ICE_token', 0.70)
    
    # Priority 8: BMS evidence (if has_bms_commands)
    if has_bms_commands:
        return ('BEV', 'bms_evidence', 0.60)
    
    # Unable to classify
    return ('unknown', 'no_match', 0.0)


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
