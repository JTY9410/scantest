"""J2534 모의 브리지 서버.

실제 J2534 장비 없이 테스트할 수 있도록 모의 응답을 제공합니다.
표준 OBD2 명령에 대한 가짜 응답을 반환합니다.
"""

import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="J2534 Mock Bridge",
    description="J2534 모의 브리지 서버 (테스트용)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 모의 세션
mock_devices = {}
mock_channels = {}
device_counter = 0
channel_counter = 0

# 모의 응답 데이터
MOCK_RESPONSES = {
    "0100": "41 00 BE 1F B8 13",  # 지원 PID
    "0101": "41 01 00 07 65 04",  # MIL, DTC 수
    "010C": "41 0C 0A F0",  # RPM
    "010D": "41 0D 3C",  # 속도
    "0105": "41 05 5A",  # 냉각수 온도
    "ATDPN": "6",  # CAN 11비트
    "03": "43 01 03 04 5B C2",  # DTC
    "22F190": "62 F1 90 57 44 43 5A 47 38 41 48 37 32 33 34 35 36 37 38",  # VIN
}


class DeviceOpenRequest(BaseModel):
    device_name: str | None = None


class DeviceOpenResponse(BaseModel):
    device_id: int


class DeviceCloseRequest(BaseModel):
    device_id: int


class ChannelConnectRequest(BaseModel):
    device_id: int
    protocol: int
    flags: int
    baudrate: int


class ChannelConnectResponse(BaseModel):
    channel_id: int


class ChannelDisconnectRequest(BaseModel):
    channel_id: int


class MessageSendRequest(BaseModel):
    channel_id: int
    data: str
    header: str | None = None
    timeout_ms: int = 2000


class MessageSendResponse(BaseModel):
    replies: list[dict[str, Any]]


@app.get("/api/status")
async def get_status():
    """브리지 상태 (항상 준비됨)."""
    return {
        "ready": True,
        "platform": "mock",
        "devices_available": 1,
        "active_devices": len(mock_devices),
        "active_channels": len(mock_channels),
        "note": "이것은 테스트용 모의 서버입니다.",
    }


@app.get("/api/devices")
async def list_devices():
    """모의 장비 목록."""
    return {
        "devices": [
            {
                "name": "모의 J2534 장비",
                "vendor": "WecarScan Test",
                "dll_path": "mock.dll",
                "key": "MOCK",
            }
        ]
    }


@app.post("/api/device/open", response_model=DeviceOpenResponse)
async def open_device(request: DeviceOpenRequest):
    """모의 장비 열기."""
    global device_counter
    device_counter += 1
    device_id = device_counter

    mock_devices[device_id] = {
        "name": request.device_name or "모의 장비",
    }

    logger.info(f"[MOCK] 장비 열림: {device_id}")
    return DeviceOpenResponse(device_id=device_id)


@app.post("/api/device/close")
async def close_device(request: DeviceCloseRequest):
    """모의 장비 닫기."""
    if request.device_id not in mock_devices:
        raise HTTPException(status_code=404, detail="장비를 찾을 수 없습니다.")

    del mock_devices[request.device_id]
    logger.info(f"[MOCK] 장비 닫힘: {request.device_id}")
    return {"success": True}


@app.post("/api/channel/connect", response_model=ChannelConnectResponse)
async def connect_channel(request: ChannelConnectRequest):
    """모의 채널 연결."""
    global channel_counter

    if request.device_id not in mock_devices:
        raise HTTPException(status_code=404, detail="장비를 찾을 수 없습니다.")

    channel_counter += 1
    channel_id = channel_counter

    mock_channels[channel_id] = {
        "device_id": request.device_id,
        "protocol": request.protocol,
    }

    logger.info(f"[MOCK] 채널 연결: {channel_id} (프로토콜 {request.protocol})")
    return ChannelConnectResponse(channel_id=channel_id)


@app.post("/api/channel/disconnect")
async def disconnect_channel(request: ChannelDisconnectRequest):
    """모의 채널 종료."""
    if request.channel_id not in mock_channels:
        raise HTTPException(status_code=404, detail="채널을 찾을 수 없습니다.")

    del mock_channels[request.channel_id]
    logger.info(f"[MOCK] 채널 종료: {request.channel_id}")
    return {"success": True}


@app.post("/api/message/send", response_model=MessageSendResponse)
async def send_message(request: MessageSendRequest):
    """모의 메시지 전송 및 응답."""
    if request.channel_id not in mock_channels:
        raise HTTPException(status_code=404, detail="채널을 찾을 수 없습니다.")

    command = request.data.replace(" ", "").upper()

    logger.info(f"[MOCK] 명령: {command}")

    # 모의 응답 생성
    reply_data = MOCK_RESPONSES.get(command)

    if reply_data:
        source = request.header or "7E8"  # 엔진 ECU
        replies = [{"source": source, "data": reply_data.replace(" ", "")}]
    else:
        # 알 수 없는 명령은 빈 응답
        logger.warning(f"[MOCK] 알 수 없는 명령: {command}")
        replies = []

    logger.info(f"[MOCK] 응답: {len(replies)}개")

    return MessageSendResponse(replies=replies)


if __name__ == "__main__":
    import uvicorn

    logger.info("J2534 모의 브리지 서버 시작: http://localhost:5000")
    logger.warning("⚠️  이것은 테스트용 모의 서버입니다. 실제 차량과 연결되지 않습니다.")

    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="info")
