import json
import logging
import mimetypes
import os

from dotenv import load_dotenv
from flask import Flask, render_template, request, session
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import CONFIGS
from app.extensions import csrf, db, limiter, login_manager, migrate

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; font-src 'self'; manifest-src 'self'; worker-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)
mimetypes.add_type("application/manifest+json", ".webmanifest")


def create_app(config_name: str | None = None) -> Flask:
    load_dotenv()
    config_name = config_name or os.environ.get("APP_ENV", "development")
    app = Flask(__name__)
    app.config.from_object(CONFIGS[config_name])
    _check_required_settings(app)

    app.json.sort_keys = False
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
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
    return app


def _check_required_settings(app: Flask) -> None:
    missing = [k for k in app.config["REQUIRED_SETTINGS"] if not app.config.get(k)]
    if missing:
        raise RuntimeError(f"필수 환경변수가 없습니다: {', '.join(missing)}")


def _import_models() -> None:
    from app.core import audit  # noqa: F401
    from app.modules.accounts import models as accounts  # noqa: F401
    from app.modules.admin import models as admin  # noqa: F401
    from app.modules.obd import models as obd  # noqa: F401
    from app.modules.reports import models as reports  # noqa: F401
    from app.modules.scans import models as scans  # noqa: F401


def _register_blueprints(app: Flask) -> None:
    from app.modules.admin.routes import bp as admin_bp
    from app.modules.api import bp as api_bp
    from app.modules.auth.routes import bp as auth_bp
    from app.modules.catalog.routes import bp as catalog_bp
    from app.modules.members.routes import bp as members_bp
    from app.modules.monitoring.routes import bp as monitoring_bp
    from app.modules.obd.routes import bp as obd_bp
    from app.modules.public.routes import bp as public_bp

    csrf.exempt(api_bp)
    for blueprint in (public_bp, api_bp, auth_bp, admin_bp, members_bp, catalog_bp, monitoring_bp,
                      obd_bp):
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
        if app.config["APP_ENV"] == "production":
            headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.path.startswith("/admin"):
            headers["Cache-Control"] = "no-store"
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

    @app.errorhandler(ServiceError)
    def service_error(error: ServiceError):
        return _error_page(error.status, error.message)

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException):
        if request.path.startswith("/api"):
            return handle_http_error(error)
        if error.code == 400 and "CSRF" in (error.description or ""):
            return _error_page(400, "보안 토큰이 만료되었습니다. 페이지를 새로고침한 뒤 다시 시도하세요.")
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
