import bcrypt
from sqlalchemy import select

from app.extensions import db
from app.modules.accounts.models import User
from tests.conftest import PASSWORD, api_login


def test_login_returns_token_pair_in_camel_case(client, make_user):
    make_user("tester1")
    body = client.post("/api/auth/login", json={"tid": "tester1", "password": PASSWORD}).get_json()

    assert body["tokenType"] == "bearer"
    assert body["expiresIn"] == 3600
    assert body["accessToken"] and body["refreshToken"]
    assert body["user"]["tid"] == "tester1"
    assert "password" not in body["user"] and "apiKey" not in body["user"]
    assert list(body["user"])[:3] == ["id", "companyId", "type"]


def test_login_rejects_wrong_password(client, make_user):
    make_user("tester1")
    response = client.post("/api/auth/login", json={"tid": "tester1", "password": "wrong-pass"})

    assert response.status_code == 400
    assert response.get_json()["message"] == "아이디 또는 비밀번호가 일치하지 않습니다."


def test_login_validation_summarizes_errors_like_laravel(client):
    response = client.post("/api/auth/login", json={})

    assert response.status_code == 422
    body = response.get_json()
    assert body["message"] == "아이디를 입력해주세요. (and 1 more error)"
    assert set(body["errors"]) == {"tid", "password"}


def test_legacy_laravel_bcrypt_hash_is_accepted_and_upgraded(app, client, make_user):
    legacy = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode().replace("$2b$", "$2y$", 1)
    make_user("legacy", password_hash=legacy)

    api_login(client, "legacy")

    with app.app_context():
        stored = db.session.scalar(select(User.password).where(User.tid == "legacy"))
    assert not stored.startswith("$2")


def test_me_logout_and_blocklist(client, make_user):
    make_user("tester1")
    headers = api_login(client, "tester1")

    assert client.get("/api/auth/me", headers=headers).get_json()["user"]["tid"] == "tester1"
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_refresh_rotates_token(client, make_user):
    make_user("tester1")
    first = client.post("/api/auth/login", json={"tid": "tester1", "password": PASSWORD}).get_json()

    rotated = client.post("/api/auth/refresh", json={"refreshToken": first["refreshToken"]})
    assert rotated.status_code == 200
    assert rotated.get_json()["refreshToken"] != first["refreshToken"]

    reused = client.post("/api/auth/refresh", json={"refreshToken": first["refreshToken"]})
    assert reused.status_code == 401


def test_invalidate_all_tokens_revokes_old_access_token(client, make_user):
    make_user("tester1")
    old = api_login(client, "tester1")

    new_pair = client.post("/api/auth/invalidateAllTokens", headers=old).get_json()

    assert client.get("/api/auth/me", headers=old).status_code == 401
    fresh = {"Authorization": f"Bearer {new_pair['accessToken']}"}
    assert client.get("/api/auth/me", headers=fresh).status_code == 200


def _registration(**overrides):
    data = {
        "type": "tester",
        "mobile": "01012345678",
        "tid": "newbie",
        "name": "새회원",
        "password": "secret-123",
        "passwordConfirmation": "secret-123",
    }
    data.update(overrides)
    return data


def test_register_creates_member_who_can_log_in(client):
    response = client.post("/api/auth/register", json=_registration())

    assert response.status_code == 201
    api_login(client, "newbie", "secret-123")


def test_public_register_cannot_create_admin(app, client):
    response = client.post("/api/auth/register", json=_registration(type="admin"))

    assert response.status_code == 422
    assert response.get_json()["errors"]["type"] == ["유효하지 않은 사용자 타입입니다."]
    with app.app_context():
        assert db.session.scalar(select(User).where(User.tid == "newbie")) is None


def test_register_validate_checks_only_given_fields(client, make_user):
    make_user("taken")
    response = client.post("/api/auth/registerValidate", json={"tid": "taken"})

    assert response.status_code == 422
    assert set(response.get_json()["errors"]) == {"tid"}


def test_sms_verification_flow_resets_password(client, make_user):
    make_user("tester1", mobile="01011112222")
    key = {"mobile": "010-1111-2222", "smsCodeKey": "k1"}

    assert client.post("/api/auth/requestSms", json={**key, "tid": "tester1"}).status_code == 200
    assert client.post("/api/auth/verifySms", json={**key, "smsCode": "1111"}).status_code == 200
    reset = client.post(
        "/api/auth/setPasswordByVerifySms",
        json={**key, "smsCode": "1111", "tid": "tester1",
              "password": "brand-new-1", "passwordConfirmation": "brand-new-1"},
    )
    assert reset.status_code == 200

    api_login(client, "tester1", "brand-new-1")
    again = client.post(
        "/api/auth/setPasswordByVerifySms",
        json={**key, "smsCode": "1111", "tid": "tester1",
              "password": "other-pass-1", "passwordConfirmation": "other-pass-1"},
    )
    assert again.status_code == 400


def test_withdraw_blocks_further_login(client, make_user):
    make_user("tester1")
    headers = api_login(client, "tester1")

    assert client.post("/api/auth/withdraw", headers=headers, json={"message": "그만"}).status_code == 200
    response = client.post("/api/auth/login", json={"tid": "tester1", "password": PASSWORD})
    assert response.get_json()["message"] == "탈퇴한 사용자입니다."


def test_unknown_api_route_returns_json_404(client):
    response = client.get("/api/nothing-here")

    assert response.status_code == 404
    assert response.get_json()["message"] == "요청한 API를 찾을 수 없습니다."
