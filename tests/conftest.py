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
def _app_base():
    """Session-scoped app for creating schema once"""
    app = create_app("testing")
    with app.app_context():
        # Use CASCADE to handle foreign key dependencies added by migrations
        db.session.execute(text("DROP SCHEMA public CASCADE"))
        db.session.execute(text("CREATE SCHEMA public"))
        db.session.commit()
        db.create_all()
    yield app
    with app.app_context():
        db.session.execute(text("DROP SCHEMA public CASCADE"))
        db.session.execute(text("CREATE SCHEMA public"))
        db.session.commit()


@pytest.fixture
def app(_app_base):
    """Function-scoped app context to avoid lock issues"""
    return _app_base


@pytest.fixture(autouse=True)
def _clean_database(app):
    yield
    with app.app_context():
        # Close all existing connections first
        db.session.rollback()
        db.session.remove()
        db.engine.dispose()
        
        if "sqlite" in app.config["SQLALCHEMY_DATABASE_URI"]:
            for table in reversed(db.metadata.sorted_tables):
                db.session.execute(text(f"DELETE FROM {table.name}"))
            try:
                db.session.execute(text("DELETE FROM sqlite_sequence"))
            except Exception:
                pass
            db.session.commit()
        else:
            # Postgres: TRUNCATE all tables excluding alembic_version
            db.session.execute(text("SET lock_timeout = '5s'"))
            tables = [t.name for t in db.metadata.sorted_tables if t.name != 'alembic_version']
            if tables:
                tables_str = ", ".join(tables)
                db.session.execute(text(f"TRUNCATE {tables_str} RESTART IDENTITY CASCADE"))
            db.session.commit()
        db.session.remove()
    
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
    if not match:
        # CSRF disabled in testing - return empty string
        return ""
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
