"""J2534 DLL ctypes 래퍼.

SAE J2534-1/-2 표준 함수를 ctypes로 래핑합니다.
Windows 레지스트리에서 설치된 J2534 장비를 찾고 DLL을 로드합니다.
"""

import ctypes
import logging
import sys
from ctypes import c_char_p, c_long, c_ulong, c_void_p, POINTER, Structure
from typing import Any

if sys.platform == "win32":
    import winreg

logger = logging.getLogger(__name__)

# J2534 프로토콜 ID
PROTOCOL_J1850VPW = 1
PROTOCOL_J1850PWM = 2
PROTOCOL_ISO9141 = 3
PROTOCOL_ISO14230 = 4
PROTOCOL_CAN = 5  # ISO 15765-4
PROTOCOL_ISO15765 = 5

# J2534 오류 코드
ERR_SUCCESS = 0x00
ERR_NOT_SUPPORTED = 0x01
ERR_INVALID_CHANNEL_ID = 0x02
ERR_INVALID_PROTOCOL_ID = 0x03
ERR_NULL_PARAMETER = 0x04
ERR_INVALID_IOCTL_VALUE = 0x05
ERR_INVALID_FLAGS = 0x06
ERR_FAILED = 0x07
ERR_DEVICE_NOT_CONNECTED = 0x08
ERR_TIMEOUT = 0x09
ERR_INVALID_MSG = 0x0A
ERR_INVALID_TIME_INTERVAL = 0x0B
ERR_EXCEEDED_LIMIT = 0x0C
ERR_INVALID_MSG_ID = 0x0D
ERR_DEVICE_IN_USE = 0x0E
ERR_INVALID_IOCTL_ID = 0x0F
ERR_BUFFER_EMPTY = 0x10
ERR_BUFFER_FULL = 0x11
ERR_BUFFER_OVERFLOW = 0x12
ERR_PIN_INVALID = 0x13
ERR_CHANNEL_IN_USE = 0x14
ERR_MSG_PROTOCOL_ID = 0x15
ERR_INVALID_FILTER_ID = 0x16
ERR_NO_FLOW_CONTROL = 0x17
ERR_NOT_UNIQUE = 0x18
ERR_INVALID_BAUDRATE = 0x19

ERROR_MESSAGES = {
    ERR_NOT_SUPPORTED: "지원하지 않는 기능입니다.",
    ERR_INVALID_CHANNEL_ID: "잘못된 채널 ID입니다.",
    ERR_INVALID_PROTOCOL_ID: "잘못된 프로토콜 ID입니다.",
    ERR_NULL_PARAMETER: "NULL 파라미터입니다.",
    ERR_INVALID_FLAGS: "잘못된 플래그입니다.",
    ERR_FAILED: "작업이 실패했습니다.",
    ERR_DEVICE_NOT_CONNECTED: "장비가 연결되지 않았습니다.",
    ERR_TIMEOUT: "시간 초과",
    ERR_DEVICE_IN_USE: "장비가 이미 사용 중입니다.",
    ERR_BUFFER_EMPTY: "버퍼가 비어 있습니다.",
    ERR_BUFFER_FULL: "버퍼가 가득 찼습니다.",
}


class J2534Error(Exception):
    """J2534 DLL 오류."""

    def __init__(self, code: int, message: str | None = None):
        self.code = code
        self.message = message or ERROR_MESSAGES.get(code, f"J2534 오류 0x{code:02X}")
        super().__init__(self.message)


# J2534 구조체
class PASSTHRU_MSG(Structure):
    _fields_ = [
        ("ProtocolID", c_ulong),
        ("RxStatus", c_ulong),
        ("TxFlags", c_ulong),
        ("Timestamp", c_ulong),
        ("DataSize", c_ulong),
        ("ExtraDataIndex", c_ulong),
        ("Data", c_ulong * 4128),  # 최대 메시지 크기
    ]


