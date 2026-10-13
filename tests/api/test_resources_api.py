from tests.conftest import api_login

SCAN = {
    "type": "ev",
    "deviceType": "obd",
    "deviceUid": "dev-1",
    "carNo": "12가3456",
    "carVin": "KMHXX00XXXX000001",
    "carModel": "아이오닉5",
    "carBatteryCapacity": "12.5",
    "raw": {"a": 1},
}


def _create_scan(client, headers, **overrides):
    return client.post("/api/scans", headers=headers, json={**SCAN, **overrides})


def test_tester_creates_scan_for_self(client, make_user):
    tester_id = make_user("tester1")
    other_id = make_user("tester2")
    owner_id = make_user("owner1", type="owner")
    headers = api_login(client, "tester1")

    response = _create_scan(client, headers, testerId=other_id, ownerId=owner_id)

    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["testerId"] == tester_id
    assert data["ownerId"] is None
    assert data["carBatteryCapacity"] == "12.50"
    assert data["tester"]["tid"] == "tester1"
    assert data["scanCodes"] == []


def test_owner_cannot_create_scan(client, make_user):
    tester_id = make_user("tester1")
    make_user("owner1", type="owner")

    response = _create_scan(client, api_login(client, "owner1"), testerId=tester_id)

    assert response.status_code == 403
    assert response.get_json()["message"] == "오너는 생성할 수 없습니다."


def test_testers_only_see_their_own_scans(client, make_user):
    make_user("tester1")
    make_user("tester2")
    make_user("boss", type="admin")
    mine = _create_scan(client, api_login(client, "tester1"), testerId=1).get_json()["data"]["id"]
    other = _create_scan(client, api_login(client, "tester2"), testerId=2).get_json()["data"]["id"]

    headers = api_login(client, "tester1")
    listing = client.get("/api/scans", headers=headers).get_json()
    assert [s["id"] for s in listing["data"]] == [mine]
    assert client.get(f"/api/scans/{other}", headers=headers).status_code == 404
    assert client.delete(f"/api/scans/{other}", headers=headers).status_code == 404

    admin_listing = client.get("/api/scans", headers=api_login(client, "boss")).get_json()
    assert {s["id"] for s in admin_listing["data"]} == {mine, other}


def test_list_meta_search_and_page_size_cap(client, make_user):
    make_user("tester1")
    headers = api_login(client, "tester1")
    _create_scan(client, headers, testerId=1, carNo="11가1111")
    _create_scan(client, headers, testerId=1, carNo="22나2222")

    body = client.get("/api/scans?perPage=1000&search=car_no:like:22||", headers=headers).get_json()

    assert [s["carNo"] for s in body["data"]] == ["22나2222"]
    assert body["meta"] == {"currentPage": 1, "lastPage": 1, "perPage": 100, "total": 1}


def test_scan_update_and_soft_delete(client, make_user):
    make_user("tester1")
    headers = api_login(client, "tester1")
    scan_id = _create_scan(client, headers, testerId=1).get_json()["data"]["id"]

    updated = client.patch(f"/api/scans/{scan_id}", headers=headers, json={"carDistance": 1234})
    assert updated.get_json()["data"]["carDistance"] == 1234
    assert client.delete(f"/api/scans/{scan_id}", headers=headers).status_code == 200
    assert client.get(f"/api/scans/{scan_id}", headers=headers).status_code == 404


def test_applogs_are_scoped_to_the_member(client, make_user):
    make_user("tester1")
    other_id = make_user("tester2")
    make_user("boss", type="admin")
    mine = api_login(client, "tester1")

    created = client.post(
        "/api/applogs",
        headers=mine,
        json={"timestamp": "2026-10-13 09:00:00", "userId": other_id, "type": "error", "message": "앱 오류"},
    )
    assert created.status_code == 201
    assert created.get_json()["userId"] == 1

    theirs = api_login(client, "tester2")
    assert client.get("/api/applogs", headers=theirs).get_json()["total"] == 0
    assert client.get(f"/api/applogs/{created.get_json()['id']}", headers=theirs).status_code == 404

    admin = client.get("/api/applogs", headers=api_login(client, "boss")).get_json()
    assert admin["total"] == 1
    assert admin["currentPage"] == 1 and "links" in admin


def test_mismatch_reports_are_scoped_to_the_member(client, make_user):
    make_user("tester1")
    make_user("tester2")
    mine = api_login(client, "tester1")
    created = client.post(
        "/api/carMismatchReports",
        headers=mine,
        json={"carNo": "12가3456", "apiVin": "A" * 17, "scanVin": "B" * 17},
    )
    assert created.status_code == 201
    assert created.get_json()["data"]["user"]["tid"] == "tester1"

    theirs = api_login(client, "tester2")
    assert client.get("/api/carMismatchReports", headers=theirs).get_json()["data"] == []


def test_api_requires_authentication(client):
    response = client.get("/api/scans")

    assert response.status_code == 401
    assert response.get_json()["message"] == "인증이 필요합니다."
