"""기능 플래그 조회. Flask 앱 밖(순수 엔진 테스트)에서는 환경변수를 본다."""

from __future__ import annotations

import os


def flag(name: str, default: bool = False) -> bool:
    try:
        from flask import current_app, has_app_context
        if has_app_context():
            return bool(current_app.config.get(name, default))
    except Exception:
        pass
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
