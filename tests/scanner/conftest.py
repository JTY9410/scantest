"""전송 계층 테스트용 모의 서버 fixture.

- mock_doip_gateway: bridge/mock_doip_gateway.py의 실제 TCP 게이트웨이를 임시 포트로 띄운다.
- mock_j2534_bridge: bridge/mock_server.py와 같은 /api 계약을 따르는 표준 라이브러리 HTTP 브리지.
  (FastAPI·uvicorn 없이 돌도록 같은 경로·응답 형식을 구현한다.)
두 fixture 모두 받은 명령을 기록하고, 테스트가 끝나면 서버와 스레드를 확실히 종료한다.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bridge.mock_doip_gateway import MockDoIPGateway

# bridge/mock_server.py의 MOCK_RESPONSES와 같은 값 (그 모듈은 FastAPI가 있어야 불러올 수 있다)
J2534_RESPONSES = {
    "0100": "41 00 BE 1F B8 13",
    "0101": "41 01 00 07 65 04",
    "03": "43 01 03 04 5B C2",
    "22F190": "62 F1 90 57 44 43 5A 47 38 41 48 37 32 33 34 35 36 37 38",
}


@pytest.fixture
def mock_doip_gateway():
    gateway = MockDoIPGateway(host="127.0.0.1", port=0)
    received: list[bytes] = []
    original = gateway.responses

    class _Recorder(dict):
        def get(self, key, default=None):
            received.append(bytes(key))
            return original.get(key, default)

    gateway.responses = _Recorder(original)
    gateway.received = received
    gateway.start()
    try:
        yield gateway
    finally:
        gateway.stop()


class _J2534State:
    def __init__(self):
        self.devices: set[int] = set()
        self.channels: dict[int, int] = {}
        self.commands: list[str] = []
        self.counter = 0


def _j2534_handler(state: _J2534State):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return None

        def _send(self, status: int, body: dict):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/api/status":
                return self._send(200, {"ready": True, "platform": "mock"})
            if self.path == "/api/devices":
                return self._send(200, {"devices": [{"name": "모의 J2534 장비"}]})
            return self._send(404, {"detail": "not found"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/api/device/open":
                state.counter += 1
                state.devices.add(state.counter)
                return self._send(200, {"device_id": state.counter})
            if self.path == "/api/device/close":
                if body.get("device_id") not in state.devices:
                    return self._send(404, {"detail": "장비 없음"})
                state.devices.discard(body["device_id"])
                return self._send(200, {"success": True})
            if self.path == "/api/channel/connect":
                if body.get("device_id") not in state.devices:
                    return self._send(404, {"detail": "장비 없음"})
                state.counter += 1
                state.channels[state.counter] = body.get("protocol")
                return self._send(200, {"channel_id": state.counter})
            if self.path == "/api/channel/disconnect":
                if state.channels.pop(body.get("channel_id"), None) is None:
                    return self._send(404, {"detail": "채널 없음"})
                return self._send(200, {"success": True})
            if self.path == "/api/message/send":
                if body.get("channel_id") not in state.channels:
                    return self._send(404, {"detail": "채널 없음"})
                command = str(body.get("data") or "").replace(" ", "").upper()
                state.commands.append(command)
                reply = J2534_RESPONSES.get(command)
                replies = [{"source": "7E8", "data": reply.replace(" ", "")}] if reply else []
                return self._send(200, {"replies": replies})
            return self._send(404, {"detail": "not found"})

    return Handler


@pytest.fixture
def mock_j2534_bridge():
    state = _J2534State()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _j2534_handler(state))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


@pytest.fixture
def no_car_lookup(monkeypatch):
    """외부 차량정보 API를 부르지 않도록 조회 실패(미설정)로 고정한다."""
    from app.modules.scans import car_info

    def _lookup(_user, car_no, *, refresh=False):
        if not car_info.normalize_car_no(car_no):
            raise car_info.CarInfoError(car_info.GUIDES["missing"], 400, "missing")
        raise car_info.CarInfoError("차량정보 조회 설정이 되어 있지 않습니다.", 503, "unconfigured")

    monkeypatch.setattr(car_info, "lookup", _lookup)
