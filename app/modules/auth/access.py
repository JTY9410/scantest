from collections.abc import Callable
from functools import wraps

from flask import abort
from flask_login import current_user, login_required

from app.extensions import db, login_manager
from app.modules.accounts.models import User, UserType

login_manager.login_view = "auth.login"
login_manager.login_message = "로그인이 필요합니다."
login_manager.login_message_category = "info"
login_manager.session_protection = "basic"


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    try:
        user = db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
    if user is None or user.deleted_at is not None or user.type != UserType.ADMIN:
        return None
    return user


def admin_required(view: Callable) -> Callable:
    """로그인한 관리자만 접근한다. 권한 확인은 서버에서 매 요청마다 한다."""

    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapper
