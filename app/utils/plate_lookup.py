"""Korean vehicle registration plate lookup system.

Provides vehicle information (fuel type, maker, model, year) from 차량번호.
"""
import os
import hashlib
import requests
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
from sqlalchemy import text

from app.extensions import db


def hash_plate(plate: str, salt: Optional[str] = None) -> str:
    """Hash plate number with salt for privacy.
    
    Args:
        plate: Vehicle registration number (차량번호)
        salt: Hashing salt (defaults to env var PLATE_LOOKUP_HASH_SALT)
    
    Returns:
        SHA-256 hex hash
    """
    if salt is None:
        salt = os.environ.get('PLATE_LOOKUP_HASH_SALT', 'default-salt-change-me')
    
    combined = f"{salt}:{plate}"
    return hashlib.sha256(combined.encode('utf-8')).hexdigest()


def mask_plate(plate: str) -> str:
    """Mask plate number for privacy: first 2-3 chars + **** (e.g., 12가****).
    
    Args:
        plate: Vehicle registration number
    
    Returns:
        Masked plate number
    """
    if not plate or len(plate) < 4:
        return '***'
    
    # Korean plates: '12가3456' format (2-3 prefix + Korean char + 4 digits)
    # Keep first 3 chars (e.g., '12가'), mask the rest
    if len(plate) <= 6:
        return plate[:2] + '****'
    
    return plate[:3] + '****'


def map_fuel_to_powertrain(fuel_raw: str) -> Tuple[str, float]:
    """Map Korean fuel type to powertrain classification.
    
    Args:
        fuel_raw: Raw fuel type from registration (e.g., '전기', '하이브리드')
    
    Returns:
        Tuple of (powertrain, confidence)
    """
    fuel = fuel_raw.lower().strip()
    
    # Electric (전기)
    if '전기' in fuel:
        return ('BEV', 0.99)
    
    # Hydrogen / Fuel Cell (수소, 연료전지)
    if '수소' in fuel or '연료전지' in fuel:
        return ('FCEV', 0.99)
    
    # Plug-in Hybrid (플러그인하이브리드)
    if '플러그인' in fuel or 'plug' in fuel:
        return ('PHEV', 0.95)
    
    # Hybrid (하이브리드)
    if '하이브리드' in fuel or 'hybrid' in fuel:
        return ('HEV', 0.95)
    
    # ICE fuels
    if any(ice in fuel for ice in ['휘발유', 'gasoline', '경유', 'diesel', 'lpg', 'cng']):
        return ('ICE', 0.95)
    
    # Unknown fuel type
    return ('unknown', 0.0)


class PlateLookupProvider(ABC):
    """Base interface for plate lookup providers."""
    
    @abstractmethod
    def lookup(self, plate: str, owner_name: Optional[str] = None) -> Optional[Dict]:
        """Look up vehicle information by plate number.
        
        Args:
            plate: Vehicle registration number (차량번호)
            owner_name: Owner name for verification (if required by provider)
        
        Returns:
            Dict with keys: fuel_raw, maker, model, model_year, displacement
            Returns None if lookup fails or not found
        """
        pass


class MOLITProvider(PlateLookupProvider):
    """국토교통부 자동차 등록원부 API provider.
    
    Requires MOLIT_API_KEY environment variable.
    Documentation: https://www.data.go.kr/data/15000300/openapi.do
    """
    
    BASE_URL = "http://apis.data.go.kr/1613000/CarInformationService/getCarInfo"
    TIMEOUT = 10  # seconds
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get('MOLIT_API_KEY')
        if not self.api_key:
            raise ValueError("MOLIT_API_KEY environment variable required")
    
    def lookup(self, plate: str, owner_name: Optional[str] = None) -> Optional[Dict]:
        """Look up vehicle from MOLIT API.
        
        Requires owner_name for verification.
        """
        if not owner_name:
            # MOLIT requires owner name for verification
            return None
        
        try:
            params = {
                'serviceKey': self.api_key,
                'numOfRows': 1,
                'pageNo': 1,
                'carRegNo': plate,
                'ownerNm': owner_name,
            }
            
            response = requests.get(self.BASE_URL, params=params, timeout=self.TIMEOUT)
            response.raise_for_status()
            
            # Parse XML response
            root = ET.fromstring(response.content)
            
            # Check result code
            result_code = root.find('.//resultCode')
            if result_code is None or result_code.text != '00':
                result_msg = root.find('.//resultMsg')
                msg = result_msg.text if result_msg is not None else 'Unknown error'
                print(f"MOLIT API error for {mask_plate(plate)}: {msg}")
                return None
            
            # Extract item data
            item = root.find('.//item')
            if item is None:
                return None
            
            # Extract fields (safely)
            def get_text(tag_name: str) -> Optional[str]:
                elem = item.find(tag_name)
                return elem.text if elem is not None and elem.text else None
            
            fuel_raw = get_text('fuelCd')
            maker = get_text('carMfr')
            model = get_text('carModel')
            
            # Model year
            model_year_str = get_text('modelYear')
            model_year = int(model_year_str) if model_year_str and model_year_str.isdigit() else None
            
            # Displacement (engine volume)
            displacement_str = get_text('engineVolume')
            displacement = int(displacement_str) if displacement_str and displacement_str.isdigit() else None
            
            if not fuel_raw:
                return None
            
            return {
                'fuel_raw': fuel_raw,
                'maker': maker,
                'model': model,
                'model_year': model_year,
                'displacement': displacement,
            }
        
        except requests.RequestException as e:
            print(f"MOLIT API request failed for {mask_plate(plate)}: {e}")
            return None
        except ET.ParseError as e:
            print(f"MOLIT API response parse error for {mask_plate(plate)}: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error in MOLIT lookup for {mask_plate(plate)}: {e}")
            return None


