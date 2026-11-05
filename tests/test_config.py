from sqlalchemy.pool import NullPool

from app.config import database_url, engine_options, proxy_fix_hops


def test_database_url_prefers_explicit_setting(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://app@db/app")
    monkeypatch.setenv("POSTGRES_URL", "postgres://other@host/other")

    assert database_url() == "postgresql+psycopg://app@db/app"


def test_database_url_converts_postgres_scheme_and_drops_supa_param(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgres://postgres.ref:p%40ss@pooler.supabase.com:6543/postgres?sslmode=require&supa=base-pooler.x",
    )

    assert database_url() == (
        "postgresql+psycopg://postgres.ref:p%40ss@pooler.supabase.com:6543/postgres?sslmode=require"
    )


def test_database_url_ignores_postgres_url_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "POSTGRES_URL",
        "postgres://other@host/other",
    )

    assert database_url() is None


def test_database_url_missing(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)

    assert database_url() is None


def test_default_engine_keeps_a_checked_pool(monkeypatch):
    monkeypatch.delenv("DATABASE_POOL", raising=False)

    assert engine_options() == {"pool_pre_ping": True}


def test_poolless_engine_uses_no_pool_and_no_prepared_statements(monkeypatch):
    monkeypatch.setenv("DATABASE_POOL", "none")

    assert engine_options() == {"poolclass": NullPool, "connect_args": {"prepare_threshold": None}}


def test_proxy_fix_hops_defaults_to_one(monkeypatch):
    monkeypatch.delenv("PROXY_FIX_HOPS", raising=False)
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    assert proxy_fix_hops() == 1


def test_proxy_fix_hops_prefers_explicit_proxy_fix_hops(monkeypatch):
    monkeypatch.setenv("PROXY_FIX_HOPS", "2")
    monkeypatch.setenv("TRUST_PROXY", "0")
    assert proxy_fix_hops() == 2


def test_trust_proxy_alias_disables_proxy_fix(monkeypatch):
    monkeypatch.delenv("PROXY_FIX_HOPS", raising=False)
    monkeypatch.setenv("TRUST_PROXY", "0")
    assert proxy_fix_hops() == 0


def test_trust_proxy_alias_enables_one_hop(monkeypatch):
    monkeypatch.delenv("PROXY_FIX_HOPS", raising=False)
    monkeypatch.setenv("TRUST_PROXY", "1")
    assert proxy_fix_hops() == 1


def test_upload_limit_defaults_to_docker_size(app):
    """업로드 한도 기본값은 도커 기준 64MB(큰 CAN 기록 허용)."""
    assert app.config["CANLAB_MAX_UPLOAD_BYTES"] == 64 * 1024 * 1024


def test_vehicle_network_is_open_by_default_and_blocked_by_setting(monkeypatch):
    from app.modules.scanner.transport.base import serverless

    monkeypatch.delenv("VEHICLE_NETWORK_BLOCKED", raising=False)
    monkeypatch.setenv("VERCEL", "1")  # 예전 플랫폼 변수는 더 이상 영향 없음
    assert serverless() is False
    monkeypatch.setenv("VEHICLE_NETWORK_BLOCKED", "1")
    assert serverless() is True
