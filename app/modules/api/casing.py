"""Laravel Str::camel / Str::snake 와 같은 규칙으로 키를 변환한다.

기존 모바일 앱은 요청을 camelCase/snake_case 어느 쪽으로 보내도 되고,
응답은 항상 camelCase 키로 받는다.
"""

import re
from functools import lru_cache
from typing import Any

_UCWORDS = re.compile(r"(^|[ \t\r\n\f\v])(\S)")


def _ucwords(value: str) -> str:
    return _UCWORDS.sub(lambda m: m.group(1) + m.group(2).upper(), value)


@lru_cache(maxsize=2048)
def camel(key: str) -> str:
    studly = _ucwords(key.replace("-", " ").replace("_", " ")).replace(" ", "")
    return studly[:1].lower() + studly[1:]


@lru_cache(maxsize=2048)
def snake(key: str) -> str:
    if re.fullmatch(r"[a-z]+", key):
        return key
    value = re.sub(r"\s+", "", _ucwords(key))
    return re.sub(r"(.)(?=[A-Z])", r"\1_", value).lower()


def camelize(data: Any) -> Any:
    if isinstance(data, dict):
        return {camel(str(k)): camelize(v) for k, v in data.items()}
    if isinstance(data, list):
        return [camelize(v) for v in data]
    return data


def snakeize(data: Any) -> Any:
    if isinstance(data, dict):
        return {snake(str(k)): snakeize(v) for k, v in data.items()}
    if isinstance(data, list):
        return [snakeize(v) for v in data]
    return data
