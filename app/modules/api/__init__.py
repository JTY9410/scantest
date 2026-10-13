from flask import Blueprint, request
from werkzeug.exceptions import HTTPException

from app.core.errors import ServiceError
from app.modules.api.http import error_response, respond

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.errorhandler(ServiceError)
def _service_error(error: ServiceError):
    return error_response(error)


@bp.after_request
def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def handle_http_error(error: HTTPException):
    """/api 아래의 404·405 등도 JSON으로 응답한다(앱 전역 핸들러에서 호출)."""
    messages = {404: "요청한 API를 찾을 수 없습니다.", 405: "허용되지 않은 요청 방식입니다."}
    message = messages.get(error.code, error.description)
    if error.code == 429:
        message = "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."
    return respond({"message": message, "path": request.path}, error.code or 500)


from app.modules.api import routes_auth, routes_resources  # noqa: E402,F401
