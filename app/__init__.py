import json
import logging
import mimetypes
import os

from dotenv import load_dotenv
from flask import Flask, render_template, request, session
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import CONFIGS
from app.core.csrf_origin import CsrfOriginReferrer
from app.extensions import csrf, db, limiter, login_manager, migrate

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; font-src 'self'; manifest-src 'self'; worker-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)
mimetypes.add_type("application/manifest+json", ".webmanifest")
VERSIONED_MAX_AGE = 365 * 24 * 3600


class WecarFlask(Flask):
    def get_send_file_max_age(self, filename: str | None) -> int | None:
        # ?v=는 내용 해시라서 파일이 바뀌면 주소도 바뀐다
        if request.args.get("v"):
            return VERSIONED_MAX_AGE
        return super().get_send_file_max_age(filename)


def create_app(config_name: str | None = None) -> Flask:
    load_dotenv()
    config_name = config_name or os.environ.get("APP_ENV", "development")
    app = WecarFlask(__name__)
    app.config.from_object(CONFIGS[config_name])
    _check_required_settings(app)

    app.json.sort_keys = False
    # ProxyFix로 호스트·스킴을 맞춘 뒤, Origin→Referer 보정(Flask-WTF HTTPS CSRF).
    app.wsgi_app = ProxyFix(
        CsrfOriginReferrer(app.wsgi_app),
        x_for=app.config["PROXY_FIX_HOPS"],
        x_proto=app.config["PROXY_FIX_HOPS"],
        x_host=app.config["PROXY_FIX_HOPS"],
    )
    logging.basicConfig(level=logging.INFO)

    db.init_app(app)
    migrate.init_app(app, db, directory=os.path.join(os.path.dirname(app.root_path), "migrations"))
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)

    _import_models()
    _register_blueprints(app)
    _register_security(app)
    _register_errors(app)
    _register_template_helpers(app)

    from app.cli import register_cli
    register_cli(app)
    
    # Register knowledge base CLI
    from app.modules.knowledge import cli as knowledge_cli
    knowledge_cli.init_app(app)
    
    return app


def _check_required_settings(app: Flask) -> None:
    if app.config.get("TESTING"):
        return  # Skip in tests only
    missing = [k for k in app.config["REQUIRED_SETTINGS"] if not app.config.get(k)]
    if missing:
        raise RuntimeError(f"필수 환경변수가 없습니다: {', '.join(missing)}")


def _import_models() -> None:
    from app.core import audit  # noqa: F401
    from app.modules.accounts import models as accounts  # noqa: F401
    from app.modules.admin import models as admin  # noqa: F401
    from app.modules.canlab import models as canlab  # noqa: F401
    from app.modules.knowledge import models as knowledge  # noqa: F401
    from app.modules.obd import models as obd  # noqa: F401
    from app.modules.reports import models as reports  # noqa: F401
    from app.modules.scans import models as scans  # noqa: F401


def _register_blueprints(app: Flask) -> None:
    from app.modules.admin.routes import bp as admin_bp
    from app.modules.api import bp as api_bp
    from app.modules.auth.routes import bp as auth_bp
    from app.modules.canlab.routes import bp as canlab_bp
    from app.modules.catalog.routes import bp as catalog_bp
    from app.modules.knowledge.routes import bp as knowledge_bp
    from app.modules.members.routes import bp as members_bp
    from app.modules.monitoring.routes import bp as monitoring_bp
    from app.modules.obd.routes import bp as obd_bp
    from app.modules.scanner.routes import bp as scanner_bp
    from app.modules.site.routes import bp as public_bp

    csrf.exempt(api_bp)
    for blueprint in (public_bp, api_bp, auth_bp, admin_bp, members_bp, catalog_bp, monitoring_bp,
                      obd_bp, canlab_bp, scanner_bp, knowledge_bp):
        app.register_blueprint(blueprint)


def _register_security(app: Flask) -> None:
    @app.after_request
    def security_headers(response):
        headers = response.headers
        headers.setdefault("Content-Security-Policy", CSP)
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        # HTTP(로컬 Docker) 응답에 HSTS를 붙이면 브라우저가 https://localhost 로 올려 접속이 깨진다.
        if app.config["APP_ENV"] == "production" and (
            request.is_secure or app.config.get("SESSION_COOKIE_SECURE")
        ):
            headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.path.startswith("/admin"):
            headers.setdefault("Cache-Control", "no-store")
        return response


ERROR_TITLES = {
    400: "요청을 처리할 수 없습니다",
    403: "접근 권한이 없습니다",
    404: "페이지를 찾을 수 없습니다",
    405: "허용되지 않은 요청입니다",
    409: "다른 변경과 충돌했습니다",
    429: "요청이 너무 많습니다",
    500: "일시적인 오류가 발생했습니다",
}


def _error_page(code: int, message: str | None = None):
    title = ERROR_TITLES.get(code, ERROR_TITLES[400] if code < 500 else ERROR_TITLES[500])
    return render_template("errors/error.html", code=code, title=title, message=message), code


def _register_errors(app: Flask) -> None:
    from app.core.errors import ServiceError
    from app.modules.api import handle_http_error
    from flask_wtf.csrf import CSRFError

    csrf_refresh = "보안 토큰이 만료되었습니다. 페이지를 새로고침한 뒤 다시 시도하세요."

    @app.errorhandler(ServiceError)
    def service_error(error: ServiceError):
        return _error_page(error.status, error.message)

    @app.errorhandler(CSRFError)
    def csrf_error(error: CSRFError):
        if request.path.startswith("/api"):
            return handle_http_error(error)
        return _error_page(400, csrf_refresh)

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException):
        if request.path.startswith("/api"):
            return handle_http_error(error)
        description = error.description or ""
        if error.code == 400 and ("CSRF" in description or "referrer" in description.lower()):
            return _error_page(400, csrf_refresh)
        return _error_page(error.code or 500)

    @app.errorhandler(Exception)
    def unexpected_error(error: Exception):
        app.logger.exception("처리하지 못한 오류")
        db.session.rollback()
        if request.path.startswith("/api"):
            from app.modules.api.http import respond

            return respond({"message": "처리 중 오류가 발생했습니다."}, 500)
        return _error_page(500)


def _register_template_helpers(app: Flask) -> None:
    from app.core.time import local_display

    app.jinja_env.add_extension("jinja2.ext.do")
    app.jinja_env.filters["kst"] = local_display
    app.jinja_env.filters["pretty_json"] = lambda value: json.dumps(
        value, ensure_ascii=False, indent=2, default=str
    )

    from app.core.assets import asset_version

    @app.context_processor
    def inject_globals():
        return {
            "app_version": app.config["APP_VERSION"],
            "asset_version": asset_version(app),
            "first_login": session.pop("show_install_hint", False),
        }
