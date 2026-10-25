"""다중 전송 방식 진단의 전체 흐름 통합 테스트.

mock DoIP 게이트웨이 및 mock J2534 브리지를 실행하여
run_scan_with_transport() → 스캔 → 해석 → 리포트 저장까지 완전한 흐름 검증.
"""

import json
import threading
import time
from typing import Any

import pytest
from flask import Flask

from app import db
from app.modules.accounts.models import User
from app.modules.scans.models import Scan
from app.modules.scanner.service import run_scan_with_transport


def _run_mock_doip_server():
    """mock DoIP 게이트웨이 실행."""
    from bridge.mock_doip_gateway import create_app

    app = create_app()
    app.run(host="127.0.0.1", port=13401, threaded=True, use_reloader=False)


def _run_mock_j2534_server():
    """mock J2534 브리지 실행."""
    import uvicorn
    from bridge.mock_server import app as mock_app

    uvicorn.run(
        mock_app,
        host="127.0.0.1",
        port=15001,
        log_level="error",
        access_log=False,
    )


@pytest.fixture
def mock_doip_gateway():
    """백그라운드에서 mock DoIP 게이트웨이 시작."""
    thread = threading.Thread(target=_run_mock_doip_server, daemon=True)
    thread.start()
    time.sleep(1.0)  # 서버 시작 대기
    yield
    # daemon=True이므로 자동 종료됨


@pytest.fixture
def mock_j2534_bridge():
    """백그라운드에서 mock J2534 브리지 시작."""
    thread = threading.Thread(target=_run_mock_j2534_server, daemon=True)
    thread.start()
    time.sleep(1.0)  # 서버 시작 대기
    yield
    # daemon=True이므로 자동 종료됨


@pytest.mark.integration
def test_full_scan_with_doip(
    app: Flask, mock_doip_gateway: Any, admin: User
) -> None:
    """DoIP 게이트웨이로 전체 스캔 흐름 검증."""
    with app.app_context():
        # 스캔 실행
        scan_id = run_scan_with_transport(
            actor=admin,
            car_no="12가3456",
            transport="doip",
            transport_config={"host": "127.0.0.1", "port": 13401},
            source="test",
        )

        # 스캔 결과 확인
        scan = db.session.get(Scan, scan_id)
        assert scan is not None
        assert scan.car_no == "12가3456"
        assert scan.finished_at is not None

        # 데이터셋 확인
        assert len(scan.datasets) > 0
        dataset = scan.datasets[0]
        data = json.loads(dataset.data)
        assert "obd" in data or "dtc" in data


@pytest.mark.integration
def test_full_scan_with_j2534(
    app: Flask, mock_j2534_bridge: Any, admin: User
) -> None:
    """J2534 브리지로 전체 스캔 흐름 검증."""
    with app.app_context():
        # 스캔 실행
        scan_id = run_scan_with_transport(
            actor=admin,
            car_no="12가3456",
            transport="j2534_can",
            transport_config={"bridge_url": "http://127.0.0.1:15001"},
            source="test",
        )

        # 스캔 결과 확인
        scan = db.session.get(Scan, scan_id)
        assert scan is not None
        assert scan.car_no == "12가3456"
        assert scan.finished_at is not None

        # 데이터셋 확인
        assert len(scan.datasets) > 0


@pytest.mark.integration
def test_blocked_services_in_scan(app: Flask, admin: User) -> None:
    """스캔 중 차단된 서비스가 전송되지 않음을 검증."""
    with app.app_context():
        from app.modules.scanner.plan import get_commands

        commands = get_commands()
        for cmd in commands:
            # 차단 서비스 목록: 10, 27, 2E, 31, 04, 14
            assert not cmd.startswith("10")
            assert not cmd.startswith("27")
            assert not cmd.startswith("2E")
            assert not cmd.startswith("31")
            assert not cmd.startswith("04")
            assert not cmd.startswith("14")
