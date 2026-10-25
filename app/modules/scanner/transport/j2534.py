"""J2534 패스스루 전송 어댑터.

SAE J2534-1/-2 표준을 통해 패스스루 장비와 통신합니다.
J2534 DLL은 Windows에만 존재하므로, 로컬 브리지 프로세스를 통해 통신합니다.

구조:
    scantest 서버 (Linux/Mac) <-> HTTP/WebSocket <-> 로컬 브리지 (Windows) <-> J2534 DLL <-> 차량
"""

import json
import time
from typing import Any
from urllib.parse import urljoin

import requests

from app.modules.scanner.transport.base import TransportAdapter, TransportError, TransportResult

# J2534 프로토콜 ID
PROTOCOL_ISO15765 = 1  # CAN (ISO 15765-4)
PROTOCOL_ISO14230 = 2  # KWP2000 (ISO 14230-4)
PROTOCOL_ISO9141 = 3  # K-Line (ISO 9141-2)
PROTOCOL_J1850VPW = 4  # J1850 VPW
PROTOCOL_J1850PWM = 5  # J1850 PWM
PROTOCOL_DOIP = 16  # DoIP over J2534 (확장)

PROTOCOL_NAMES = {
    PROTOCOL_ISO15765: "ISO 15765-4 (CAN)",
    PROTOCOL_ISO14230: "ISO 14230-4 (KWP2000)",
    PROTOCOL_ISO9141: "ISO 9141-2 (K-Line)",
    PROTOCOL_J1850VPW: "SAE J1850 VPW",
    PROTOCOL_J1850PWM: "SAE J1850 PWM",
    PROTOCOL_DOIP: "DoIP over J2534",
}


