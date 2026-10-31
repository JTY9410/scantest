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
    """DATABASE_URL만 사용한다. postgres:// 스킴이면 psycopg 드라이버로 바꾸고,
    psycopg가 거부하는 supa 쿼리 파라미터는 제거한다."""
    url = os.environ.get("DATABASE_URL")
    if not url or not url.startswith("postgres://"):
        return url
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k != "supa"])
    return urlunsplit(parts._replace(scheme="postgresql+psycopg", query=query))


def engine_options() -> dict:
    """DATABASE_POOL=none: 풀 없이 연결(레거시 서버리스용). Mac Compose 운영은 기본 pool_pre_ping."""
    if os.environ.get("DATABASE_POOL") == "none":
        return {"poolclass": NullPool, "connect_args": {"prepare_threshold": None}}
    return {"pool_pre_ping": True}


def proxy_fix_hops() -> int:
    """nginx 등 프록시 뒤에서 X-Forwarded-* 를 신뢰할 홉 수.
    PROXY_FIX_HOPS가 있으면 그걸 쓰고, 없으면 TRUST_PROXY(0/1) 별칭을 따른다. 기본 1."""
    raw_hops = os.environ.get("PROXY_FIX_HOPS")
    if raw_hops is not None and str(raw_hops).strip() != "":
        return int(raw_hops)
    trust = (os.environ.get("TRUST_PROXY") or "1").strip().lower()
    if trust in {"0", "false", "no", "off"}:
        return 0
    if trust in {"1", "true", "yes", "on"}:
        return 1
    return int(trust)


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

    # 관리자 화면(설정 > 차량정보 조회)에 키를 등록하면 그 값을 먼저 쓴다.
    CAR_INFO_API_URL = os.environ.get("CAR_INFO_API_URL")
    CAR_INFO_API_KEY = os.environ.get("CAR_INFO_API_KEY")
    CAR_INFO_TIMEOUT_SECONDS = 15
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL") or None

    # 설정하면 SMS를 보내지 않고 이 값을 인증번호로 쓴다. 운영에서는 비워 둔다.
    SMS_DEV_CODE = os.environ.get("SMS_DEV_CODE") or None
    SMS_EXPIRE_MINUTES = 10

    # 실험 상태의 명령어/수식 사용 허용 (기본값: False, 운영에서는 끈다)
    SCANNER_ALLOW_EXPERIMENTAL = _bool("SCANNER_ALLOW_EXPERIMENTAL", False)

    # 검증 명령 삭제 여부 알림(docs/command-alerts.md). 실제 스캔 응답이 아래 기준을 넘으면
    # 관리자에게 "삭제/유지"를 묻는 알림을 만든다. 자동 삭제는 하지 않는다.
    #  - 연속 실패 COMMAND_ALERT_CONSECUTIVE 회 이상, 또는
    #  - 시도 COMMAND_ALERT_MIN_ATTEMPTS 회 이상이면서 실패율 COMMAND_ALERT_FAILURE_RATE 이상
    COMMAND_ALERT_CONSECUTIVE = int(os.environ.get("COMMAND_ALERT_CONSECUTIVE", "5"))
    COMMAND_ALERT_MIN_ATTEMPTS = int(os.environ.get("COMMAND_ALERT_MIN_ATTEMPTS", "20"))
    COMMAND_ALERT_FAILURE_RATE = float(os.environ.get("COMMAND_ALERT_FAILURE_RATE", "0.8"))

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
    # 결과지 이미지 판독은 오래 걸린다. Vercel 함수 제한 시간(60초)보다 짧게 둔다.
    AI_REQUEST_TIMEOUT_SECONDS = _int("AI_REQUEST_TIMEOUT_SECONDS", 50)
    # Vercel 요청 본문 한도가 4.5MB라서 그보다 작게 둔다.
    CANLAB_MAX_UPLOAD_BYTES = _int("CANLAB_MAX_UPLOAD_BYTES", 4 * 1024 * 1024)
    PAGE_SIZE_DEFAULT = 15
    PAGE_SIZE_MAX = 100
    ADMIN_PAGE_SIZE = 20

    # 프록시 뒤에서 X-Forwarded-* 를 신뢰할 단계 수 (TRUST_PROXY=0/1 별칭 지원)
    PROXY_FIX_HOPS = proxy_fix_hops()

    REQUIRED_SETTINGS = ("SECRET_KEY", "SQLALCHEMY_DATABASE_URI", "JWT_SECRET")


class DevelopmentConfig(Config):
    # 로컬 HTTP. HTTPS 운영의 Referer 완화는 ProductionConfig.WTF_CSRF_SSL_STRICT 만 쓴다.
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
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL") or "sqlite:///:memory:"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    RATELIMIT_STORAGE_URI = "memory://"
    SMS_DEV_CODE = "1111"
    CAR_INFO_API_URL = "https://car-info.test/api/get_car_info"
    CAR_INFO_API_KEY = "test-car-info-key"
    REQUIRED_SETTINGS = []  # Don't check required settings in tests
    # Override to ensure False in tests unless explicitly set
    SCANNER_ALLOW_EXPERIMENTAL = False


class ProductionConfig(Config):
    APP_ENV = "production"
    DEBUG = False
    # 로컬 Docker(HTTP)는 compose 에서 PREFERRED_URL_SCHEME=http 로 덮어쓴다.
    PREFERRED_URL_SCHEME = os.environ.get("PREFERRED_URL_SCHEME", "https")
    # Vercel은 HTTPS·Secure 쿠키만 쓴다. Referer를 막는 브라우저·웹뷰에서
    # Flask-WTF SSL_STRICT가 로그인 POST를 400으로 깨지 않게 토큰 검사만 한다.
    WTF_CSRF_SSL_STRICT = False


CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
