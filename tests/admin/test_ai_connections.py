import httpx
from sqlalchemy import select

from app.core.audit import Activity
from app.core.crypto import decrypt
from app.extensions import db
from app.modules.admin import ai_service
from app.modules.admin.models import AiConnection
from tests.conftest import csrf_token

SECRET_KEY = "sk-test-abcdefghijklmnop-WXYZ"


def _setup_openai(client) -> str:
    token = csrf_token(client, "/admin/ai/openai")
    client.post(
        "/admin/ai/openai",
        data={"csrf_token": token, "settings-model": "gpt-test", "settings-features": ["canlab"],
              "settings-monthly_budget": "50.00", "settings-monthly_token_limit": "100000"},
    )
    client.post("/admin/ai/openai/key", data={"csrf_token": token, "key-api_key": SECRET_KEY})
    return token


def _connection(app) -> AiConnection:
    with app.app_context():
        connection = db.session.scalar(select(AiConnection))
        db.session.expunge(connection)
        return connection


def test_key_is_encrypted_and_only_last4_is_shown(app, admin_client):
    _setup_openai(admin_client)

    connection = _connection(app)
    assert connection.key_enc != SECRET_KEY and SECRET_KEY not in connection.key_enc
    with app.app_context():
        assert decrypt(connection.key_enc) == SECRET_KEY
    assert connection.key_last4 == "WXYZ"
    assert str(connection.monthly_budget) == "50.00"
    assert connection.features == {"canlab": True}

    for url in ("/admin/ai", "/admin/ai/openai"):
        html = admin_client.get(url).get_data(as_text=True)
        assert SECRET_KEY not in html and "WXYZ" in html

    with app.app_context():
        logged = " ".join(str(a.changes) for a in db.session.scalars(select(Activity)).all())
    assert SECRET_KEY not in logged


def test_connection_test_records_result(app, admin_client, monkeypatch):
    token = _setup_openai(admin_client)
    seen = {}

    def fake_probe(provider, model, api_key):
        seen.update(provider=provider, model=model, api_key=api_key)
        return httpx.Response(401)

    monkeypatch.setattr(ai_service, "_probe", fake_probe)
    admin_client.post("/admin/ai/openai/test", data={"csrf_token": token})

    assert seen == {"provider": "openai", "model": "gpt-test", "api_key": SECRET_KEY}
    connection = _connection(app)
    assert connection.status == "failed"
    assert "인증에 실패" in connection.last_test_message

    monkeypatch.setattr(ai_service, "_probe", lambda *args: httpx.Response(200))
    admin_client.post("/admin/ai/openai/test", data={"csrf_token": token})
    assert _connection(app).status == "ok"


def test_revoke_removes_key_and_disables_features(app, admin_client):
    token = _setup_openai(admin_client)

    admin_client.post("/admin/ai/openai/revoke", data={"csrf_token": token})

    connection = _connection(app)
    assert connection.key_enc is None and connection.key_last4 is None
    assert connection.status == "revoked"
    assert not any(connection.features.values())
    with app.app_context():
        actions = set(db.session.scalars(select(Activity.relation_type)).all())
    assert {"AI 연결 생성", "AI 키 등록", "AI 키 폐기"} <= actions


def test_settings_conflict_is_detected(app, admin_client):
    token = _setup_openai(admin_client)
    stale_version = _connection(app).version
    admin_client.post(
        "/admin/ai/openai",
        data={"csrf_token": token, "settings-model": "gpt-a", "settings-version": stale_version},
    )

    response = admin_client.post(
        "/admin/ai/openai",
        data={"csrf_token": token, "settings-model": "gpt-b", "settings-version": stale_version},
    )

    assert "다른 관리자가 먼저 수정했습니다." in response.get_data(as_text=True)
    assert _connection(app).model == "gpt-a"


def test_unknown_provider_is_rejected(admin_client):
    response = admin_client.get("/admin/ai/unknown")

    assert response.status_code == 302
