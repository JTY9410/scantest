from sqlalchemy import select

from app.core.audit import Activity
from app.extensions import db
from app.modules.accounts.models import User
from tests.conftest import csrf_token


def _edit_form(client, user_id: int, **overrides) -> dict:
    token = csrf_token(client, f"/admin/members/{user_id}/edit")
    with client.application.app_context():
        user = db.session.get(User, user_id)
        data = {
            "csrf_token": token,
            "name": user.name,
            "type": user.type,
            "company_id": user.company_id or 0,
            "mobile": user.mobile or "",
            "email": user.email or "",
            "biz_no": user.biz_no or "",
            "version": user.version,
        }
    data.update(overrides)
    return data


def test_member_list_search_and_filters(admin_client, make_user, make_company):
    company_id = make_company("ACME", "에이씨엠이")
    make_user("kim01", name="김테스터", mobile="01012341234", company_id=company_id)
    make_user("lee02", name="이소유", type="owner")

    by_name = admin_client.get("/admin/members/?q=김테스").get_data(as_text=True)
    assert "kim01" in by_name and "lee02" not in by_name

    by_phone = admin_client.get("/admin/members/?q=1234-1234").get_data(as_text=True)
    assert "kim01" in by_phone

    owners = admin_client.get("/admin/members/?type=owner").get_data(as_text=True)
    assert "lee02" in owners and "kim01" not in owners

    by_company = admin_client.get(f"/admin/members/?company_id={company_id}").get_data(as_text=True)
    assert "kim01" in by_company and "lee02" not in by_company


def test_member_detail_and_missing_member(admin_client, make_user):
    user_id = make_user("kim01", name="김테스터", mobile="01012341234")

    page = admin_client.get(f"/admin/members/{user_id}").get_data(as_text=True)
    assert "김테스터" in page and "010-1234-1234" in page

    assert admin_client.get("/admin/members/9999").status_code == 404


def test_member_edit_saves_and_audits(app, admin_client, make_user, make_company):
    user_id = make_user("kim01", name="김테스터")
    company_id = make_company("ACME")

    response = admin_client.post(
        f"/admin/members/{user_id}/edit",
        data=_edit_form(admin_client, user_id, name="김수정", type="owner",
                        company_id=company_id, mobile="010-9999-8888", biz_no="123-45-67890"),
    )

    assert response.status_code == 302
    with app.app_context():
        user = db.session.get(User, user_id)
        assert (user.name, user.type, user.company_id) == ("김수정", "owner", company_id)
        assert (user.mobile, user.biz_no, user.version) == ("01099998888", "1234567890", 2)
        activity = db.session.scalar(select(Activity).where(Activity.relation_type == "회원 정보 수정"))
        assert activity.relation_id == user_id
        assert activity.changes["name"] == {"before": "김테스터", "after": "김수정"}


def test_member_edit_detects_concurrent_change(app, admin_client, make_user):
    user_id = make_user("kim01", name="김테스터")
    stale = _edit_form(admin_client, user_id, name="나중 저장")

    with app.app_context():
        user = db.session.get(User, user_id)
        user.name = "먼저 저장"
        db.session.commit()

    response = admin_client.post(f"/admin/members/{user_id}/edit", data=stale)

    assert response.status_code == 200
    assert "다른 관리자가 먼저" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(User, user_id).name == "먼저 저장"


def test_member_edit_rejects_duplicate_email(admin_client, make_user):
    make_user("a1", email="taken@example.com")
    user_id = make_user("b2")

    response = admin_client.post(
        f"/admin/members/{user_id}/edit", data=_edit_form(admin_client, user_id, email="taken@example.com")
    )

    assert "이미 다른 회원이 사용 중인 이메일입니다." in response.get_data(as_text=True)


def test_admin_cannot_demote_self(admin_client):
    response = admin_client.post("/admin/members/1/edit", data=_edit_form(admin_client, 1, type="tester"))

    assert "본인의 관리자 유형은 바꿀 수 없습니다." in response.get_data(as_text=True)
