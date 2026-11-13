"""NHTSA vPIC (Vehicle Product Information Catalog) API client.

API documentation: https://vpic.nhtsa.dot.gov/api/
Privacy: VINs are submitted to NHTSA's public API; results are cached locally.
"""
from typing import Optional, Literal
import requests
from datetime import datetime, timedelta
from sqlalchemy import text

PowertrainType = Literal['BEV', 'PHEV', 'HEV', 'ICE', 'unknown']

VPIC_API_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"
VPIC_TIMEOUT = 3.0  # seconds
CACHE_DURATION_DAYS = 90


def map_vpic_to_powertrain(
    electrification_level: Optional[str],
    fuel_type_primary: Optional[str],
    fuel_type_secondary: Optional[str]
) -> tuple[PowertrainType, float]:
    """Map vPIC response to powertrain type.
    
    Args:
        electrification_level: e.g. "BEV", "PHEV", "HEV", "MHEV", "None"
        fuel_type_primary: e.g. "Electric", "Gasoline", "Diesel", "Hydrogen"
        fuel_type_secondary: Secondary fuel type if applicable
    
    Returns:
        Tuple of (powertrain, confidence)
    """
    # Electrification level is most reliable
    if electrification_level:
        level = electrification_level.upper()
        if 'BEV' in level or level == 'ELECTRIC':
            return ('BEV', 0.90)
        if 'PHEV' in level or 'PLUG' in level:
            return ('PHEV', 0.90)
        if 'HEV' in level or 'HYBRID' in level:
            return ('HEV', 0.85)
        if 'MHEV' in level:  # Mild hybrid
            return ('HEV', 0.80)
    
    # Fall back to fuel type
    if fuel_type_primary:
        fuel = fuel_type_primary.lower()
        if 'electric' in fuel and not fuel_type_secondary:
            return ('BEV', 0.85)
        if 'electric' in fuel and fuel_type_secondary:
            if 'gasoline' in fuel_type_secondary.lower() or 'petrol' in fuel_type_secondary.lower():
                return ('PHEV', 0.80)
        if 'hybrid' in fuel or ('electric' in fuel and 'gasoline' in fuel):
            return ('HEV', 0.75)
        if 'gasoline' in fuel or 'diesel' in fuel or 'petrol' in fuel:
            return ('ICE', 0.70)
    
    return ('unknown', 0.0)


def decode_vin_vpic(vin: str, db_connection) -> tuple[Optional[PowertrainType], str, float]:
    """Decode VIN using NHTSA vPIC API with database caching.
    
    Args:
        vin: 17-character VIN
        db_connection: SQLAlchemy connection for cache access
    
    Returns:
        Tuple of (powertrain_type, source, confidence)
        - source: 'vpic' if successful, 'vpic_cached', 'vpic_timeout', 'vpic_error', or 'vpic_offline'
    """
    if not vin or len(vin) != 17:
        return (None, 'vpic_invalid_vin', 0.0)
    
    # Check cache first
    try:
        result = db_connection.execute(text("""
            SELECT electrification_level, fuel_type_primary, fuel_type_secondary, cached_at, expires_at
            FROM vpic_cache
            WHERE vin = :vin AND expires_at > NOW()
        """), {"vin": vin})
        
        row = result.fetchone()
        if row:
            powertrain, confidence = map_vpic_to_powertrain(
                row[0],  # electrification_level
                row[1],  # fuel_type_primary
                row[2]   # fuel_type_secondary
            )
            return (powertrain, 'vpic_cached', confidence)
    except Exception:
        # Cache read failed, continue to API
        pass
    
    # Call vPIC API
    try:
        url = VPIC_API_URL.format(vin=vin)
        response = requests.get(url, timeout=VPIC_TIMEOUT)
        response.raise_for_status()
        
        data = response.json()
        if not data or 'Results' not in data or not data['Results']:
            return ('unknown', 'vpic_no_data', 0.0)
        
        result = data['Results'][0]
        
        electrification_level = result.get('ElectrificationLevel')
        fuel_type_primary = result.get('FuelTypePrimary')
        fuel_type_secondary = result.get('FuelTypeSecondary')
        make = result.get('Make')
        model = result.get('Model')
        model_year = result.get('ModelYear')
        
        # Try to parse model_year as int
        try:
            model_year = int(model_year) if model_year else None
        except (ValueError, TypeError):
            model_year = None
        
        powertrain, confidence = map_vpic_to_powertrain(
            electrification_level,
            fuel_type_primary,
            fuel_type_secondary
        )
        
        # Cache the result
        try:
            expires_at = datetime.now() + timedelta(days=CACHE_DURATION_DAYS)
            db_connection.execute(text("""
                INSERT INTO vpic_cache 
                (vin, electrification_level, fuel_type_primary, fuel_type_secondary, 
                 make, model, model_year, response_json, cached_at, expires_at)
                VALUES (:vin, :elec, :fuel1, :fuel2, :make, :model, :year, :json, NOW(), :expires)
                ON CONFLICT (vin) DO UPDATE SET
                    electrification_level = EXCLUDED.electrification_level,
                    fuel_type_primary = EXCLUDED.fuel_type_primary,
                    fuel_type_secondary = EXCLUDED.fuel_type_secondary,
                    make = EXCLUDED.make,
                    model = EXCLUDED.model,
                    model_year = EXCLUDED.model_year,
                    response_json = EXCLUDED.response_json,
                    cached_at = NOW(),
                    expires_at = EXCLUDED.expires_at
            """), {
                "vin": vin,
                "elec": electrification_level,
                "fuel1": fuel_type_primary,
                "fuel2": fuel_type_secondary,
                "make": make,
                "model": model,
                "year": model_year,
                "json": data,
                "expires": expires_at
            })
            db_connection.commit()
        except Exception:
            # Cache write failed, but we have the result
            pass
        
        return (powertrain, 'vpic', confidence)
    
    except requests.exceptions.Timeout:
        return ('unknown', 'vpic_timeout', 0.0)
    except requests.exceptions.ConnectionError:
        return ('unknown', 'vpic_offline', 0.0)
    except requests.exceptions.HTTPError as e:
        if e.response and e.response.status_code == 404:
            return ('unknown', 'vpic_not_found', 0.0)
        return ('unknown', 'vpic_error', 0.0)
    except Exception:
        return ('unknown', 'vpic_error', 0.0)


def get_vpic_cached_model_year(vin: str, db_connection) -> Optional[int]:
    """Get model year from vPIC cache if available.
    
    Used for SOH calculation to match battery_specs.
    """
    try:
        result = db_connection.execute(text("""
            SELECT model_year FROM vpic_cache
            WHERE vin = :vin AND expires_at > NOW() AND model_year IS NOT NULL
        """), {"vin": vin})
        
        row = result.fetchone()
        return row[0] if row else None
    except Exception:
        return None
