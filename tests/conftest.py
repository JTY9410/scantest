import re
from collections.abc import Callable

import pytest
from sqlalchemy import text

from app import create_app
from app.extensions import db, limiter
from app.modules.accounts.models import Company, User
from app.modules.accounts.passwords import hash_password

PASSWORD = "password123"
ADMIN_PASSWORD = "admin-password-1"


@pytest.fixture(scope="session")
def app():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
    yield app
    with app.app_context():
        db.drop_all()


@pytest.fixture(autouse=True)
def _clean_database(app):
    yield
    with app.app_context():
        db.session.remove()
        tables = ", ".join(t.name for t in db.metadata.sorted_tables)
        db.session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        db.session.commit()
    limiter.reset()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_user(app) -> Callable[..., int]:
    def _make(tid: str, type: str = "tester", password: str = PASSWORD, **fields) -> int:
        with app.app_context():
            user = User(
                tid=tid,
                name=fields.pop("name", tid),
                type=type,
                password=fields.pop("password_hash", None) or hash_password(password),
                **fields,
            )
            db.session.add(user)
            db.session.commit()
            return user.id

    return _make


@pytest.fixture
def make_company(app) -> Callable[..., int]:
    def _make(code: str, name: str | None = None) -> int:
        with app.app_context():
            company = Company(code=code, name=name or code)
            db.session.add(company)
            db.session.commit()
            return company.id

    return _make


def csrf_token(client, url: str) -> str:
    html = client.get(url).get_data(as_text=True)
    match = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', html) or re.search(
        r'name="csrf_token" value="([^"]+)"', html
    )
    assert match, f"CSRF 토큰을 찾을 수 없습니다: {url}"
    return match.group(1)


def admin_login(client, tid: str = "wecar", password: str = ADMIN_PASSWORD):
    token = csrf_token(client, "/admin/login")
    return client.post(
        "/admin/login", data={"csrf_token": token, "tid": tid, "password": password}
    )


@pytest.fixture
def admin_client(client, make_user):
    make_user("wecar", type="admin", password=ADMIN_PASSWORD, name="운영관리자")
    response = admin_login(client)
    assert response.status_code == 302
    return client


def api_login(client, tid: str, password: str = PASSWORD) -> dict:
    response = client.post("/api/auth/login", json={"tid": tid, "password": password})
    assert response.status_code == 200, response.get_json()
    return {"Authorization": f"Bearer {response.get_json()['accessToken']}"}
