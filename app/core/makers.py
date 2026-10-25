"""제조사 이름 별칭 정규화. 같은 제조사의 여러 표기를 하나의 표시 이름으로 맞춘다.

예: "Nissan", "NISSAN", "nissan", "닛산" → "닛산"
저장(모델 validates)·조회(서비스 필터)·가져오기(DTC 문서) 모두 이 함수를 거친다.
"""

# casefold 한 별칭 → 표시 이름
_ALIASES: dict[str, str] = {
    "nissan": "닛산",
    "닛산": "닛산",
}


def normalize_maker(name: str | None) -> str | None:
    """빈 값은 None, 알려진 별칭은 표시 이름, 나머지는 앞뒤 공백만 정리해 그대로 돌려준다."""
    if name is None:
        return None
    text = str(name).strip()
    if not text:
        return None
    return _ALIASES.get(text.casefold(), text)


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
