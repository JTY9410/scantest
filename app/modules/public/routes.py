from pathlib import Path

from flask import Blueprint, current_app, jsonify, redirect, url_for
from sqlalchemy import text

from app.core.assets import asset_version
from app.extensions import db

bp = Blueprint("public", __name__)


@bp.get("/")
def index():
    return redirect(url_for("admin.dashboard"))


@bp.get("/up")
def health():
    db.session.execute(text("SELECT 1"))
    return jsonify({"status": "ok"})


@bp.get("/service-worker.js")
def service_worker():
    """관리자 범위(/admin/)를 제어해야 하므로 static/ 이 아닌 루트 경로에서 제공한다."""
    source = Path(current_app.static_folder, "service-worker.js").read_text(encoding="utf-8")
    body = source.replace("__ASSET_VERSION__", asset_version(current_app))
    response = current_app.response_class(body, mimetype="text/javascript")
    response.headers["Cache-Control"] = "no-cache"
    return response
