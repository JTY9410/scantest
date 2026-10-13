import os
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from cryptography.fernet import Fernet
from sqlalchemy.pool import NullPool


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


def database_url() -> str | None:
    """DATABASE_URL이 없으면 Vercel Supabase 연동이 넣어 주는 POSTGRES_URL을 쓴다.
    psycopg가 거부하는 supa 쿼리 값은 지우고 드라이버를 psycopg로 지정한다."""
    url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not url or not url.startswith("postgres://"):
        return url
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k != "supa"])
    return urlunsplit(parts._replace(scheme="postgresql+psycopg", query=query))


def engine_options() -> dict:
    """DATABASE_POOL=none: 서버리스(Vercel) + Supabase 트랜잭션 풀러용.
    함수 인스턴스가 연결을 붙잡지 않고, 풀러가 지원하지 않는 prepared statement를 끈다."""
    if os.environ.get("DATABASE_POOL") == "none":
        return {"poolclass": NullPool, "connect_args": {"prepare_threshold": None}}
    return {"pool_pre_ping": True}


class Config:
    APP_ENV = "development"
    APP_VERSION = os.environ.get("APP_VERSION", "2.0.0")

    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = database_url()
    SQLALCHEMY_ENGINE_OPTIONS = engine_options()

    JWT_SECRET = os.environ.get("JWT_SECRET")
    JWT_TTL_MINUTES = _int("JWT_TTL", 60)
    JWT_REFRESH_TTL_MINUTES = _int("JWT_REFRESH_TTL", 20160)

    # Fernet 키. AI 연결 키와 관리자 OTP 비밀값 암호화에 쓰며 DB와 분리해 보관한다.
    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")

    CAR_INFO_API_URL = os.environ.get("CAR_INFO_API_URL")
    CAR_INFO_API_KEY = os.environ.get("CAR_INFO_API_KEY")
    CAR_INFO_TIMEOUT_SECONDS = 10

    # 설정하면 SMS를 보내지 않고 이 값을 인증번호로 쓴다. 운영에서는 비워 둔다.
    SMS_DEV_CODE = os.environ.get("SMS_DEV_CODE") or None
    SMS_EXPIRE_MINUTES = 10

    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True
    ADMIN_LOGIN_RATE_LIMIT = os.environ.get("ADMIN_LOGIN_RATE_LIMIT", "5 per minute")
    API_LOGIN_RATE_LIMIT = os.environ.get("API_LOGIN_RATE_LIMIT", "20 per minute")

    SESSION_COOKIE_NAME = "wecarscan_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", True)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    AI_TEST_TIMEOUT_SECONDS = 10
    PAGE_SIZE_DEFAULT = 15
    PAGE_SIZE_MAX = 100
    ADMIN_PAGE_SIZE = 20

    # 프록시 뒤에서 X-Forwarded-* 를 신뢰할 단계 수
    PROXY_FIX_HOPS = _int("PROXY_FIX_HOPS", 1)

    REQUIRED_SETTINGS = ("SECRET_KEY", "SQLALCHEMY_DATABASE_URI", "JWT_SECRET")


class DevelopmentConfig(Config):
    APP_ENV = "development"
    DEBUG = True
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE


class TestingConfig(Config):
    APP_ENV = "testing"
    TESTING = True
    SECRET_KEY = "test-secret-key"
    JWT_SECRET = "test-jwt-secret-with-enough-length-for-hs256"
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL")
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    RATELIMIT_STORAGE_URI = "memory://"
    SMS_DEV_CODE = "1111"
    CAR_INFO_API_URL = "https://car-info.test/api/get_car_info"
    CAR_INFO_API_KEY = "test-car-info-key"


class ProductionConfig(Config):
    APP_ENV = "production"
    DEBUG = False
    PREFERRED_URL_SCHEME = "https"


CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
