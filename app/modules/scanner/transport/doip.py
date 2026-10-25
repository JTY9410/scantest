"""DoIP (Diagnostics over IP) 전송 어댑터.

ISO 13400 프로토콜을 구현하여 이더넷을 통한 차량 진단을 지원합니다.
- 차량 식별 (UDP 13400)
- TCP 라우팅 활성화
- 진단 메시지 송수신
- 논리주소 기반 ECU 탐색
"""

import logging
import os
import socket
import struct
from typing import Any, Generator

from app.modules.scanner.transport.base import (
    TransportAdapter,
    TransportError,
    TransportResult,
    check_port,
    check_target_host,
    serverless,
)

_log = logging.getLogger(__name__)

# DoIP 상수
DOIP_VERSION = 0x02
DOIP_INV_VERSION = 0xFD
DOIP_PORT = 13400
DOIP_DISCOVERY_PORT = 13400

# DoIP 페이로드 타입
VEHICLE_IDENTIFICATION_REQUEST = 0x0001
VEHICLE_IDENTIFICATION_RESPONSE = 0x0004
ROUTING_ACTIVATION_REQUEST = 0x0005
ROUTING_ACTIVATION_RESPONSE = 0x0006
DIAGNOSTIC_MESSAGE = 0x8001
DIAGNOSTIC_POSITIVE_ACK = 0x8002
DIAGNOSTIC_NEGATIVE_ACK = 0x8003

# 테스터 논리주소 (표준)
TESTER_ADDRESS = 0x0E00

# 기능 주소 (브로드캐스트)
FUNCTIONAL_ADDRESS = 0xE400

# CAN 기능 주소 헤더(OBD 브로드캐스트)는 DoIP 기능 주소로 보낸다
_FUNCTIONAL_CAN_HEADERS = {"7DF", "18DB33F1"}

# DoIP NACK 코드
NACK_CODES = {
    0x00: "올바르지 않은 소스 주소",
    0x01: "알 수 없는 대상 주소",
    0x02: "메시지가 너무 큼",
    0x03: "메모리 부족",
    0x04: "대상 주소에 연결할 수 없음",
    0x05: "잘못된 대상 주소",
}


def _make_header(payload_type: int, payload_length: int) -> bytes:
    """DoIP 헤더 생성."""
    return struct.pack(
        ">BBHI",
        DOIP_VERSION,
        DOIP_INV_VERSION,
        payload_type,
        payload_length,
    )


def _make_packet(payload_type: int, payload: bytes) -> bytes:
    """DoIP 패킷 생성."""
    return _make_header(payload_type, len(payload)) + payload


def _parse_header(data: bytes) -> tuple[int, int, int]:
    """DoIP 헤더 파싱.

    Returns:
        (version, payload_type, payload_length)
    """
    if len(data) < 8:
        raise TransportError("DoIP 헤더가 너무 짧습니다.")

    version, inv_version, payload_type, payload_length = struct.unpack(">BBHI", data[:8])

    if (version ^ inv_version) != 0xFF:
        raise TransportError(
            f"잘못된 DoIP 버전: 0x{version:02X} ^ 0x{inv_version:02X} != 0xFF"
        )

    return version, payload_type, payload_length