class J2534Adapter(TransportAdapter):
    """J2534 패스스루 어댑터.

    로컬 브리지 서버를 통해 J2534 DLL과 통신합니다.
    브리지는 차량 옆 Windows PC에서 실행됩니다.
    """

    def __init__(self):
        self._bridge_url: str | None = None
        self._session: requests.Session | None = None
        self._device_id: int | None = None
        self._channel_id: int | None = None
        self._protocol: int = PROTOCOL_ISO15765
        self._connected = False

    def connect(self, config: dict[str, Any]) -> None:
        """로컬 브리지를 통해 J2534 장비에 연결합니다.

        Args:
            config: {
                "bridge_url": "http://localhost:5000",
                "device_name": "드류텍 J2534",  # 선택 사항
                "protocol": "CAN" | "KWP" | "K-Line",  # 기본 CAN
                "baudrate": 500000,  # 기본 500k
            }

        Raises:
            TransportError: 연결 실패 시
        """
        bridge_url = (config.get("bridge_url") or "").strip()
        if not bridge_url:
            raise TransportError("J2534 브리지 URL을 입력하세요.")

        if not bridge_url.startswith(("http://", "https://")):
            bridge_url = f"http://{bridge_url}"

        # 프로토콜 선택
        protocol_name = (config.get("protocol") or "CAN").upper()
        protocol_map = {
            "CAN": PROTOCOL_ISO15765,
            "ISO15765": PROTOCOL_ISO15765,
            "KWP": PROTOCOL_ISO14230,
            "ISO14230": PROTOCOL_ISO14230,
            "K-LINE": PROTOCOL_ISO9141,
            "ISO9141": PROTOCOL_ISO9141,
            "J1850VPW": PROTOCOL_J1850VPW,
            "J1850PWM": PROTOCOL_J1850PWM,
            "DOIP": PROTOCOL_DOIP,
        }
        self._protocol = protocol_map.get(protocol_name, PROTOCOL_ISO15765)

        try:
            self._session = requests.Session()
            self._bridge_url = bridge_url.rstrip("/")

            # 브리지 상태 확인
            status = self._api_call("GET", "/api/status")
            if not status.get("ready"):
                raise TransportError(
                    f"J2534 브리지가 준비되지 않았습니다: {status.get('error', '알 수 없는 오류')}"
                )

            # 장비 열기
            device_name = config.get("device_name")
            result = self._api_call(
                "POST",
                "/api/device/open",
                {"device_name": device_name} if device_name else {},
            )
            self._device_id = result["device_id"]

            # 채널 연결
            baudrate = config.get("baudrate", 500000)
            result = self._api_call(
                "POST",
                "/api/channel/connect",
                {
                    "device_id": self._device_id,
                    "protocol": self._protocol,
                    "flags": 0,
                    "baudrate": baudrate,
                },
            )
            self._channel_id = result["channel_id"]

            self._connected = True

        except requests.RequestException as exc:
            raise TransportError(
                f"J2534 브리지에 연결하지 못했습니다: {exc}. "
                f"브리지가 {bridge_url}에서 실행 중인지 확인하세요."
            )
        except TransportError:
            raise
        except Exception as exc:
            raise TransportError(f"J2534 연결 실패: {exc}")

    def disconnect(self) -> None:
        """연결을 종료합니다."""
        if not self._session:
            return

        try:
            # 채널 닫기
            if self._channel_id is not None:
                self._api_call(
                    "POST",
                    "/api/channel/disconnect",
                    {"channel_id": self._channel_id},
                )

            # 장비 닫기
            if self._device_id is not None:
                self._api_call(
                    "POST",
                    "/api/device/close",
                    {"device_id": self._device_id},
                )

        except Exception:
            pass
        finally:
            if self._session:
                self._session.close()
            self._session = None
            self._device_id = None
            self._channel_id = None
            self._connected = False

    def send_command(
        self, command: str, header: str | None = None, timeout_ms: int = 2000
    ) -> TransportResult:
        """진단 명령을 전송하고 응답을 받습니다."""
        if not self.is_connected():
            raise TransportError("연결되지 않았습니다.")

        start = time.time()

        try:
            # 명령 바이트 변환
            try:
                command_bytes = bytes.fromhex(command)
            except ValueError:
                raise TransportError(f"잘못된 명령 형식: {command}")

            # 헤더 설정 (CAN인 경우)
            txflags = 0
            if header and self._protocol == PROTOCOL_ISO15765:
                try:
                    can_id = int(header, 16)
                    # ISO-TP 헤더는 브리지에서 처리
                    # 여기서는 CAN ID만 전달
                except ValueError:
                    raise TransportError(f"잘못된 CAN ID: {header}")

            # 메시지 전송
            result = self._api_call(
                "POST",
                "/api/message/send",
                {
                    "channel_id": self._channel_id,
                    "data": command_bytes.hex(),
                    "header": header,
                    "timeout_ms": timeout_ms,
                },
            )

            elapsed = (time.time() - start) * 1000

            # 응답 읽기
            if result.get("replies"):
                reply_text = self._format_replies(result["replies"])
                return TransportResult(
                    command=command,
                    header=header,
                    reply=reply_text,
                    error=None,
                    elapsed_ms=elapsed,
                )
            else:
                return TransportResult(
                    command=command,
                    header=header,
                    reply="NO DATA\r\r>",
                    error="no_data",
                    elapsed_ms=elapsed,
                )

        except TransportError:
            raise
        except Exception as exc:
            elapsed = (time.time() - start) * 1000
            return TransportResult(
                command=command,
                header=header,
                reply=None,
                error=str(exc),
                elapsed_ms=elapsed,
            )

    def is_connected(self) -> bool:
        """연결 상태를 반환합니다."""
        return self._connected

    def get_protocol_info(self) -> dict[str, Any]:
        """J2534 프로토콜 정보를 반환합니다."""
        return {
            "name": f"J2534 {PROTOCOL_NAMES.get(self._protocol, '알 수 없음')}",
            "bus": self._get_bus_type(),
            "protocol": self._protocol,
            "bridge": self._bridge_url,
        }

    def list_devices(self) -> list[dict[str, Any]]:
        """사용 가능한 J2534 장비 목록을 반환합니다.

        Returns:
            [{"name": "...", "vendor": "...", "dll_path": "..."}]
        """
        if not self._session or not self._bridge_url:
            raise TransportError("브리지에 연결되지 않았습니다.")

        try:
            result = self._api_call("GET", "/api/devices")
            return result.get("devices", [])
        except Exception as exc:
            raise TransportError(f"장비 목록 조회 실패: {exc}")

    def test_connection(self) -> dict[str, Any]:
        """J2534 연결 테스트를 수행합니다."""
        try:
            if not self.is_connected():
                return {
                    "success": False,
                    "message": "연결되지 않았습니다.",
                    "details": {},
                }

            # 브리지 상태 확인
            status = self._api_call("GET", "/api/status")

            # 간단한 테스트 명령
            result = self.send_command("0100", timeout_ms=2000)

            return {
                "success": True,
                "message": "J2534 연결 테스트 성공",
                "details": {
                    "protocol": self.get_protocol_info(),
                    "bridge_status": status,
                    "test_result": result.__dict__,
                },
            }

        except Exception as exc:
            return {
                "success": False,
                "message": f"테스트 중 오류 발생: {str(exc)}",
                "details": {"error": str(exc)},
            }

    def _api_call(self, method: str, path: str, data: dict | None = None) -> dict:
        """브리지 API를 호출합니다."""
        if not self._session or not self._bridge_url:
            raise TransportError("브리지에 연결되지 않았습니다.")

        url = urljoin(self._bridge_url, path)

        try:
            if method == "GET":
                response = self._session.get(url, timeout=10)
            else:
                response = self._session.post(url, json=data or {}, timeout=10)

            result = response.json()

            if not response.ok:
                error = result.get("error", "알 수 없는 오류")
                raise TransportError(f"브리지 API 오류: {error}")

            return result

        except requests.RequestException as exc:
            raise TransportError(f"브리지 통신 실패: {exc}")

    def _get_bus_type(self) -> str:
        """프로토콜에 따른 버스 타입을 반환합니다."""
        if self._protocol == PROTOCOL_ISO15765:
            return "can"
        elif self._protocol in (PROTOCOL_ISO14230, PROTOCOL_ISO9141):
            return "serial"
        else:
            return "unknown"

    def _format_replies(self, replies: list[dict]) -> str:
        """브리지 응답을 ELM327 형식으로 변환합니다."""
        if not replies:
            return "NO DATA\r\r>"

        lines = []
        for reply in replies:
            source = reply.get("source", "")
            data = reply.get("data", "")

            # CAN인 경우 ISO-TP 형식
            if self._protocol == PROTOCOL_ISO15765 and source:
                try:
                    payload_bytes = bytes.fromhex(data)
                    frames = self._to_isotp_frames(payload_bytes)
                    for frame in frames:
                        hex_bytes = " ".join(f"{b:02X}" for b in frame)
                        lines.append(f"{source} {hex_bytes}")
                except Exception:
                    lines.append(f"{source} {data}")
            else:
                # K-Line 등은 그대로
                lines.append(data)

        return "\r".join(lines) + "\r>"

    def _to_isotp_frames(self, payload: bytes) -> list[bytes]:
        """UDS 페이로드를 ISO-TP 프레임으로 변환합니다."""
        if not payload:
            return []

        if len(payload) <= 7:
            return [bytes([len(payload)]) + payload]

        frames = []
        frames.append(
            bytes([0x10 | (len(payload) >> 8), len(payload) & 0xFF]) + payload[:6]
        )

        rest = payload[6:]
        seq = 1
        while rest:
            chunk, rest = rest[:7], rest[7:]
            frames.append(bytes([0x20 | seq]) + chunk)
            seq = (seq + 1) % 16

        return frames
