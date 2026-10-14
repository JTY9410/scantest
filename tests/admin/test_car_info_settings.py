import httpx
from sqlalchemy import select

from app.core.audit import Activity
from app.core.crypto import decrypt
from app.extensions import db
from app.modules.scans import car_info
from app.modules.scans.models import CarInfoSetting
from tests.conftest import csrf_token

SECRET = "car-info-secret-AB12"


def _setting(app) -> CarInfoSetting:
    with app.app_context():
        setting = db.session.scalar(select(CarInfoSetting))
        db.session.expunge(setting)
        return setting


def test_key_is_encrypted_and_used_before_env(app, admin_client, monkeypatch):
    token = csrf_token(admin_client, "/admin/car-info")
    admin_client.post("/admin/car-info/key", data={"csrf_token": token, "key-api_key": SECRET})

    setting = _setting(app)
    assert SECRET not in setting.key_enc and setting.key_last4 == "AB12"
    with app.app_context():
        assert decrypt(setting.key_enc) == SECRET
        logged = " ".join(str(a.changes) for a in db.session.scalars(select(Activity)).all())
    assert SECRET not in logged
    html = admin_client.get("/admin/car-info").get_data(as_text=True)
    assert SECRET not in html and "AB12" in html

    seen = []

    def fake(url, data, timeout):
        seen.append((url, data["authkey"]))
        return httpx.Response(200, json={"status": "fail", "msg": "인증된 키가 아닙니다."})

    monkeypatch.setattr(car_info.httpx, "post", fake)
    admin_client.post("/admin/car-info/test", data={"csrf_token": token, "test-car_no": "12가3456"})

    assert seen == [("https://diag.wecarmobility.co.kr/api/get_car_info", SECRET)]
    assert "인증키가 올바르지 않습니다" in _setting(app).last_test_message


def test_url_must_be_https_and_revoke_clears_key(app, admin_client):
    token = csrf_token(admin_client, "/admin/car-info")
    admin_client.post("/admin/car-info", data={"csrf_token": token, "url-url": "http://x.test/api"})
    assert _setting_or_none(app) is None

    admin_client.post("/admin/car-info", data={"csrf_token": token, "url-url": "https://x.test/api"})
    assert _setting(app).url == "https://x.test/api"

    admin_client.post("/admin/car-info/key", data={"csrf_token": token, "key-api_key": SECRET})
    admin_client.post("/admin/car-info/revoke", data={"csrf_token": token})
    setting = _setting(app)
    assert setting.key_enc is None and setting.key_last4 is None


def _setting_or_none(app):
    with app.app_context():
        return db.session.scalar(select(CarInfoSetting.id))
