import re
from collections.abc import Callable
from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy import text

# Load .env file for test configuration
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    load_dotenv(env_path)

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
        # Handle both SQLite and Postgres
        engine_name = db.engine.name
        if engine_name == 'postgresql':
            db.session.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            db.session.execute(text("CREATE SCHEMA public"))
            db.session.commit()
            # Run migrations for Postgres
            from flask_migrate import upgrade as flask_migrate_upgrade
            flask_migrate_upgrade()
        else:
            # SQLite: use create_all (migrations don't work well with SQLite constraints)
            db.drop_all()
            db.create_all()
            # Create migration-only tables manually for SQLite
            try:
                db.session.execute(text("SELECT 1 FROM maker_aliases LIMIT 1"))
            except Exception:
                db.session.execute(text("""
                    CREATE TABLE maker_aliases (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        standard_key VARCHAR(50) NOT NULL UNIQUE,
                        english_name VARCHAR(100) NOT NULL,
                        korean_name VARCHAR(100) NOT NULL,
                        aliases TEXT NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                db.session.execute(text("""
                    INSERT INTO maker_aliases (standard_key, english_name, korean_name, aliases) VALUES
                    ('hyundai', 'Hyundai', '현대', 'HYUNDAI,hyundai,현대,현대자동차'),
                    ('kia', 'Kia', '기아', 'KIA,kia,기아,기아자동차'),
                    ('nissan', 'Nissan', '닛산', 'NISSAN,nissan,닛산,Infiniti,INFINITI'),
                    ('tesla', 'Tesla', '테슬라', 'TESLA,tesla,테슬라')
                """))
                db.session.commit()
            
            try:
                db.session.execute(text("SELECT 1 FROM command_stats LIMIT 1"))
            except Exception:
                db.session.execute(text("""
                    CREATE TABLE command_stats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        maker VARCHAR(50) NOT NULL,
                        model VARCHAR(200),
                        ecu VARCHAR(50) NOT NULL,
                        command VARCHAR(100) NOT NULL,
                        attempts INTEGER DEFAULT 0,
                        successes INTEGER DEFAULT 0,
                        timeouts INTEGER DEFAULT 0,
                        nrcs INTEGER DEFAULT 0,
                        min_response_ms INTEGER,
                        max_response_ms INTEGER,
                        avg_response_ms REAL,
                        ucb_score REAL,
                        thompson_alpha REAL DEFAULT 1.0,
                        thompson_beta REAL DEFAULT 1.0,
                        last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(maker, model, ecu, command)
                    )
                """))
                db.session.commit()
            
            try:
                db.session.execute(text("SELECT 1 FROM learning_runs LIMIT 1"))
            except Exception:
                db.session.execute(text("""
                    CREATE TABLE learning_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_name VARCHAR(200) NOT NULL,
                        description TEXT,
                        params TEXT,
                        metrics TEXT,
                        status VARCHAR(20) DEFAULT 'candidate',
                        promoted_at DATETIME,
                        rolled_back_at DATETIME,
                        rollback_reason TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                db.session.commit()
            
            try:
                db.session.execute(text("SELECT 1 FROM battery_reference_capacity LIMIT 1"))
            except Exception:
                db.session.execute(text("""
                    CREATE TABLE battery_reference_capacity (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_file VARCHAR(100) NOT NULL,
                        sheet_name VARCHAR(100),
                        row_number INTEGER,
                        maker VARCHAR(50) NOT NULL,
                        model VARCHAR(100) NOT NULL,
                        trim VARCHAR(200),
                        generation VARCHAR(100),
                        year_from INTEGER,
                        year_to INTEGER,
                        vin_wmi VARCHAR(10),
                        vin_factory VARCHAR(50),
                        pack_id VARCHAR(50),
                        official_capacity_kwh REAL,
                        official_classification VARCHAR(50),
                        gross_capacity_kwh REAL,
                        net_capacity_kwh REAL,
                        rated_voltage_v REAL,
                        rated_capacity_ah REAL,
                        computed_capacity_kwh REAL,
                        cell_manufacturer VARCHAR(100),
                        chemistry VARCHAR(100),
                        pack_type_note VARCHAR(200),
                        verification_level VARCHAR(50),
                        domestic_sales_verified VARCHAR(100),
                        domestic_application_evidence VARCHAR(200),
                        source_url_1 TEXT,
                        source_url_2 TEXT,
                        source_id VARCHAR(100),
                        notes TEXT,
                        warnings TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                db.session.commit()
            
            try:
                db.session.execute(text("SELECT 1 FROM vin_decode_rules LIMIT 1"))
            except Exception:
                db.session.execute(text("""
                    CREATE TABLE vin_decode_rules (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        wmi_pattern VARCHAR(10) NOT NULL,
                        manufacturer VARCHAR(50) NOT NULL,
                        vds_position INTEGER,
                        vds_value_pattern VARCHAR(20),
                        powertrain VARCHAR(20) NOT NULL,
                        confidence REAL DEFAULT 0.9,
                        description TEXT,
                        source_url VARCHAR(500) NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                db.session.commit()
            
            # ML tables from migration 20261116_120000
            try:
                db.session.execute(text("SELECT 1 FROM ml_model_runs LIMIT 1"))
            except Exception:
                db.session.execute(text("""
                    CREATE TABLE ml_model_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_type VARCHAR(50) NOT NULL,
                        trigger_reason VARCHAR(200),
                        training_samples INTEGER NOT NULL,
                        validation_samples INTEGER NOT NULL,
                        test_samples INTEGER NOT NULL,
                        model_type VARCHAR(50) NOT NULL,
                        model_path VARCHAR(500),
                        metrics TEXT,
                        status VARCHAR(20) NOT NULL,
                        error_message VARCHAR(500),
                        started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        completed_at DATETIME
                    )
                """))
                db.session.commit()
            
            try:
                db.session.execute(text("SELECT 1 FROM ml_active_model LIMIT 1"))
            except Exception:
                db.session.execute(text("""
                    CREATE TABLE ml_active_model (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        model_run_id INTEGER NOT NULL,
                        activated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        activated_by VARCHAR(100),
                        model_path VARCHAR(500) NOT NULL,
                        FOREIGN KEY (model_run_id) REFERENCES ml_model_runs(id) ON DELETE CASCADE
                    )
                """))
                db.session.commit()
            
            try:
                db.session.execute(text("SELECT 1 FROM ml_consistency_scores LIMIT 1"))
            except Exception:
                db.session.execute(text("""
                    CREATE TABLE ml_consistency_scores (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        scan_id INTEGER NOT NULL UNIQUE,
                        score INTEGER NOT NULL,
                        distribution_match REAL,
                        physical_plausibility REAL,
                        issues_detected TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (scan_id) REFERENCES scans(id) ON DELETE CASCADE
                    )
                """))
                db.session.commit()
    yield app
    with app.app_context():
        engine_name = db.engine.name
        if engine_name == 'postgresql':
            db.session.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            db.session.execute(text("CREATE SCHEMA public"))
            db.session.commit()
        else:
            db.drop_all()


@pytest.fixture
def app(_app_base):
    """Function-scoped app context to avoid lock issues"""
    return _app_base


@pytest.fixture(autouse=True)
def _clean_database(app):
    """Clean database using TRUNCATE for reliable isolation.
    
    Uses TRUNCATE CASCADE which is faster than DELETE and properly handles
    foreign key constraints. Preserves alembic_version table.
    """
    yield
    
    with app.app_context():
        # Rollback any pending transactions
        db.session.rollback()
        db.session.remove()
        
        # Get all table names except alembic_version
        tables = [table.name for table in db.metadata.sorted_tables 
                  if table.name != 'alembic_version']
        
        if tables:
            # Use TRUNCATE CASCADE for PostgreSQL (faster and handles FKs)
            if "postgresql" in app.config["SQLALCHEMY_DATABASE_URI"]:
                db.session.execute(text("SET lock_timeout = '5s'"))
                # Only truncate tables that actually exist
                for table_name in tables:
                    try:
                        db.session.execute(text(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE"))
                        db.session.commit()
                    except Exception:
                        # Table doesn't exist (e.g., new models without migration)
                        db.session.rollback()
            else:
                # SQLite fallback (skip tables that don't exist)
                for table in reversed(db.metadata.sorted_tables):
                    if table.name != 'alembic_version':
                        try:
                            db.session.execute(text(f"DELETE FROM {table.name}"))
                        except Exception:
                            # Table doesn't exist in test DB (e.g., battery_reference_capacity)
                            pass
                try:
                    db.session.execute(text("DELETE FROM sqlite_sequence"))
                except Exception:
                    pass
            
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


@pytest.fixture(autouse=True)
def stub_car_info_cache():
    """Stub car_info cache to prevent external API calls in tests.
    
    By default returns None (cache miss). Individual tests can populate
    the car_info_cache table to test plate lookup behavior.
    """
    # No-op: The car_info_cache table will be empty by default in tests
    # Tests that need plate lookup should explicitly insert cache entries
    yield
