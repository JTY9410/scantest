"""Test DATABASE_URL normalization for psycopg3 compatibility."""

import pytest


def test_postgres_scheme_normalized_to_psycopg(monkeypatch):
    """Test that postgres:// is normalized to postgresql+psycopg://"""
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@host:5432/db")
    
    from app.config import Config
    url = Config.database_url()
    
    assert url == "postgresql+psycopg://user:pass@host:5432/db"
    assert "postgres://" not in url
    assert "+psycopg" in url


def test_postgresql_scheme_normalized_to_psycopg(monkeypatch):
    """Test that postgresql:// is normalized to postgresql+psycopg://"""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host:5432/db")
    
    from app.config import Config
    url = Config.database_url()
    
    assert url == "postgresql+psycopg://user:pass@host:5432/db"
    assert "+psycopg" in url


def test_postgresql_psycopg_unchanged(monkeypatch):
    """Test that postgresql+psycopg:// is not double-normalized"""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@host:5432/db")
    
    from app.config import Config
    url = Config.database_url()
    
    assert url == "postgresql+psycopg://user:pass@host:5432/db"
    assert url.count("+psycopg") == 1


def test_postgres_with_query_params(monkeypatch):
    """Test normalization preserves query parameters"""
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@host:5432/db?sslmode=require")
    
    from app.config import Config
    url = Config.database_url()
    
    assert url == "postgresql+psycopg://user:pass@host:5432/db?sslmode=require"
    assert "sslmode=require" in url


def test_app_creates_with_all_url_formats(monkeypatch):
    """Test that app successfully creates with all DATABASE_URL formats"""
    from app import create_app
    
    formats = [
        "postgres://wecarscan:test@localhost:5432/test_db",
        "postgresql://wecarscan:test@localhost:5432/test_db",
        "postgresql+psycopg://wecarscan:test@localhost:5432/test_db",
    ]
    
    for url_format in formats:
        monkeypatch.setenv("DATABASE_URL", url_format)
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-key")
        monkeypatch.setenv("ENCRYPTION_KEY", "4PjmU8z4M3K5L6N7P8Q9R0S1T2U3V4W5X6Y7Z8A9B0C=")
        
        app = create_app("testing")
        assert app is not None
        
        # Verify the normalized URL uses psycopg
        with app.app_context():
            from flask import current_app
            db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
            assert "+psycopg" in db_uri, f"URL not normalized: {db_uri}"
