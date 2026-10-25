"""모의 DoIP 게이트웨이 서버.

테스트용으로 DoIP 프로토콜을 시뮬레이션합니다.
실제 차량 없이도 DoIP 연결 흐름을 테스트할 수 있습니다.
"""

import socket
import struct
import threading
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DOIP_PORT = 13400
DOIP_VERSION = 0x02
DOIP_INV_VERSION = 0xFD

# 페이로드 타입
ROUTING_ACTIVATION_REQUEST = 0x0005
ROUTING_ACTIVATION_RESPONSE = 0x0006
DIAGNOSTIC_MESSAGE = 0x8001
DIAGNOSTIC_POSITIVE_ACK = 0x8002


def make_packet(payload_type: int, payload: bytes) -> bytes:
    """DoIP 패킷 생성."""
    header = struct.pack(
        ">BBHI",
        DOIP_VERSION,
        DOIP_INV_VERSION,
        payload_type,
        len(payload),
    )
    return header + payload


class MockDoIPGateway:
    """모의 DoIP 게이트웨이."""

    def __init__(self, host: str = "0.0.0.0", port: int = DOIP_PORT):
        self.host = host
        self.port = port
        self.server_socket: socket.socket | None = None
        self.running = False
        self.routing_code = 0x10  # 라우팅 활성화 응답 코드 (0x10 = 성공)

        # 모의 응답 (이미 bytes)
        self.responses = {
            b"\x01\x00": b"\x41\x00\xBE\x1F\xB8\x13",  # PID 지원
            b"\x01\x01": b"\x41\x01\x00\x07\x65\x04",  # MIL, DTC
            b"\x01\x0C": b"\x41\x0C\x0A\xF0",  # RPM
            b"\x03": b"\x43\x01\x03\x04\x5B\xC2",  # DTC
            b"\x22\xF1\x90": b"\x62\xF1\x90WDCZG8AH723456789"[:20],  # VIN
        }

    def start(self):
        """서버 시작."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.port = self.server_socket.getsockname()[1]  # port=0이면 OS가 고른 포트
        self.server_socket.listen(5)
        self.running = True

        logger.info(f"[MOCK DoIP] 게이트웨이 시작: {self.host}:{self.port}")

        self._accept_thread = threading.Thread(target=self._accept_connections, daemon=True)
        self._accept_thread.start()

    def stop(self):
        """서버 종료."""
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.server_socket.close()
        thread = getattr(self, "_accept_thread", None)
        if thread is not None:
            thread.join(timeout=2.0)

    def _accept_connections(self):
        """연결 수락."""
        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                logger.info(f"[MOCK DoIP] 클라이언트 연결: {addr}")

                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket,),
                    daemon=True,
                )
                client_thread.start()

            except Exception as exc:
                if self.running:
                    logger.error(f"[MOCK DoIP] 연결 수락 오류: {exc}")

    def _handle_client(self, client_socket: socket.socket):
        """클라이언트 요청 처리."""
        try:
            while self.running:
                # 헤더 수신
                header = self._recv_exact(client_socket, 8)
                if not header:
                    break

                payload_type = struct.unpack(">H", header[2:4])[0]
                payload_length = struct.unpack(">I", header[4:8])[0]

                # 페이로드 수신
                payload = self._recv_exact(client_socket, payload_length)
                if not payload:
                    break

                logger.info(
                    f"[MOCK DoIP] 수신: 타입=0x{payload_type:04X}, "
                    f"길이={payload_length}"
                )

                # 요청 처리
                if payload_type == ROUTING_ACTIVATION_REQUEST:
                    # 라우팅 활성화 응답 (성공)
                    # ISO 13400-2: 테스터 주소(2) + 게이트웨이 주소(2) + 응답 코드(1) + 예약(4)
                    response = struct.pack(
                        ">HHBI",
                        0x0E00,  # 테스터 주소
                        0x10E0,  # 게이트웨이 주소
                        self.routing_code,  # 0x10 = 성공
                        0x00000000,  # 예약(ISO)
                    )

                    packet = make_packet(ROUTING_ACTIVATION_RESPONSE, response)
                    client_socket.sendall(packet)
                    logger.info("[MOCK DoIP] 라우팅 활성화 응답 전송")

                elif payload_type == DIAGNOSTIC_MESSAGE:
                    # 진단 메시지
                    if len(payload) < 4:
                        continue

                    source = struct.unpack(">H", payload[:2])[0]
                    target = struct.unpack(">H", payload[2:4])[0]
                    uds_data = payload[4:]

                    logger.info(
                        f"[MOCK DoIP] 진단 메시지: "
                        f"소스=0x{source:04X}, 대상=0x{target:04X}, "
                        f"UDS={uds_data.hex()}"
                    )

                    # Positive ACK
                    ack = struct.pack(">HHB", 0x10E0, source, 0x00)
                    client_socket.sendall(make_packet(DIAGNOSTIC_POSITIVE_ACK, ack))

                    # 모의 응답 생성
                    response_data = self.responses.get(uds_data, b"\x7F" + uds_data[:1] + b"\x11")

                    response = struct.pack(">HH", 0x10E0, source) + response_data
                    client_socket.sendall(make_packet(DIAGNOSTIC_MESSAGE, response))

                    logger.info(f"[MOCK DoIP] 진단 응답: {response_data.hex()}")

        except Exception as exc:
            logger.error(f"[MOCK DoIP] 클라이언트 처리 오류: {exc}")
        finally:
            client_socket.close()

    def _recv_exact(self, sock: socket.socket, size: int) -> bytes:
        """정확한 크기만큼 수신."""
        buf = b""
        while len(buf) < size:
            try:
                chunk = sock.recv(size - len(buf))
                if not chunk:
                    return b""
                buf += chunk
            except Exception:
                return b""
        return buf


if __name__ == "__main__":
    gateway = MockDoIPGateway()
    gateway.start()

    try:
        logger.info("[MOCK DoIP] 서버 실행 중. Ctrl+C로 종료하세요.")
        threading.Event().wait()
    except KeyboardInterrupt:
        logger.info("[MOCK DoIP] 서버 종료 중...")
        gateway.stop()
