import httpx
from sqlalchemy import select

from app.extensions import db
from app.modules.api.casing import camelize
from app.modules.scans import car_info
from app.modules.scans.models import CarInfoCache
from tests.conftest import api_login

DTO = {
    "diag_info_api": "autoup", "diag_car_id": "KPBXH3AP1GP000000", "diag_company": "KG 모빌리티",
    "diag_model": "티볼리", "diag_submodel": "티볼리 (X100. 15.1~17년)", "diag_grade": "5인승(디젤 1.6) 2WD",
    "diag_year": 2016, "diag_fuel": "경유", "diag_displacement": 1597, "diag_capacity": "",
    "diag_payload": "", "diag_new_price": "", "diag_mission": "자동", "diag_distance": 0,
}


def _fake_post(monkeypatch, body):
    calls = []

    def fake(url, data, timeout):
        calls.append({"url": url, "data": data, "timeout": timeout})
        return httpx.Response(200, json=body)

    monkeypatch.setattr(car_info.httpx, "post", fake)
    return calls


def test_car_info_returns_original_dto_and_reuses_cache(app, client, make_user, monkeypatch):
    calls = _fake_post(monkeypatch, {"status": "ok", "msg": "정상 처리되었습니다.", "dto": DTO})
    make_user("tester1")
    headers = api_login(client, "tester1")

    first = client.post("/api/scans/getCarInfo", headers=headers, json={"car_no": "12가 3456"})
    second = client.post("/api/scans/getCarInfo", headers=headers, json={"car_no": "12가3456"})

    assert first.status_code == 200 and first.get_json() == {"data": camelize(DTO)}
    assert first.get_json()["data"]["diagCapacity"] == ""
    assert second.get_json() == {"data": camelize(DTO)}
    assert len(calls) == 1
    assert calls[0]["data"] == {"authkey": "test-car-info-key", "car_no": "12가3456"}
    assert calls[0]["timeout"] == 15
    with app.app_context():
        assert db.session.scalar(select(CarInfoCache.car_no)) == "12가3456"


def test_car_info_failure_keeps_laravel_format(client, make_user, monkeypatch):
    body = {"status": "fail", "msg": "일제한 초과"}
    _fake_post(monkeypatch, body)
    make_user("tester1")
    headers = api_login(client, "tester1")

    response = client.post("/api/scans/getCarInfo", headers=headers, json={"car_no": "12가3456"})

    assert response.status_code == 400
    assert response.get_json() == {"message": "일제한 초과", "response": body}

    missing = client.post("/api/scans/getCarInfo", headers=headers, json={})
    assert missing.status_code == 400 and missing.get_json()["message"] == "차량번호를 입력해주세요."


def test_car_info_errors_are_classified(app, admin_client, monkeypatch):
    cases = {
        "인증된 키가 아닙니다.": "key",
        "말소 차량번호 or 등록되지 않은 차량번호 또는 없는 차량": "not_found",
        "차량정보 없음": "not_found",
        "일제한 초과": "quota",
    }
    with app.test_request_context():
        from app.modules.accounts.models import User
        user = db.session.scalar(select(User))
        for message, kind in cases.items():
            _fake_post(monkeypatch, {"status": "fail", "msg": message})
            try:
                car_info.lookup(user, "12가3456")
            except car_info.CarInfoError as error:
                assert error.kind == kind and error.message == message and error.guide != message
            else:
                raise AssertionError(message)


def test_normalize_dto_turns_blank_numbers_into_none():
    result = car_info.normalize_dto(DTO)
    assert result["diag_capacity"] is None and result["diag_new_price"] is None
    assert result["diag_displacement"] == 1597 and result["diag_year"] == 2016
