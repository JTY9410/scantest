"""제조사 이름 별칭 매칭 및 정규화.

maker_aliases 테이블을 사용하여 영문/한글/변형을 모두 동일한 제조사로 매칭.
예: "Hyundai", "HYUNDAI", "현대", "현대자동차" → 모두 같은 제조사

표시: "현대 (Hyundai)" 형식으로 양쪽 표시

기존 데이터는 변경하지 않음. 검색/필터/매칭 시 aliases 사용.
"""

import re
from typing import Optional
from functools import lru_cache

# Fallback aliases when database is not available (tests, CLI without app context)
_FALLBACK_ALIASES = {
    "hyundai": "hyundai",
    "현대": "hyundai",
    "현대자동차": "hyundai",
    "kia": "kia",
    "기아": "kia",
    "기아자동차": "kia",
    "nissan": "nissan",
    "닛산": "nissan",
    "닛싼": "nissan",
    "genesis": "genesis",
    "제네시스": "genesis",
    "tesla": "tesla",
    "테슬라": "tesla",
    "bmw": "bmw",
    "mercedes-benz": "mercedes-benz",
    "mercedes benz": "mercedes-benz",
    "benz": "mercedes-benz",
    "벤츠": "mercedes-benz",
    "audi": "audi",
    "아우디": "audi",
    "volkswagen": "volkswagen",
    "vw": "volkswagen",
    "폭스바겐": "volkswagen",
    "toyota": "toyota",
    "토요타": "toyota",
    "honda": "honda",
    "혼다": "honda",
    "ford": "ford",
    "포드": "ford",
    "chevrolet": "chevrolet",
    "chevy": "chevrolet",
    "쉐보레": "chevrolet",
    "aston martin": "aston-martin",
    "aston_martin": "aston-martin",
    "astonmartin": "aston-martin",
    "애스턴 마틴": "aston-martin",
    "애스턴마틴": "aston-martin",
    "land rover": "land-rover",
    "land_rover": "land-rover",
    "landrover": "land-rover",
    "랜드로버": "land-rover",
    "alfa romeo": "alfa-romeo",
    "alfa_romeo": "alfa-romeo",
    "alfaromeo": "alfa-romeo",
    "알파 로메오": "alfa-romeo",
    "알파로메오": "alfa-romeo",
    "rolls-royce": "rolls-royce",
    "rolls_royce": "rolls-royce",
    "rollsroyce": "rolls-royce",
    "롤스로이스": "rolls-royce",
}

# Standard keys with display names (fallback)
_DISPLAY_NAMES = {
    "hyundai": ("Hyundai", "현대"),
    "kia": ("Kia", "기아"),
    "genesis": ("Genesis", "제네시스"),
    "nissan": ("Nissan", "닛산"),
    "tesla": ("Tesla", "테슬라"),
    "bmw": ("BMW", "BMW"),
    "mercedes-benz": ("Mercedes-Benz", "벤츠"),
    "audi": ("Audi", "아우디"),
    "volkswagen": ("Volkswagen", "폭스바겐"),
    "toyota": ("Toyota", "도요타"),
    "honda": ("Honda", "혼다"),
    "ford": ("Ford", "포드"),
    "chevrolet": ("Chevrolet", "쉐보레"),
    "aston-martin": ("Aston Martin", "애스턴 마틴"),
    "land-rover": ("Land Rover", "랜드로버"),
    "alfa-romeo": ("Alfa Romeo", "알파 로메오"),
    "rolls-royce": ("Rolls-Royce", "롤스로이스"),
}

# Test/Generic entries that should be marked as not_vehicle
_NOT_VEHICLE_MARKERS = {
    "comma",
    "_테스트_예제",
    "_공통_센서",
    "공용규격",
    "공통규격",
}

# In-memory cache for aliases loaded from database
_ALIASES_CACHE = None
_REVERSE_LOOKUP_CACHE = None


def _load_aliases_from_db():
    """Load maker aliases from database into memory cache.
    
    Returns:
        dict: {alias.lower(): standard_key} for fast lookup
        dict: {standard_key: (english_name, korean_name)} for display
    """
    global _ALIASES_CACHE, _REVERSE_LOOKUP_CACHE
    
    if _ALIASES_CACHE is not None:
        return _ALIASES_CACHE, _REVERSE_LOOKUP_CACHE
    
    try:
        from app.extensions import db
        from sqlalchemy import text
        
        # Load all aliases
        result = db.session.execute(text("""
            SELECT standard_key, english_name, korean_name, aliases
            FROM maker_aliases
        """)).fetchall()
        
        aliases_map = {}
        display_map = {}
        
        for row in result:
            standard_key, english_name, korean_name, aliases = row
            
            # Map each alias to standard_key (case-insensitive)
            for alias in aliases:
                aliases_map[alias.lower()] = standard_key
            
            # Also map standard_key, english_name, korean_name to themselves
            aliases_map[standard_key.lower()] = standard_key
            aliases_map[english_name.lower()] = standard_key
            aliases_map[korean_name.lower()] = standard_key
            
            # Store display names
            display_map[standard_key] = (english_name, korean_name)
        
        _ALIASES_CACHE = aliases_map
        _REVERSE_LOOKUP_CACHE = display_map
        
        return aliases_map, display_map
    
    except Exception:
        # Database not available or table doesn't exist yet
        # Use fallback
        return _FALLBACK_ALIASES, _DISPLAY_NAMES


def resolve_maker(name: str | None) -> str | None:
    """Resolve any maker name/alias to standard key.
    
    Args:
        name: Any variation (English, Korean, mixed case, etc.)
        
    Returns:
        standard_key (e.g., 'hyundai', 'kia', 'aston-martin') or None
    """
    if name is None:
        return None
    
    text = str(name).strip()
    if not text or text == '_':
        return None
    
    # Check for not_vehicle markers
    if text in _NOT_VEHICLE_MARKERS or text.startswith('AAA_') or text.startswith('_공통'):
        return None
    
    # Handle 'Maker_ Model' patterns (e.g., 'BMW_ i3')
    if '_' in text:
        parts = text.split('_', 1)
        if len(parts) == 2:
            maker_part = parts[0].strip()
            if maker_part:
                # Try to resolve just the maker part
                resolved = resolve_maker(maker_part)
                return resolved if resolved else None
            else:
                return None
    
    # Handle 'Maker Model Year' patterns (e.g., 'Subaru Outback 2.5na Gen6')
    if ' ' in text:
        if re.search(r'\d{4}|Gen\d|\d\.\d|[Nn]a\b|R\d{3}|Ph\d', text):
            maker_part = text.split()[0].strip()
            return resolve_maker(maker_part)
    
    # Look up in aliases
    aliases_map, _ = _load_aliases_from_db()
    standard_key = aliases_map.get(text.lower())
    
    if standard_key:
        return standard_key
    
    # Not found in aliases, return as-is (after trimming)
    # This preserves unknown makers unchanged
    return text if text and not text.startswith('_') else None


def normalize_maker(name: str | None) -> str | None:
    """Normalize maker name to standard key.
    
    This is the main function used by ORM @validates decorators.
    It returns the input unchanged if it's already a known value in the database,
    or resolves it to standard key if it's an alias.
    
    Args:
        name: Any maker name variation
        
    Returns:
        Resolved maker name (keeps existing values, resolves new aliases)
    """
    if name is None:
        return None
    
    # Resolve to standard key
    resolved = resolve_maker(name)
    
    # For backward compatibility, if the input is already in the database as-is,
    # keep it unchanged. Only resolve if it's a known alias.
    # This prevents changing existing 'Hyundai' to 'hyundai' in the database.
    
    # Check if input matches a display name (English or Korean)
    _, display_map = _load_aliases_from_db()
    
    for standard_key, (eng, kor) in display_map.items():
        if name == eng or name == kor:
            # Input is already a display name, keep it
            return name
    
    # Input is an alias or unknown, return resolved standard_key
    return resolved


def get_maker_display(maker_value: str | None, format: str = 'both') -> str | None:
    """Get display name for maker.
    
    Args:
        maker_value: Maker value from database (could be standard key, English, Korean, or alias)
        format: 'both' (default) -> "Korean (English)"
                'korean' -> "Korean"
                'english' -> "English"
                'english_first' -> "English (Korean)"
    
    Returns:
        Formatted display string or original value if not in aliases
    """
    if not maker_value:
        return None
    
    resolved = resolve_maker(maker_value)
    if not resolved:
        return maker_value
    
    _, display_map = _load_aliases_from_db()
    
    if resolved in display_map:
        english, korean = display_map[resolved]
        
        if format == 'korean':
            return korean
        elif format == 'english':
            return english
        elif format == 'english_first':
            return f"{english} ({korean})"
        else:  # 'both' default
            return f"{korean} ({english})"
    
    # Not in display map, return original
    return maker_value


