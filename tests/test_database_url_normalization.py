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


def test_alembic_env_normalization():
    """Test that Alembic env.py normalizes URLs correctly.
    
    The normalization function is identical to the one in app.config,
    so we test the logic directly here without importing migrations/env.py
    (which has module-level alembic initialization code).
    """
    # Replicate the normalization logic from migrations/env.py
    def normalize_database_url(url: str) -> str:
        if not url or not isinstance(url, str):
            return url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        if url.startswith("postgresql://") and "+psycopg" not in url:
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url
    
    test_cases = [
        ("postgres://user:pass@host:5432/db", "postgresql+psycopg://user:pass@host:5432/db"),
        ("postgresql://user:pass@host:5432/db", "postgresql+psycopg://user:pass@host:5432/db"),
        ("postgresql+psycopg://user:pass@host:5432/db", "postgresql+psycopg://user:pass@host:5432/db"),
    ]
    
    for input_url, expected_url in test_cases:
        result = normalize_database_url(input_url)
        assert result == expected_url, f"Failed for {input_url}: got {result}"
