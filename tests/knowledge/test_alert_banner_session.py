"""관리자 화면 배너의 대기 알림 수 조회가 요청 세션(트랜잭션)을 쓰지 않는다.

예전에는 배너 조회(context processor)가 요청 세션에서 읽기 트랜잭션을 열었고, 앱 컨텍스트가
남아 있는 동안 'idle in transaction'으로 남아 테스트 정리 TRUNCATE가 무기한 멈췄다.
"""

from flask import render_template_string
from flask_login import login_user
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.extensions import db
from app.modules.accounts.models import User


def test_banner_count_does_not_use_request_session(app, make_user):
    admin_id = make_user("wecar", type="admin")
    seen: list[str] = []

    def record(state):
        seen.append(str(state.statement))

    event.listen(Session, "do_orm_execute", record)
    try:
        with app.test_request_context("/admin/"):
            user = db.session.get(User, admin_id)
            assert user.is_admin
            login_user(user)
            seen.clear()

            assert render_template_string("{{ command_alert_count() }}") == "0"
    finally:
        event.remove(Session, "do_orm_execute", record)

    assert not any("command_deletion_alerts" in statement for statement in seen)


def test_banner_count_is_zero_for_anonymous(app):
    with app.test_request_context("/admin/"):
        assert render_template_string("{{ command_alert_count() }}") == "0"