def get_maker_aliases(maker_value: str | None) -> set[str]:
    """Get all aliases for a maker (for search/filter queries).
    
    Args:
        maker_value: Any maker name
        
    Returns:
        Set of all variations that should match this maker
    """
    if not maker_value:
        return set()
    
    resolved = resolve_maker(maker_value)
    if not resolved:
        return {maker_value}
    
    aliases_map, display_map = _load_aliases_from_db()
    
    # Find all aliases that resolve to the same standard_key
    matching_aliases = set()
    for alias, standard_key in aliases_map.items():
        if standard_key == resolved:
            matching_aliases.add(alias)
            matching_aliases.add(alias.upper())
            matching_aliases.add(alias.title())
    
    # Also add the display names
    if resolved in display_map:
        english, korean = display_map[resolved]
        matching_aliases.add(english)
        matching_aliases.add(korean)
    
    matching_aliases.add(resolved)
    return matching_aliases


def extract_model_from_maker_field(maker_value: str | None) -> tuple[str | None, str | None]:
    """Extract (maker, model) from a combined maker field.
    
    Used by CLI to split 'Maker_ Model' patterns where model column is empty.
    Returns: (maker, model) where model is None if no extraction needed
    """
    if not maker_value:
        return (None, None)
    
    text = maker_value.strip()
    
    # Check for 'Maker_ Model' pattern or 'Maker_' (trailing underscore)
    if '_' in text:
        parts = text.split('_', 1)
        if len(parts) == 2:
            maker_part = parts[0].strip()
            model_part = parts[1].strip()
            
            if maker_part:
                # Resolve maker
                resolved_maker = resolve_maker(maker_part)
                if model_part:
                    # Has model part
                    return (resolved_maker, model_part)
                else:
                    # Trailing underscore only (e.g., 'Toyota_')
                    return (resolved_maker, None)
    
    # Check for 'Maker Model Year' pattern (e.g., 'Renault Zoe R110')
    if ' ' in text:
        if re.search(r'\d{4}|Gen\d|\d\.\d|[Nn]a\b|R\d{3}|Ph\d', text):
            parts = text.split(None, 1)  # Split on first whitespace
            if len(parts) == 2:
                maker_part = parts[0].strip()
                model_part = parts[1].strip()
                
                resolved_maker = resolve_maker(maker_part)
                return (resolved_maker, model_part)
    
    # No extraction needed
    return (resolve_maker(text), None)


def derive_maker_from_path(file_path: str | None, model: str | None) -> str | None:
    """Derive maker from file path when maker is NULL.
    
    Returns standard_key if matched, None otherwise.
    """
    if not file_path and not model:
        return None
    
    # CanZE is Renault-only
    if file_path and ('canze' in file_path.lower() or 'can-ze' in file_path.lower()):
        return 'renault'
    
    # Check path for explicit maker names
    if file_path:
        path_lower = file_path.lower()
        aliases_map, _ = _load_aliases_from_db()
        
        for alias, standard_key in aliases_map.items():
            if alias in path_lower:
                return standard_key
    
    # Check model for known model→maker mappings
    if model:
        model_lower = model.lower()
        
        # Hyundai models
        if any(m in model_lower for m in ['ioniq', 'kona', 'venue']):
            return 'hyundai'
        
        # Kia models
        if any(m in model_lower for m in ['niro', 'soul', 'ray', 'ev6', 'ev9']):
            return 'kia'
        
        # Renault models
        if any(m in model_lower for m in ['zoe', 'twingo', 'kangoo']):
            return 'renault'
        
        # Tesla models
        if any(m in model_lower for m in ['model 3', 'model s', 'model x', 'model y']):
            return 'tesla'
    
    return None


def is_not_vehicle_maker(name: str | None) -> bool:
    """Check if maker name indicates test/generic/non-vehicle entry."""
    if not name:
        return False
    
    text = str(name).strip().lower()
    
    # Check exact matches
    if text in _NOT_VEHICLE_MARKERS:
        return True
    
    # Check prefixes
    if text.startswith('aaa_') or text.startswith('_공통') or text.startswith('_테스트'):
        return True
    
    # Check if it contains '공용' or '공통' (shared/common definitions)
    if '공용' in text or '공통' in text:
        return True
    
    return False


# For backward compatibility
def maker_aliases(name: str | None) -> set[str]:
    """Alias for get_maker_aliases (backward compatibility)."""
    return get_maker_aliases(name)
