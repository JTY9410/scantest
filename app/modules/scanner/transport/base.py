"""전송 계층 기본 인터페이스.

모든 전송 어댑터가 구현해야 하는 추상 클래스와 공통 타입을 정의합니다.
"""

import ipaddress
import logging
import re
import socket
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class TransportError(Exception):
    """전송 계층 오류. ServiceError로 변환됩니다."""

    def __init__(self, message: str, status: int = 400):
        self.message = message
        self.status = status
        super().__init__(message)


_log = logging.getLogger(__name__)
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
_BLOCKED_NAMES = {"metadata", "metadata.google.internal", "metadata.goog", "instance-data", "instance-data.ec2.internal"}


def _blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    """클라우드 메타데이터(링크 로컬)·멀티캐스트·미지정·예약 주소는 막는다.

    차량 게이트웨이와 로컬 브리지는 사설망·루프백에 있으므로 허용한다."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return False
    return ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved


def check_target_host(host: str | None, port: int) -> str:
    """연결 대상 주소를 검사한다(SSRF 방지). 이름은 해석된 모든 주소를 확인한다."""
    name = (host or "").strip().rstrip(".").lower()
    if not name or not _HOST.fullmatch(name) or name in _BLOCKED_NAMES:
        raise TransportError("게이트웨이 주소를 확인하세요.")
    try:
        ips = {ipaddress.ip_address(name)}
    except ValueError:
        try:
            infos = socket.getaddrinfo(name, port, proto=socket.IPPROTO_TCP)
        except (OSError, UnicodeError):
            raise TransportError("게이트웨이 주소를 확인하세요.") from None
        ips = {ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos}
    if not ips or any(_blocked_ip(ip) for ip in ips):
        raise TransportError("게이트웨이 주소를 확인하세요.")
    return name


def check_port(port) -> int:
    if isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535):
        raise TransportError("포트 번호를 확인하세요.")
    return port


@dataclass
class TransportResult:
    """한 단계의 실행 결과."""

    command: str
    header: str | None
    reply: str | None
    error: str | None
    elapsed_ms: float


class TransportAdapter(ABC):
    """전송 계층 추상 인터페이스.

    각 연결 방식(CAN/DoIP/J2534)은 이 인터페이스를 구현합니다.
    """

    @abstractmethod
    def connect(self, config: dict[str, Any]) -> None:
        """연결을 수립합니다.

        Args:
            config: 연결 설정 (방식별로 다름)
                - CAN: {"port": "/dev/ttyUSB0", "baudrate": 115200, ...}
                - DoIP: {"host": "192.168.0.20", "port": 13400, ...}
                - J2534: {"bridge_url": "http://localhost:5000", ...}

        Raises:
            TransportError: 연결 실패 시
        """

    @abstractmethod
    def disconnect(self) -> None:
        """연결을 종료합니다."""

    @abstractmethod
    def send_command(
        self, command: str, header: str | None = None, timeout_ms: int = 2000
    ) -> TransportResult:
        """진단 명령을 전송하고 응답을 받습니다.

        Args:
            command: 진단 명령 (16진수 문자열, 예: "0100", "22F190")
            header: ECU 주소 (없으면 기본 브로드캐스트)
            timeout_ms: 타임아웃 (밀리초)

        Returns:
            TransportResult: 실행 결과

        Raises:
            TransportError: 전송 실패 시
        """

    @abstractmethod
    def is_connected(self) -> bool:
        """연결 상태를 반환합니다."""

    @abstractmethod
    def get_protocol_info(self) -> dict[str, Any]:
        """현재 프로토콜 정보를 반환합니다.

        Returns:
            {"name": "...", "bus": "can11" | "can29" | "serial", ...}
        """

    def test_connection(self) -> dict[str, Any]:
        """연결 테스트를 수행합니다.

        기본 구현은 간단한 명령을 보내고 응답을 확인합니다.
        각 어댑터는 이 메서드를 오버라이드할 수 있습니다.

        Returns:
            {"success": bool, "message": str, "details": {...}}
        """
        try:
            if not self.is_connected():
                return {
                    "success": False,
                    "message": "연결되지 않았습니다.",
                    "details": {},
                }

            # 간단한 테스트 명령 (프로토콜 조회)
            result = self.send_command("ATDPN", timeout_ms=1000)
            if result.error:
                return {
                    "success": False,
                    "message": f"테스트 명령 실패: {result.error}",
                    "details": {},
                }

            return {
                "success": True,
                "message": "연결 테스트 성공",
                "details": {"protocol": self.get_protocol_info(), "result": result},
            }

        except Exception:
            _log.exception("전송 연결 테스트 오류")
            return {"success": False, "message": "테스트 중 오류가 발생했습니다.", "details": {}}
