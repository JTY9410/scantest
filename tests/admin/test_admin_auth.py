import pyotp
from sqlalchemy import select

from app.core.audit import Activity
from app.core.crypto import encrypt
from app.extensions import db
from app.modules.accounts.models import User
from tests.conftest import ADMIN_PASSWORD, PASSWORD, admin_login, csrf_token


def test_admin_pages_require_login(client):
    response = client.get("/admin/")

    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]


def test_login_page_sends_security_headers(client):
    response = client.get("/admin/login")

    assert response.status_code == 200
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"


def test_login_requires_csrf_token(client, make_user):
    make_user("wecar", type="admin", password=ADMIN_PASSWORD)

    response = client.post("/admin/login", data={"tid": "wecar", "password": ADMIN_PASSWORD})

    assert response.status_code == 400


def test_wrong_password_is_rejected_and_audited(app, client, make_user):
    make_user("wecar", type="admin", password=ADMIN_PASSWORD)

    response = admin_login(client, password="not-the-password")

    assert response.status_code == 401
    assert "아이디 또는 비밀번호가 올바르지 않습니다." in response.get_data(as_text=True)
    with app.app_context():
        actions = db.session.scalars(select(Activity.relation_type)).all()
    assert actions == ["관리자 로그인 실패"]


def test_non_admin_member_cannot_log_in(client, make_user):
    make_user("tester1", type="tester")

    assert admin_login(client, "tester1", PASSWORD).status_code == 401


def test_login_regenerates_session(client, make_user):
    make_user("wecar", type="admin", password=ADMIN_PASSWORD)
    token = csrf_token(client, "/admin/login")
    with client.session_transaction() as sess:
        sess["planted"] = "attacker-value"

    response = client.post("/admin/login", data={"csrf_token": token, "tid": "wecar", "password": ADMIN_PASSWORD})

    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert "planted" not in sess
        assert sess.get("_user_id") == "1"


def test_login_is_rate_limited(client, make_user):
    make_user("wecar", type="admin", password=ADMIN_PASSWORD)
    statuses = [admin_login(client, password="wrong").status_code for _ in range(6)]

    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429


def test_logout_requires_post_and_ends_session(admin_client):
    assert admin_client.get("/admin/logout").status_code == 405
    token = csrf_token(admin_client, "/admin/")

    admin_client.post("/admin/logout", data={"csrf_token": token})

    assert admin_client.get("/admin/").status_code == 302


def test_mfa_is_required_once_enabled(app, client, make_user):
    secret = pyotp.random_base32()
    with app.app_context():
        user_id = make_user("wecar", type="admin", password=ADMIN_PASSWORD)
        user = db.session.get(User, user_id)
        user.totp_secret_enc = encrypt(secret)
        db.session.commit()

    response = admin_login(client)
    assert response.headers["Location"].endswith("/admin/mfa")
    assert client.get("/admin/").status_code == 302

    token = csrf_token(client, "/admin/mfa")
    wrong = client.post("/admin/mfa", data={"csrf_token": token, "code": "000000"})
    assert "OTP 코드가 맞지 않습니다." in wrong.get_data(as_text=True)

    ok = client.post("/admin/mfa", data={"csrf_token": token, "code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 302
    assert client.get("/admin/").status_code == 200


def test_admin_can_enroll_otp_and_password_change(app, admin_client):
    token = csrf_token(admin_client, "/admin/account")
    admin_client.post("/admin/account/mfa/start", data={"csrf_token": token})
    with admin_client.session_transaction() as sess:
        secret = sess["mfa_setup_secret"]

    page = admin_client.get("/admin/account").get_data(as_text=True)
    assert secret in page and "<svg" in page

    admin_client.post(
        "/admin/account/mfa/confirm",
        data={"csrf_token": token, "otp-code": pyotp.TOTP(secret).now()},
    )
    with app.app_context():
        user = db.session.scalar(select(User).where(User.tid == "wecar"))
        assert user.mfa_enabled and secret not in user.totp_secret_enc

    changed = admin_client.post(
        "/admin/account",
        data={"csrf_token": token, "pw-current_password": ADMIN_PASSWORD,
              "pw-new_password": "new-admin-pass-2", "pw-confirm_password": "new-admin-pass-2"},
    )
    assert changed.status_code == 302


def test_create_admin_command(app):
    runner = app.test_cli_runner()

    env = {"ADMIN_PASSWORD": ADMIN_PASSWORD}
    result = runner.invoke(args=["create-admin", "--tid", "wecar"], env=env)
    assert result.exit_code == 0, result.output

    again = runner.invoke(args=["create-admin", "--tid", "wecar"], env=env)
    assert again.exit_code != 0
    assert "이미 존재하는 아이디" in again.output

    with app.app_context():
        user = db.session.scalar(select(User).where(User.tid == "wecar"))
        assert user.is_admin and ADMIN_PASSWORD not in user.password


def test_create_admin_reads_tid_from_env(app, client):
    runner = app.test_cli_runner()

    result = runner.invoke(args=["create-admin"],
                           env={"ADMIN_TID": "wecar", "ADMIN_PASSWORD": ADMIN_PASSWORD})

    assert result.exit_code == 0, result.output
    assert admin_login(client, "wecar", ADMIN_PASSWORD).status_code == 302
