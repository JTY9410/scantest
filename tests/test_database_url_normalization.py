"""Test DATABASE_URL normalization for psycopg3 compatibility."""

import pytest


def test_postgres_scheme_normalized_to_psycopg(monkeypatch):
    """Test that postgres:// is normalized to postgresql+psycopg://"""
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@host:5432/db")
    
    from app.config import database_url
    url = database_url()
    
    assert url == "postgresql+psycopg://user:pass@host:5432/db"
    assert "postgres://" not in url
    assert "+psycopg" in url


def test_postgresql_scheme_normalized_to_psycopg(monkeypatch):
    """Test that postgresql:// is normalized to postgresql+psycopg://"""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host:5432/db")
    
    from app.config import database_url
    url = database_url()
    
    assert url == "postgresql+psycopg://user:pass@host:5432/db"
    assert "+psycopg" in url


def test_postgresql_psycopg_unchanged(monkeypatch):
    """Test that postgresql+psycopg:// is not double-normalized"""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@host:5432/db")
    
    from app.config import database_url
    url = database_url()
    
    assert url == "postgresql+psycopg://user:pass@host:5432/db"
    assert url.count("+psycopg") == 1


def test_postgres_with_query_params(monkeypatch):
    """Test normalization preserves query parameters"""
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@host:5432/db?sslmode=require")
    
    from app.config import database_url
    url = database_url()
    
    assert url == "postgresql+psycopg://user:pass@host:5432/db?sslmode=require"
    assert "sslmode=require" in url


def test_supa_param_removed(monkeypatch):
    """Test that supa query parameter is removed (Supabase pooler adds it, psycopg rejects it)"""
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@host:5432/db?supa=pooler&sslmode=require")
    
    from app.config import database_url
    url = database_url()
    
    assert url == "postgresql+psycopg://user:pass@host:5432/db?sslmode=require"
    assert "supa" not in url
    assert "sslmode=require" in url


def test_alembic_env_normalization(monkeypatch):
    """Test that Alembic env.py normalizes URLs correctly"""
    # Test the normalization function directly by importing it from the module file
    import sys
    import importlib.util
    
    spec = importlib.util.spec_from_file_location("migrations.env", "migrations/env.py")
    env_module = importlib.util.module_from_spec(spec)
    
    # Mock alembic context to prevent initialization errors
    import types
    mock_context = types.ModuleType('alembic.context')
    mock_context.config = None
    sys.modules['alembic.context'] = mock_context
    
    spec.loader.exec_module(env_module)
    normalize_database_url = env_module.normalize_database_url
    
    test_cases = [
        ("postgres://user:pass@host:5432/db", "postgresql+psycopg://user:pass@host:5432/db"),
        ("postgresql://user:pass@host:5432/db", "postgresql+psycopg://user:pass@host:5432/db"),
        ("postgresql+psycopg://user:pass@host:5432/db", "postgresql+psycopg://user:pass@host:5432/db"),
    ]
    
    for input_url, expected_url in test_cases:
        result = normalize_database_url(input_url)
        assert result == expected_url, f"Failed for {input_url}: got {result}"
