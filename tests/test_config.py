from sqlalchemy.pool import NullPool

from app.config import engine_options


def test_default_engine_keeps_a_checked_pool(monkeypatch):
    monkeypatch.delenv("DATABASE_POOL", raising=False)

    assert engine_options() == {"pool_pre_ping": True}


def test_serverless_engine_uses_no_pool_and_no_prepared_statements(monkeypatch):
    monkeypatch.setenv("DATABASE_POOL", "none")

    assert engine_options() == {"poolclass": NullPool, "connect_args": {"prepare_threshold": None}}