class DoIPAdapter(TransportAdapter):
    """DoIP 전송 어댑터.

    이더넷을 통해 차량과 통신합니다.
    배포 서버(Vercel)에서는 사용할 수 없고, 차량과 같은 망의 로컬 서버에서만 동작합니다.
    """

    def __init__(self):
        self._socket: socket.socket | None = None
        self._host: str | None = None
        self._port: int = DOIP_PORT
        self._timeout: float = 2.0
        self._vehicle_info: dict[str, Any] = {}
        self._active_ecus: list[int] = []

    def connect(self, config: dict[str, Any]) -> None:
        """DoIP 게이트웨이에 연결합니다.

        Args:
            config: {"host": "192.168.0.20", "port": 13400, "timeout": 2.0}

        Raises:
            TransportError: 연결 실패 시
        """
        # Vercel 환경에서는 차량 네트워크에 접근 불가
        # 배포(서버리스) 환경에서는 차량 네트워크에 접근 불가
        if serverless():
            raise TransportError(
                "이 서버는 차량 이더넷에 연결할 수 없습니다. "
                "차량과 같은 망의 로컬 서버에서 실행하세요."
            )

        if not isinstance(config, dict):
            raise TransportError("연결 설정을 확인하세요.")
        port = check_port(config.get("port", DOIP_PORT))
        host = check_target_host(config.get("host") if isinstance(config.get("host"), str) else None, port)

        timeout = config.get("timeout", 2.0)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            timeout = 2.0
        timeout = min(max(float(timeout), 0.1), 10.0)

        try:
            self._socket = socket.create_connection((host, port), timeout)
            self._socket.settimeout(timeout)
            self._host = host
            self._port = port
            self._timeout = timeout

            # 라우팅 활성화
            self._activate_routing()

        except TransportError:
            self.disconnect()
            raise
        except (socket.timeout, TimeoutError):
            self.disconnect()
            raise TransportError("게이트웨이 연결 시간 초과") from None
        except OSError:
            self.disconnect()
            _log.warning("DoIP 게이트웨이 연결 실패", exc_info=True)
            raise TransportError("게이트웨이에 연결하지 못했습니다.") from None

    def disconnect(self) -> None:
        """연결을 종료합니다."""
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            finally:
                self._socket = None
                self._host = None
                self._vehicle_info = {}
                self._active_ecus = []

    def send_command(
        self, command: str, header: str | None = None, timeout_ms: int = 2000
    ) -> TransportResult:
        """진단 명령을 전송하고 응답을 받습니다."""
        if not self.is_connected():
            raise TransportError("연결되지 않았습니다.")

        import time

        start = time.time()

        try:
            # 헤더 파싱 (없으면 기능 주소)
            target_address = FUNCTIONAL_ADDRESS
            if header and header.upper() not in _FUNCTIONAL_CAN_HEADERS:
                try:
                    target_address = int(header, 16)
                except ValueError:
                    raise TransportError(f"잘못된 ECU 주소: {header}")

            # 명령 바이트 변환
            try:
                uds_data = bytes.fromhex(command)
            except ValueError:
                raise TransportError(f"잘못된 명령 형식: {command}")

            # 진단 메시지 전송
            payload = struct.pack(
                ">HH", TESTER_ADDRESS, target_address
            ) + uds_data
            packet = _make_packet(DIAGNOSTIC_MESSAGE, payload)
            self._socket.sendall(packet)

            # 응답 수집 (여러 ECU가 응답할 수 있음)
            replies: list[tuple[int, bytes]] = []
            self._socket.settimeout(timeout_ms / 1000.0)

            for _ in range(8):  # 최대 8개 ECU 응답
                try:
                    response_type, response_payload = self._recv_packet()

                    if response_type == DIAGNOSTIC_MESSAGE:
                        if len(response_payload) >= 4:
                            source = struct.unpack(">H", response_payload[:2])[0]
                            uds_response = response_payload[4:]
                            replies.append((source, uds_response))
                            
                            # 기능 주소로 보낸 경우, 응답한 ECU 기록
                            if target_address == FUNCTIONAL_ADDRESS and source not in self._active_ecus:
                                self._active_ecus.append(source)

                            # 응답 대기(NRC 0x78)는 최종 응답을 계속 기다린다
                            if len(uds_response) >= 3 and uds_response[0] == 0x7F and uds_response[2] == 0x78:
                                replies.pop()
                                continue
                            # 물리 주소는 한 제어기만 답하므로 바로 끝낸다
                            if target_address != FUNCTIONAL_ADDRESS:
                                break
                            # 기능 주소는 짧은 타임아웃으로 추가 응답 대기
                            self._socket.settimeout(0.2)

                    elif response_type == DIAGNOSTIC_NEGATIVE_ACK:
                        if len(response_payload) >= 5:
                            nack_code = response_payload[4]
                            error_msg = NACK_CODES.get(
                                nack_code, f"알 수 없는 NACK 코드 0x{nack_code:02X}"
                            )
                            raise TransportError(f"DoIP NACK: {error_msg}")

                    elif response_type == DIAGNOSTIC_POSITIVE_ACK:
                        # ACK는 응답이 아니라 수신 확인이므로 계속 대기
                        continue

                except (socket.timeout, TimeoutError):
                    break

            # ELM327 형식으로 변환 (기존 해석기와 호환)
            reply_text = self._format_elm_response(replies)
            elapsed = (time.time() - start) * 1000

            return TransportResult(
                command=command,
                header=header or f"{FUNCTIONAL_ADDRESS:08X}",
                reply=reply_text,
                error=None if replies else "timeout",
                elapsed_ms=elapsed,
            )

        except TransportError:
            raise
        except Exception:
            _log.warning("DoIP 명령 전송 실패", exc_info=True)
            elapsed = (time.time() - start) * 1000
            return TransportResult(
                command=command,
                header=header,
                reply=None,
                error="전송 오류",
                elapsed_ms=elapsed,
            )

    def is_connected(self) -> bool:
        """연결 상태를 반환합니다."""
        return self._socket is not None

    def get_protocol_info(self) -> dict[str, Any]:
        """DoIP 프로토콜 정보를 반환합니다."""
        return {
            "name": "DoIP (ISO 13400)",
            "bus": "can",  # DoIP는 CAN over Ethernet
            "host": self._host,
            "port": self._port,
            "vehicle": self._vehicle_info,
            "active_ecus": [f"{ecu:04X}" for ecu in self._active_ecus],
        }

    def get_vehicle_info(self) -> dict[str, Any]:
        """차량 식별 정보를 반환합니다.

        VIN, EID, GID 등을 포함합니다.
        """
        return dict(self._vehicle_info)

    def get_active_ecus(self) -> list[int]:
        """응답한 ECU 논리주소 목록을 반환합니다."""
        return list(self._active_ecus)

    def discover_vehicle(self, broadcast_address: str = "255.255.255.255") -> list[dict[str, Any]]:
        """UDP 브로드캐스트로 차량을 탐색합니다.

        Args:
            broadcast_address: 브로드캐스트 주소

        Returns:
            발견된 차량 정보 목록
        """
        vehicles = []

        try:
            # UDP 소켓 생성
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            udp_socket.settimeout(2.0)

            # 차량 식별 요청 전송
            request = _make_packet(VEHICLE_IDENTIFICATION_REQUEST, b"")
            udp_socket.sendto(request, (broadcast_address, DOIP_DISCOVERY_PORT))

            # 응답 수신 (여러 차량이 응답할 수 있음)
            while True:
                try:
                    data, addr = udp_socket.recvfrom(4096)
                    version, payload_type, payload_length = _parse_header(data[:8])

                    if payload_type == VEHICLE_IDENTIFICATION_RESPONSE:
                        payload = data[8 : 8 + payload_length]
                        vehicle_info = self._parse_vehicle_identification(payload)
                        vehicle_info["address"] = addr[0]
                        vehicles.append(vehicle_info)

                except socket.timeout:
                    break

            udp_socket.close()

        except TransportError:
            raise
        except Exception:
            _log.warning("DoIP 차량 탐색 실패", exc_info=True)
            raise TransportError("차량 탐색에 실패했습니다.") from None

        return vehicles

    def _activate_routing(self) -> None:
        """라우팅을 활성화합니다.

        DoIP 통신을 시작하기 전에 반드시 호출해야 합니다.
        """
        # 라우팅 활성화 요청
        # Activation Type: 0x00 (Default), 0x01 (WWH-OBD)
        payload = struct.pack(">HI", TESTER_ADDRESS, 0x00000000)
        packet = _make_packet(ROUTING_ACTIVATION_REQUEST, payload)
        self._socket.sendall(packet)

        # 응답 대기
        response_type, response_payload = self._recv_packet()

        if response_type != ROUTING_ACTIVATION_RESPONSE:
            raise TransportError(
                f"라우팅 활성화 응답이 아닙니다: 0x{response_type:04X}"
            )

        if len(response_payload) < 9:
            raise TransportError("라우팅 활성화 응답이 너무 짧습니다.")

        # Response Code: 0x10 (성공)
        response_code = response_payload[4]
        if response_code != 0x10:
            raise TransportError(
                f"DoIP 라우팅 활성화 실패: 응답 코드 0x{response_code:02X}"
            )

    def _recv_packet(self) -> tuple[int, bytes]:
        """DoIP 패킷을 수신합니다.

        Returns:
            (payload_type, payload)
        """
        # 헤더 수신
        header = self._recv_exact(8)
        version, payload_type, payload_length = _parse_header(header)

        if payload_length > 4096:
            raise TransportError(
                f"DoIP 페이로드가 너무 큽니다: {payload_length} bytes"
            )

        # 페이로드 수신
        payload = self._recv_exact(payload_length) if payload_length > 0 else b""

        return payload_type, payload

    def _recv_exact(self, size: int) -> bytes:
        """정확한 크기만큼 데이터를 수신합니다."""
        buf = b""
        while len(buf) < size:
            chunk = self._socket.recv(size - len(buf))
            if not chunk:
                raise TransportError("DoIP 연결이 끊겼습니다.")
            buf += chunk
        return buf

    def _parse_vehicle_identification(self, payload: bytes) -> dict[str, Any]:
        """차량 식별 응답을 파싱합니다."""
        if len(payload) < 33:
            return {}

        try:
            vin = payload[0:17].decode("ascii").strip("\x00")
            logical_address = struct.unpack(">H", payload[17:19])[0]
            eid = payload[19:25].hex().upper()
            gid = payload[25:31].hex().upper()

            return {
                "vin": vin if vin else None,
                "logical_address": f"{logical_address:04X}",
                "eid": eid,
                "gid": gid,
            }
        except Exception:
            return {}

    def _format_elm_response(self, replies: list[tuple[int, bytes]]) -> str:
        """DoIP 응답을 ELM327 형식으로 변환합니다.

        기존 obd.py 해석기와 호환되도록 ISO-TP 프레임 형식으로 변환합니다.
        """
        if not replies:
            return "NO DATA\r\r>"

        lines = []
        for source, payload in replies:
            can_id = f"{source:08X}"
            frames = self._to_isotp_frames(payload)
            for frame in frames:
                hex_bytes = " ".join(f"{b:02X}" for b in frame)
                lines.append(f"{can_id} {hex_bytes}")

        return "\r".join(lines) + "\r>"

    def _to_isotp_frames(self, payload: bytes) -> list[bytes]:
        """UDS 페이로드를 ISO-TP 프레임으로 변환합니다."""
        if not payload:
            return []

        # Single Frame (길이 ≤ 7)
        if len(payload) <= 7:
            return [bytes([len(payload)]) + payload]

        # First Frame + Consecutive Frames
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

    def test_connection(self) -> dict[str, Any]:
        """DoIP 연결 테스트를 수행합니다."""
        try:
            if not self.is_connected():
                return {
                    "success": False,
                    "message": "연결되지 않았습니다.",
                    "details": {},
                }

            # 간단한 테스트 명령 (OBD 지원 PID 조회)
            result = self.send_command("0100", timeout_ms=2000)

            if result.error:
                return {
                    "success": False,
                    "message": f"테스트 명령 실패: {result.error}",
                    "details": {},
                }

            return {
                "success": True,
                "message": "DoIP 연결 테스트 성공",
                "details": {
                    "protocol": self.get_protocol_info(),
                    "result": result.__dict__,
                },
            }

        except Exception:
            _log.exception("DoIP 연결 테스트 오류")
            return {"success": False, "message": "테스트 중 오류가 발생했습니다.", "details": {}}
