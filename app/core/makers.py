"""제조사 이름 별칭 정규화. 같은 제조사의 여러 표기를 하나의 표시 이름으로 맞춘다.

예: "Nissan", "NISSAN", "nissan", "닛산" → "Nissan"
저장(모델 validates)·조회(서비스 필터)·가져오기(DTC 문서) 모두 이 함수를 거친다.

특수 처리:
- 'Maker_ Model' 패턴 (예: 'Hyundai_ Ioniq', 'VW_ ID'): 언더스코어 앞까지만 maker로 취급
- 비차량 항목 (comma, AAA_ Generic, _테스트_예제, _공통_센서, 공용규격): None 반환
"""

import re

# casefold 한 별칭 → 표시 이름
_ALIASES: dict[str, str] = {
    # Korean/International makers
    "hyundai": "Hyundai",
    "현대": "Hyundai",
    "kia": "Kia",
    "기아": "Kia",
    "genesis": "Genesis",
    "제네시스": "Genesis",
    
    # European - German
    "mercedes-benz": "Mercedes-Benz",
    "mercedes_benz": "Mercedes-Benz",
    "mercedes benz": "Mercedes-Benz",
    "메르세데스-벤츠": "Mercedes-Benz",
    "bmw": "BMW",
    "audi": "Audi",
    "아우디": "Audi",
    "volkswagen": "Volkswagen",
    "vw": "Volkswagen",
    "폭스바겐": "Volkswagen",
    "porsche": "Porsche",
    "포르쉐": "Porsche",
    
    # European - French
    "renault": "Renault",
    "르노": "Renault",
    "peugeot": "Peugeot",
    "푸조": "Peugeot",
    "citroen": "Citroen",
    "citroën": "Citroen",
    "시트로엥": "Citroen",
    
    # European - Italian
    "fiat": "Fiat",
    "fiat_abarth": "Fiat",
    "피아트": "Fiat",
    "alfa romeo": "Alfa Romeo",
    "alfa_romeo": "Alfa Romeo",
    "alfaromeo": "Alfa Romeo",
    "알파로메오": "Alfa Romeo",
    
    # European - Czech/Spanish
    "skoda": "Skoda",
    "škoda": "Skoda",
    "스코다": "Skoda",
    "seat": "Seat",
    "세아트": "Seat",
    
    # European - British
    "jaguar": "Jaguar",
    "재규어": "Jaguar",
    "land rover": "Land Rover",
    "land_rover": "Land Rover",
    "landrover": "Land Rover",
    "랜드로버": "Land Rover",
    "aston martin": "Aston Martin",
    "aston_martin": "Aston Martin",
    "astonmartin": "Aston Martin",
    "mini": "MINI",
    "mini cooper": "MINI",
    "미니": "MINI",
    
    # European - Swedish
    "volvo": "Volvo",
    "볼보": "Volvo",
    "polestar": "Polestar",
    "폴스타": "Polestar",
    
    # European - Other
    "opel": "Opel",
    "오펠": "Opel",
    
    # Motorcycle/Specialty
    "mv agusta": "MV Agusta",
    "mv_agusta": "MV Agusta",
    "mvagusta": "MV Agusta",
    "legend cars": "Legend Cars",
    "legend_cars": "Legend Cars",
    "scca enterprises": "SCCA Enterprises",
    "scca_enterprises": "SCCA Enterprises",
    
    # Japanese
    "nissan": "Nissan",
    "닛산": "Nissan",
    "infiniti": "Infiniti",
    "nissaninfiniti": "Infiniti",
    "인피니티": "Infiniti",
    "toyota": "Toyota",
    "토요타": "Toyota",
    "lexus": "Lexus",
    "렉서스": "Lexus",
    "honda": "Honda",
    "혼다": "Honda",
    "mazda": "Mazda",
    "마쓰다": "Mazda",
    "subaru": "Subaru",
    "스바루": "Subaru",
    "mitsubishi": "Mitsubishi",
    "미쓰비시": "Mitsubishi",
    
    # American
    "ford": "Ford",
    "포드": "Ford",
    "chevrolet": "Chevrolet",
    "chevy": "Chevrolet",
    "쉐보레": "Chevrolet",
    "gmc": "GMC",
    "gm": "GMC",
    "cadillac": "Cadillac",
    "캐딜락": "Cadillac",
    "tesla": "Tesla",
    "테슬라": "Tesla",
    "ram": "Ram",
    "dodge": "Dodge",
    "닷지": "Dodge",
    "jeep": "Jeep",
    "지프": "Jeep",
    "chrysler": "Chrysler",
    "크라이슬러": "Chrysler",
    "lincoln": "Lincoln",
    "링컨": "Lincoln",
    "buick": "Buick",
    "뷰익": "Buick",
    
    # Chinese
    "byd": "BYD",
    "nio": "NIO",
    "xpeng": "Xpeng",
    "샤오펑": "Xpeng",
    "li auto": "Li Auto",
    "li": "Li Auto",
    "리": "Li Auto",
    "mg motor": "MG Motor",
    "mg": "MG Motor",
    "great wall motors": "Great Wall Motors",
    "great wall": "Great Wall Motors",
    "great_wall": "Great Wall Motors",
    "greatwall": "Great Wall Motors",
    "gwm": "Great Wall Motors",
    "장성": "Great Wall Motors",
    "geely": "Geely",
    "지리": "Geely",
    "zeekr": "Zeekr",
    
    # EV Startups
    "rivian": "Rivian",
    "lucid motors": "Lucid Motors",
    "lucid": "Lucid Motors",
    "fisker": "Fisker",
    
    # Other
    "smart": "Smart",
}

