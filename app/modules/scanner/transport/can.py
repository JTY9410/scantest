"""CAN/ELM327 전송 어댑터.

기존 BLE/Serial/WiFi 연결 방식을 위한 어댑터입니다.
실제 하드웨어 연결은 클라이언트(브라우저/앱)에서 처리하고,
서버는 결과만 받아서 처리하는 구조이므로 이 어댑터는 주로 검증 용도입니다.
"""

from typing import Any

from app.modules.scanner.transport.base import TransportAdapter, TransportError, TransportResult


class CanAdapter(TransportAdapter):
    """CAN/ELM327 어댑터.

    실제로는 클라이언트가 BLE/Serial로 직접 연결하므로,
    서버 측에서는 결과만 검증하는 역할입니다.
    """

    def __init__(self):
        self._connected = False
        self._protocol_info: dict[str, Any] = {}

    def connect(self, config: dict[str, Any]) -> None:
        """CAN 연결은 클라이언트에서 처리됩니다.

        서버에서는 설정만 저장합니다.
        """
        # 클라이언트 연결 방식 검증
        method = config.get("method")
        if method not in ("ble", "serial", "wifi", "lte"):
            raise TransportError(f"지원하지 않는 CAN 연결 방식: {method}")

        self._connected = True
        self._protocol_info = {
            "name": "CAN/ELM327",
            "method": method,
            "bus": config.get("bus", "can11"),
        }

    def disconnect(self) -> None:
        """연결 종료."""
        self._connected = False
        self._protocol_info = {}

    def send_command(
        self, command: str, header: str | None = None, timeout_ms: int = 2000
    ) -> TransportResult:
        """CAN 명령 전송.

        실제로는 클라이언트가 보내므로 서버에서는 사용하지 않습니다.
        """
        if not self._connected:
            raise TransportError("연결되지 않았습니다.")

        # 서버에서 직접 명령을 보낼 수 없음
        raise TransportError(
            "CAN 연결은 클라이언트(브라우저/앱)에서만 사용할 수 있습니다. "
            "서버에서 직접 차량에 명령을 보내려면 DoIP 또는 J2534를 사용하세요."
        )

    def is_connected(self) -> bool:
        """연결 상태 반환."""
        return self._connected

    def get_protocol_info(self) -> dict[str, Any]:
        """프로토콜 정보 반환."""
        return dict(self._protocol_info)

    def test_connection(self) -> dict[str, Any]:
        """CAN 연결 테스트.

        클라이언트 연결이므로 설정만 확인합니다.
        """
        if not self._connected:
            return {
                "success": False,
                "message": "연결되지 않았습니다.",
                "details": {},
            }

        return {
            "success": True,
            "message": "CAN 연결 설정 확인됨",
            "details": {"protocol": self._protocol_info},
        }