class J2534Wrapper:
    """J2534 DLL 래퍼.

    Windows 레지스트리에서 J2534 장비를 찾고 DLL 함수를 호출합니다.
    """

    def __init__(self):
        self.dll = None
        self.device_id: c_ulong | None = None

    def list_devices(self) -> list[dict[str, Any]]:
        """레지스트리에서 설치된 J2534 장비 목록을 반환합니다."""
        if sys.platform != "win32":
            return []

        devices = []

        try:
            # PassThruSupport.04.04 키 확인
            base_key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\PassThruSupport.04.04",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
            )

            # 모든 하위 키 열거
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(base_key, i)
                    subkey = winreg.OpenKey(base_key, subkey_name)

                    # 장비 정보 읽기
                    try:
                        name = winreg.QueryValueEx(subkey, "Name")[0]
                        vendor = winreg.QueryValueEx(subkey, "Vendor")[0]
                        dll_path = winreg.QueryValueEx(subkey, "FunctionLibrary")[0]

                        devices.append({
                            "name": name,
                            "vendor": vendor,
                            "dll_path": dll_path,
                            "key": subkey_name,
                        })

                    except FileNotFoundError:
                        pass

                    winreg.CloseKey(subkey)
                    i += 1

                except OSError:
                    break

            winreg.CloseKey(base_key)

        except FileNotFoundError:
            logger.warning("PassThruSupport.04.04 레지스트리 키를 찾을 수 없습니다.")

        return devices

    def load_dll(self, dll_path: str | None = None) -> None:
        """J2534 DLL을 로드합니다."""
        if self.dll is not None:
            return

        if dll_path:
            # 지정된 DLL 로드
            try:
                self.dll = ctypes.WinDLL(dll_path)
                logger.info(f"J2534 DLL 로드: {dll_path}")
                return
            except Exception as exc:
                raise J2534Error(ERR_FAILED, f"DLL 로드 실패: {exc}")

        # 레지스트리에서 첫 번째 장비의 DLL 로드
        devices = self.list_devices()
        if not devices:
            raise J2534Error(
                ERR_DEVICE_NOT_CONNECTED,
                "설치된 J2534 장비가 없습니다. "
                "장비 드라이버를 설치하세요.",
            )

        first_device = devices[0]
        try:
            self.dll = ctypes.WinDLL(first_device["dll_path"])
            logger.info(
                f"J2534 DLL 로드: {first_device['name']} ({first_device['dll_path']})"
            )
        except Exception as exc:
            raise J2534Error(
                ERR_FAILED,
                f"DLL 로드 실패 ({first_device['name']}): {exc}",
            )

    def open(self, device_name: str | None = None) -> c_ulong:
        """J2534 장비를 엽니다.

        Returns:
            device_id
        """
        self.load_dll()

        device_id = c_ulong(0)

        # PassThruOpen 함수 호출
        func = self.dll.PassThruOpen
        func.argtypes = [c_void_p, POINTER(c_ulong)]
        func.restype = c_long

        name_ptr = c_char_p(device_name.encode()) if device_name else None
        result = func(name_ptr, ctypes.byref(device_id))

        if result != ERR_SUCCESS:
            raise J2534Error(result)

        self.device_id = device_id
        logger.info(f"J2534 장비 열림: device_id={device_id.value}")

        return device_id

    def close(self, device_id: c_ulong) -> None:
        """J2534 장비를 닫습니다."""
        if not self.dll:
            return

        func = self.dll.PassThruClose
        func.argtypes = [c_ulong]
        func.restype = c_long

        result = func(device_id)
        if result != ERR_SUCCESS:
            raise J2534Error(result)

        logger.info(f"J2534 장비 닫힘: device_id={device_id.value}")

    def connect(
        self, device_id: c_ulong, protocol: int, flags: int, baudrate: int
    ) -> c_ulong:
        """진단 채널을 연결합니다.

        Returns:
            channel_id
        """
        if not self.dll:
            raise J2534Error(ERR_DEVICE_NOT_CONNECTED)

        channel_id = c_ulong(0)

        func = self.dll.PassThruConnect
        func.argtypes = [c_ulong, c_ulong, c_ulong, c_ulong, POINTER(c_ulong)]
        func.restype = c_long

        result = func(
            device_id,
            c_ulong(protocol),
            c_ulong(flags),
            c_ulong(baudrate),
            ctypes.byref(channel_id),
        )

        if result != ERR_SUCCESS:
            raise J2534Error(result)

        logger.info(
            f"J2534 채널 연결: channel_id={channel_id.value}, "
            f"protocol={protocol}, baudrate={baudrate}"
        )

        return channel_id

    def disconnect(self, channel_id: c_ulong) -> None:
        """진단 채널을 종료합니다."""
        if not self.dll:
            return

        func = self.dll.PassThruDisconnect
        func.argtypes = [c_ulong]
        func.restype = c_long

        result = func(channel_id)
        if result != ERR_SUCCESS:
            raise J2534Error(result)

        logger.info(f"J2534 채널 종료: channel_id={channel_id.value}")

    def write_read(
        self, channel_id: c_ulong, data: bytes, timeout_ms: int
    ) -> list[dict[str, Any]]:
        """메시지를 전송하고 응답을 받습니다."""
        if not self.dll:
            raise J2534Error(ERR_DEVICE_NOT_CONNECTED)

        # 메시지 전송
        tx_msg = PASSTHRU_MSG()
        tx_msg.ProtocolID = PROTOCOL_CAN  # TODO: 채널 프로토콜에 맞춰야 함
        tx_msg.TxFlags = 0
        tx_msg.DataSize = len(data)
        for i, byte in enumerate(data):
            tx_msg.Data[i] = byte

        num_msgs = c_ulong(1)

        func_write = self.dll.PassThruWriteMsgs
        func_write.argtypes = [c_ulong, POINTER(PASSTHRU_MSG), c_ulong, POINTER(c_ulong)]
        func_write.restype = c_long

        result = func_write(
            channel_id,
            ctypes.byref(tx_msg),
            c_ulong(1),
            ctypes.byref(num_msgs),
        )

        if result != ERR_SUCCESS:
            raise J2534Error(result)

        # 응답 수신
        rx_msgs = (PASSTHRU_MSG * 10)()  # 최대 10개 메시지
        num_msgs = c_ulong(10)

        func_read = self.dll.PassThruReadMsgs
        func_read.argtypes = [c_ulong, POINTER(PASSTHRU_MSG), POINTER(c_ulong), c_ulong]
        func_read.restype = c_long

        result = func_read(
            channel_id,
            ctypes.byref(rx_msgs),
            ctypes.byref(num_msgs),
            c_ulong(timeout_ms),
        )

        # 타임아웃은 오류로 처리하지 않음
        if result != ERR_SUCCESS and result != ERR_TIMEOUT and result != ERR_BUFFER_EMPTY:
            raise J2534Error(result)

        # 응답 변환
        replies = []
        for i in range(num_msgs.value):
            msg = rx_msgs[i]
            data_bytes = bytes(msg.Data[: msg.DataSize])

            # CAN ID 추출 (프로토콜에 따라 다름)
            source = ""
            if msg.ProtocolID == PROTOCOL_CAN and msg.DataSize > 4:
                # CAN 메시지: [ID(4)] + [데이터]
                can_id = int.from_bytes(data_bytes[:4], "big")
                source = f"{can_id:08X}"
                data_bytes = data_bytes[4:]

            replies.append({"source": source, "data": data_bytes})

        return replies
