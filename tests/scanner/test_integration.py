"""다중 전송 방식 진단의 전체 흐름 통합 테스트 (83f7e78에서 삭제된 테스트 복구).

모의 DoIP 게이트웨이와 모의 J2534 브리지를 띄워
run_scan_with_transport() → 스캔 → 해석 → 저장 → 결과 화면까지 검증한다.
(ScanReport 모델은 이 저장소에 없어 리포트 검증은 저장된 결과와 결과 화면으로 대신한다.)
"""

import pytest

from app import db
from app.modules.accounts.models import User
from app.modules.scanner import service
from app.modules.scanner.plan import _blocked, build_plan
from app.modules.scanner.service import run_scan_with_transport
from app.modules.scans.models import Scan

BLOCKED_PREFIXES = ("10", "27", "2E", "31", "04", "14")


def _admin(make_user) -> int:
    return make_user("scan-admin", type="admin")


@pytest.mark.integration
def test_full_scan_with_doip(app, make_user, mock_doip_gateway, no_car_lookup) -> None:
    admin_id = _admin(make_user)
    with app.app_context():
        scan = run_scan_with_transport(
            db.session.get(User, admin_id), car_no="12가3456", transport="doip",
            transport_config={"host": "127.0.0.1", "port": mock_doip_gateway.port, "timeout": 0.5},
        )
        saved = db.session.get(Scan, scan.id)
        assert saved is not None
        assert saved.car_no == "12가3456"
        assert saved.device_type == "doip"
        assert saved.device_uid == "DoIP 127.0.0.1:%d" % mock_doip_gateway.port

        result = service.scan_result(saved)
        assert any(step["command"] == "0100" and "41 00 BE 1F B8 13" in step["raw"] for step in result["steps"])
        # 차량정보 조회 실패는 스캔을 막지 않고 기록만 남긴다
        assert "차량정보 조회 설정이 되어 있지 않습니다." in str(saved.bms_data)

    # 게이트웨이가 실제로 받은 명령에 차단 서비스가 없어야 한다
    assert mock_doip_gateway.received
    assert not any(uds.hex().upper().startswith(BLOCKED_PREFIXES) for uds in mock_doip_gateway.received)


@pytest.mark.integration
def test_full_scan_with_j2534(app, make_user, mock_j2534_bridge, no_car_lookup) -> None:
    admin_id = _admin(make_user)
    with app.app_context():
        scan = run_scan_with_transport(
            db.session.get(User, admin_id), car_no="12가3456", transport="j2534_can",
            transport_config={"bridge_url": mock_j2534_bridge.url},
        )
        saved = db.session.get(Scan, scan.id)
        assert saved is not None
        assert saved.car_no == "12가3456"
        assert saved.device_type == "j2534"
        result = service.scan_result(saved)
        assert any(step["command"] == "0100" and "41 00 BE 1F B8 13" in step["raw"] for step in result["steps"])

    assert "0100" in mock_j2534_bridge.commands
    assert not any(command.startswith(BLOCKED_PREFIXES) for command in mock_j2534_bridge.commands)
    # 스캔이 끝나면 채널과 장비를 닫는다
    assert mock_j2534_bridge.channels == {}
    assert mock_j2534_bridge.devices == set()


@pytest.mark.integration
def test_scan_result_page_renders(app, admin_client, mock_doip_gateway, no_car_lookup) -> None:
    with app.app_context():
        admin = db.session.scalar(db.select(User).where(User.tid == "wecar"))
        scan = run_scan_with_transport(
            admin, car_no="12가3456", transport="doip",
            transport_config={"host": "127.0.0.1", "port": mock_doip_gateway.port, "timeout": 0.5},
        )
        scan_id = scan.id
    response = admin_client.get(f"/admin/scan/{scan_id}")
    assert response.status_code == 200
    assert "12가3456" in response.get_data(as_text=True)


@pytest.mark.integration
def test_blocked_services_in_scan(app) -> None:
    """서버 측 전송이 쓰는 스캔 계획에는 세션·보안·쓰기·루틴·지우기 서비스가 없다."""
    with app.app_context():
        for car in (None, {"diag_company": "현대", "diag_model": "아이오닉5", "diag_fuel": "전기"}):
            commands = [step["command"].replace(" ", "").upper() for step in build_plan(car, expand=False)["steps"]]
            assert commands
            for command in commands:
                if command.startswith("AT"):
                    continue
                assert not _blocked(command), command
                assert not command.startswith(BLOCKED_PREFIXES), command