def get_provider() -> Optional[PlateLookupProvider]:
    """Get configured plate lookup provider.
    
    Returns:
        Provider instance, or None if not configured
    """
    provider_name = os.environ.get('PLATE_LOOKUP_PROVIDER', 'none').lower()
    
    if provider_name == 'none' or not provider_name:
        return None
    
    if provider_name == 'molit':
        api_key = os.environ.get('MOLIT_API_KEY')
        if not api_key:
            print("Warning: PLATE_LOOKUP_PROVIDER=molit but MOLIT_API_KEY not set")
            return None
        return MOLITProvider(api_key)
    
    print(f"Warning: Unknown PLATE_LOOKUP_PROVIDER: {provider_name}")
    return None


def lookup_plate_info(
    plate: str,
    owner_name: Optional[str] = None,
    use_cache: bool = True
) -> Optional[Dict]:
    """Look up vehicle information by plate number with caching.
    
    Args:
        plate: Vehicle registration number (차량번호)
        owner_name: Owner name for verification (if required by provider)
        use_cache: Whether to use cached results
    
    Returns:
        Dict with keys: fuel_raw, maker, model, model_year, displacement, 
                        powertrain, powertrain_confidence, source, fetched_at
        Returns None if lookup fails or not found
    """
    plate_hash = hash_plate(plate)
    cache_ttl_days = int(os.environ.get('PLATE_LOOKUP_CACHE_TTL_DAYS', 90))
    
    # Check cache first
    if use_cache:
        cache_cutoff = datetime.utcnow() - timedelta(days=cache_ttl_days)
        cached = db.session.execute(text("""
            SELECT fuel_raw, maker, model, model_year, displacement, 
                   powertrain, powertrain_confidence, source, fetched_at
            FROM plate_lookup_cache
            WHERE plate_hash = :plate_hash
            AND fetched_at > :cache_cutoff
            LIMIT 1
        """), {'plate_hash': plate_hash, 'cache_cutoff': cache_cutoff}).fetchone()
        
        if cached:
            return dict(cached._mapping)
    
    # Lookup from provider
    provider = get_provider()
    if not provider:
        return None
    
    result = provider.lookup(plate, owner_name)
    if not result:
        return None
    
    # Map fuel to powertrain
    powertrain, confidence = map_fuel_to_powertrain(result['fuel_raw'])
    
    # Store in cache
    now = datetime.utcnow()
    db.session.execute(text("""
        INSERT INTO plate_lookup_cache 
            (plate_hash, fuel_raw, maker, model, model_year, displacement,
             powertrain, powertrain_confidence, source, fetched_at)
        VALUES 
            (:plate_hash, :fuel_raw, :maker, :model, :model_year, :displacement,
             :powertrain, :confidence, :source, :fetched_at)
        ON CONFLICT (plate_hash) DO UPDATE SET
            fuel_raw = EXCLUDED.fuel_raw,
            maker = EXCLUDED.maker,
            model = EXCLUDED.model,
            model_year = EXCLUDED.model_year,
            displacement = EXCLUDED.displacement,
            powertrain = EXCLUDED.powertrain,
            powertrain_confidence = EXCLUDED.powertrain_confidence,
            source = EXCLUDED.source,
            fetched_at = EXCLUDED.fetched_at
    """), {
        'plate_hash': plate_hash,
        'fuel_raw': result['fuel_raw'],
        'maker': result.get('maker'),
        'model': result.get('model'),
        'model_year': result.get('model_year'),
        'displacement': result.get('displacement'),
        'powertrain': powertrain,
        'confidence': confidence,
        'source': provider.__class__.__name__,
        'fetched_at': now,
    })
    db.session.commit()
    
    # Return combined result
    return {
        **result,
        'powertrain': powertrain,
        'powertrain_confidence': confidence,
        'source': provider.__class__.__name__,
        'fetched_at': now,
    }
