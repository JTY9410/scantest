from sqlalchemy.pool import NullPool

from app.config import database_url, engine_options


def test_database_url_prefers_explicit_setting(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://app@db/app")
    monkeypatch.setenv("POSTGRES_URL", "postgres://other@host/other")

    assert database_url() == "postgresql+psycopg://app@db/app"


def test_database_url_converts_vercel_supabase_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "POSTGRES_URL",
        "postgres://postgres.ref:p%40ss@pooler.supabase.com:6543/postgres?sslmode=require&supa=base-pooler.x",
    )

    assert database_url() == (
        "postgresql+psycopg://postgres.ref:p%40ss@pooler.supabase.com:6543/postgres?sslmode=require"
    )


def test_database_url_missing(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)

    assert database_url() is None


def test_default_engine_keeps_a_checked_pool(monkeypatch):
    monkeypatch.delenv("DATABASE_POOL", raising=False)

    assert engine_options() == {"pool_pre_ping": True}


def test_serverless_engine_uses_no_pool_and_no_prepared_statements(monkeypatch):
    monkeypatch.setenv("DATABASE_POOL", "none")

    assert engine_options() == {"poolclass": NullPool, "connect_args": {"prepare_threshold": None}}
