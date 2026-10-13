"""관리자 AI 연결 설정 업무 규칙.

- 공급자별로 한 건만 둔다.
- 키는 Fernet으로 암호화해 저장하고 평문은 다시 내보내지 않는다(끝 4자리만 표시).
- 변경·연결 테스트는 감사 기록에 남기되 키는 기록하지 않는다.
"""

from decimal import Decimal
from typing import Any

import httpx
from flask import current_app
from sqlalchemy import select

from app.core import audit
from app.core.crypto import decrypt, encrypt
from app.core.errors import ServiceError
from app.core.time import utcnow
from app.extensions import db
from app.modules.accounts.models import User
from app.modules.admin.models import AI_FEATURES, AiConnection, AiProvider, AiStatus

CONFLICT = "다른 관리자가 먼저 수정했습니다. 새로고침한 뒤 다시 저장하세요."


def connections_by_provider() -> dict[str, AiConnection | None]:
    rows = {c.provider: c for c in db.session.scalars(select(AiConnection)).all()}
    return {p.value: rows.get(p.value) for p in AiProvider}


def get_connection(provider: str) -> AiConnection | None:
    if provider not in AiProvider.__members__.values():
        raise ServiceError("지원하지 않는 AI 공급자입니다.", 404)
    return db.session.scalar(select(AiConnection).where(AiConnection.provider == provider))


def _require(provider: str) -> AiConnection:
    connection = get_connection(provider)
    if connection is None:
        raise ServiceError("먼저 모델과 사용 설정을 저장하세요.", 400)
    return connection


def save_settings(
    actor: User,
    provider: str,
    *,
    model: str,
    features: list[str],
    monthly_budget: Decimal | None,
    monthly_token_limit: int | None,
    version: int | None,
) -> AiConnection:
    connection = get_connection(provider)
    enabled = {key: key in features for key in AI_FEATURES}
    if connection is None:
        connection = AiConnection(provider=provider, status=AiStatus.NO_KEY)
        db.session.add(connection)
        action = "AI 연결 생성"
    else:
        if version is not None and version != connection.version:
            raise ServiceError(CONFLICT, 409)
        action = "AI 연결 설정 변경"
    before = {
        "model": connection.model,
        "features": connection.features,
        "monthly_budget": str(connection.monthly_budget) if connection.monthly_budget else None,
        "monthly_token_limit": connection.monthly_token_limit,
    }
    connection.model = model.strip()
    connection.features = enabled
    connection.monthly_budget = monthly_budget
    connection.monthly_token_limit = monthly_token_limit
    db.session.flush()
    after = {
        "model": connection.model,
        "features": enabled,
        "monthly_budget": str(monthly_budget) if monthly_budget is not None else None,
        "monthly_token_limit": monthly_token_limit,
    }
    audit.record(action, "AiConnection", connection.id, user_id=actor.id,
                 changes={"provider": provider, "before": before, "after": after})
    db.session.commit()
    return connection


def replace_key(actor: User, provider: str, api_key: str) -> AiConnection:
    api_key = (api_key or "").strip()
    if len(api_key) < 8:
        raise ServiceError("API 키를 확인하세요.")
    connection = _require(provider)
    had_key = connection.has_key
    connection.key_enc = encrypt(api_key)
    connection.key_last4 = api_key[-4:]
    connection.status = AiStatus.UNTESTED
    connection.last_test_message = None
    audit.record("AI 키 교체" if had_key else "AI 키 등록", "AiConnection", connection.id,
                 user_id=actor.id, changes={"provider": provider, "key_last4": connection.key_last4})
    db.session.commit()
    return connection


def revoke_key(actor: User, provider: str) -> AiConnection:
    connection = _require(provider)
    if not connection.has_key:
        raise ServiceError("폐기할 키가 없습니다.")
    last4 = connection.key_last4
    connection.key_enc = None
    connection.key_last4 = None
    connection.status = AiStatus.REVOKED
    connection.features = {key: False for key in AI_FEATURES}
    audit.record("AI 키 폐기", "AiConnection", connection.id, user_id=actor.id,
                 changes={"provider": provider, "key_last4": last4})
    db.session.commit()
    return connection


def _probe(provider: str, model: str, api_key: str) -> httpx.Response:
    timeout = current_app.config["AI_TEST_TIMEOUT_SECONDS"]
    if provider == AiProvider.OPENAI:
        return httpx.get(f"https://api.openai.com/v1/models/{model}",
                         headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout)
    if provider == AiProvider.ANTHROPIC:
        return httpx.get(f"https://api.anthropic.com/v1/models/{model}",
                         headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                         timeout=timeout)
    return httpx.get(f"https://generativelanguage.googleapis.com/v1beta/models/{model}",
                     headers={"x-goog-api-key": api_key}, timeout=timeout)


def _describe(status_code: int) -> tuple[bool, str]:
    if status_code == 200:
        return True, "모델에 연결했습니다."
    if status_code in (401, 403):
        return False, "인증에 실패했습니다. 키와 권한을 확인하세요."
    if status_code == 404:
        return False, "모델을 찾을 수 없습니다. 모델 이름을 확인하세요."
    if status_code == 429:
        return False, "요청 한도를 초과했습니다. 잠시 후 다시 시도하세요."
    return False, f"공급자 서버가 오류를 반환했습니다(HTTP {status_code})."


def test_connection(actor: User, provider: str) -> AiConnection:
    connection = _require(provider)
    if not connection.has_key:
        raise ServiceError("먼저 API 키를 등록하세요.")
    try:
        response = _probe(provider, connection.model, decrypt(connection.key_enc))
        ok, message = _describe(response.status_code)
    except httpx.TimeoutException:
        ok, message = False, "응답 시간이 초과되었습니다."
    except httpx.HTTPError as exc:
        ok, message = False, f"연결할 수 없습니다({type(exc).__name__})."
    connection.status = AiStatus.OK if ok else AiStatus.FAILED
    connection.last_tested_at = utcnow()
    connection.last_test_message = message
    audit.record("AI 연결 테스트", "AiConnection", connection.id, user_id=actor.id,
                 changes={"provider": provider, "model": connection.model, "result": message})
    db.session.commit()
    return connection


def features_summary(connection: AiConnection | None) -> list[dict[str, Any]]:
    enabled = (connection.features or {}) if connection else {}
    return [{"key": k, "label": v, "on": bool(enabled.get(k))} for k, v in AI_FEATURES.items()]