# Test/Generic entries that should be marked as not_vehicle
_NOT_VEHICLE_MARKERS = {
    "comma",
    "_테스트_예제",
    "_공통_센서",
    "공용규격",
    "공통규격",
}


def normalize_maker(name: str | None) -> str | None:
    """빈 값은 None, 알려진 별칭은 표시 이름, 나머지는 앞뒤 공백만 정리해 그대로 돌려준다.
    
    특수 처리:
    1. 'Maker_ Model' 패턴: 언더스코어 앞까지만 추출해 정규화
    2. 비차량 항목: None 반환 (나중에 not_vehicle로 분류됨)
    3. 모델명 포함된 패턴 (예: 'Subaru Outback 2.5na Gen6'): 첫 단어만 추출
    
    Returns maker name only (model extraction happens separately in CLI)
    """
    if name is None:
        return None
    
    text = str(name).strip()
    if not text or text == '_':
        return None
    
    # Check for not_vehicle markers
    if text in _NOT_VEHICLE_MARKERS or text.startswith('AAA_') or text.startswith('_공통'):
        return None
    
    # First, check if the text (as-is) matches a known alias
    # This handles maker names like 'Mercedes_Benz', 'Land_Rover', 'Aston_Martin', etc.
    normalized = _ALIASES.get(text.casefold())
    if normalized:
        return normalized
    
    # Handle 'Maker_ Model' patterns (e.g., 'BMW_ i3', 'Fiat_ 600e')
    # Extract maker part before underscore+space
    if '_' in text:
        # Pattern: 'Maker_<space/letter><rest>'
        # Split on underscore and check if there's content after
        parts = text.split('_', 1)
        if len(parts) == 2:
            maker_part = parts[0].strip()
            model_part = parts[1].strip()
            
            # If there's a model part, try to normalize just the maker
            if model_part or not maker_part:  # Empty maker or has model
                if maker_part:
                    normalized = _ALIASES.get(maker_part.casefold(), maker_part)
                    return normalized if normalized and not normalized.startswith('_') else None
                else:
                    # Maker is empty (e.g., '_Tesla'), skip
                    return None
    
    # Handle 'Maker Model Year Variant' patterns (e.g., 'Subaru Outback 2.5na Gen6', 'Renault Zoe R110')
    # Extract only the first word if it looks like a full model path
    if ' ' in text:
        # Check if it contains year patterns or multiple words suggesting it's a full model path
        if re.search(r'\d{4}|Gen\d|\d\.\d|[Nn]a\b|R\d{3}|Ph\d', text):
            # Extract first word as maker
            maker_part = text.split()[0].strip()
            # Try to normalize the extracted maker
            normalized = _ALIASES.get(maker_part.casefold(), maker_part)
            return normalized if normalized and not normalized.startswith('_') else None
    
    # If no special patterns matched, return the text as-is (after trimming)
    return text if text and not text.startswith('_') else None


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
                # Normalize maker
                normalized_maker = _ALIASES.get(maker_part.casefold(), maker_part)
                if model_part:
                    # Has model part
                    return (normalized_maker, model_part)
                else:
                    # Trailing underscore only (e.g., 'Toyota_')
                    return (normalized_maker, None)
    
    # Check for 'Maker Model Year' pattern (e.g., 'Renault Zoe R110')
    if ' ' in text:
        if re.search(r'\d{4}|Gen\d|\d\.\d|[Nn]a\b|R\d{3}|Ph\d', text):
            parts = text.split(None, 1)  # Split on first whitespace
            if len(parts) == 2:
                maker_part = parts[0].strip()
                model_part = parts[1].strip()
                
                normalized_maker = _ALIASES.get(maker_part.casefold(), maker_part)
                return (normalized_maker, model_part)
    
    # No extraction needed
    return (normalize_maker(text), None)


def derive_maker_from_path(file_path: str | None, model: str | None) -> str | None:
    """Derive maker from file path when maker is NULL.
    
    Common patterns:
    - '05_CanZE_조회필드/ZOE' or '05_CanZE_조회필드/Twingo*' → Renault (CanZE is Renault-only)
    - '04_Torque_PID/Ray EV' → Kia
    - Path contains 'Hyundai', 'Kia', etc. → that maker
    - Model 'Ioniq*', 'Kona*' → Hyundai
    - Model 'Niro*', 'Soul*', 'Ray*' → Kia
    - Model 'Zoe', 'Twingo' → Renault
    """
    if not file_path and not model:
        return None
    
    # CanZE is Renault-only
    if file_path and ('canze' in file_path.lower() or 'can-ze' in file_path.lower()):
        return 'Renault'
    
    # Check path for explicit maker names
    if file_path:
        path_lower = file_path.lower()
        for maker_key, maker_name in _ALIASES.items():
            if maker_key in path_lower:
                return maker_name
    
    # Check model for known model→maker mappings
    if model:
        model_lower = model.lower()
        
        # Hyundai models
        if any(m in model_lower for m in ['ioniq', 'kona', 'venue']):
            return 'Hyundai'
        
        # Kia models
        if any(m in model_lower for m in ['niro', 'soul', 'ray', 'ev6', 'ev9']):
            return 'Kia'
        
        # Renault models
        if any(m in model_lower for m in ['zoe', 'twingo', 'kangoo']):
            return 'Renault'
        
        # Tesla models
        if any(m in model_lower for m in ['model 3', 'model s', 'model x', 'model y']):
            return 'Tesla'
    
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


def maker_aliases(name: str | None) -> set[str]:
    """표시 이름과 같은 제조사로 보는 모든 저장 표기(조회용)."""
    canonical = normalize_maker(name)
    if canonical is None:
        return set()
    names = {canonical}
    for alias, target in _ALIASES.items():
        if target == canonical:
            names.update({alias, alias.upper(), alias.title()})
    return names
