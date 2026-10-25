"""J2534 로컬 브리지 서버.

Windows PC에서 실행되어 J2534 DLL과 통신하고,
scantest 서버에 HTTP/WebSocket API를 제공합니다.

사용법:
    python -m bridge.main

환경 변수:
    BRIDGE_PORT: 서버 포트 (기본 5000)
    BRIDGE_HOST: 바인드 주소 (기본 0.0.0.0)
"""

import logging
import sys
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from bridge.j2534_wrapper import J2534Error, J2534Wrapper

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# FastAPI 앱
app = FastAPI(
    title="J2534 Bridge",
    description="J2534 패스스루 장비를 위한 로컬 브리지 서버",
    version="1.0.0",
)

# CORS 설정 (로컬 개발용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# J2534 래퍼 인스턴스
j2534 = J2534Wrapper()

# 활성 세션 저장
devices: dict[int, Any] = {}
channels: dict[int, Any] = {}
device_counter = 0
channel_counter = 0


# 요청/응답 모델
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
    data: str  # 16진수 문자열
    header: str | None = None
    timeout_ms: int = 2000


class MessageSendResponse(BaseModel):
    replies: list[dict[str, Any]]


# API 엔드포인트


@app.get("/api/status")
async def get_status():
    """브리지 상태를 반환합니다."""
    try:
        # Windows 플랫폼 확인
        if sys.platform != "win32":
            return {
                "ready": False,
                "error": "J2534는 Windows에서만 사용할 수 있습니다.",
                "platform": sys.platform,
            }

        # J2534 DLL 확인
        available_devices = j2534.list_devices()

        return {
            "ready": True,
            "platform": sys.platform,
            "devices_available": len(available_devices),
            "active_devices": len(devices),
            "active_channels": len(channels),
        }

    except Exception as exc:
        logger.error(f"상태 확인 실패: {exc}")
        return {"ready": False, "error": str(exc)}


@app.get("/api/devices")
async def list_devices():
    """사용 가능한 J2534 장비 목록을 반환합니다."""
    try:
        device_list = j2534.list_devices()
        return {"devices": device_list}

    except J2534Error as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"장비 목록 조회 실패: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/device/open", response_model=DeviceOpenResponse)
async def open_device(request: DeviceOpenRequest):
    """J2534 장비를 엽니다."""
    global device_counter

    try:
        device_id_internal = j2534.open(request.device_name)

        device_counter += 1
        device_id = device_counter

        devices[device_id] = {
            "internal_id": device_id_internal,
            "name": request.device_name,
        }

        logger.info(f"장비 열림: {device_id} ({request.device_name})")

        return DeviceOpenResponse(device_id=device_id)

    except J2534Error as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"장비 열기 실패: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/device/close")
async def close_device(request: DeviceCloseRequest):
    """J2534 장비를 닫습니다."""
    try:
        device = devices.get(request.device_id)
        if not device:
            raise HTTPException(status_code=404, detail="장비를 찾을 수 없습니다.")

        j2534.close(device["internal_id"])
        del devices[request.device_id]

        # 이 장비의 모든 채널 닫기
        for channel_id in list(channels.keys()):
            if channels[channel_id]["device_id"] == request.device_id:
                del channels[channel_id]

        logger.info(f"장비 닫힘: {request.device_id}")

        return {"success": True}

    except J2534Error as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"장비 닫기 실패: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/channel/connect", response_model=ChannelConnectResponse)
async def connect_channel(request: ChannelConnectRequest):
    """진단 채널을 연결합니다."""
    global channel_counter

    try:
        device = devices.get(request.device_id)
        if not device:
            raise HTTPException(status_code=404, detail="장비를 찾을 수 없습니다.")

        channel_id_internal = j2534.connect(
            device["internal_id"],
            request.protocol,
            request.flags,
            request.baudrate,
        )

        channel_counter += 1
        channel_id = channel_counter

        channels[channel_id] = {
            "internal_id": channel_id_internal,
            "device_id": request.device_id,
            "protocol": request.protocol,
        }

        logger.info(
            f"채널 연결: {channel_id} (장비 {request.device_id}, 프로토콜 {request.protocol})"
        )

        return ChannelConnectResponse(channel_id=channel_id)

    except J2534Error as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"채널 연결 실패: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/channel/disconnect")
async def disconnect_channel(request: ChannelDisconnectRequest):
    """진단 채널을 종료합니다."""
    try:
        channel = channels.get(request.channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="채널을 찾을 수 없습니다.")

        j2534.disconnect(channel["internal_id"])
        del channels[request.channel_id]

        logger.info(f"채널 종료: {request.channel_id}")

        return {"success": True}

    except J2534Error as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"채널 종료 실패: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/message/send", response_model=MessageSendResponse)
async def send_message(request: MessageSendRequest):
    """진단 메시지를 전송하고 응답을 받습니다."""
    try:
        channel = channels.get(request.channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="채널을 찾을 수 없습니다.")

        # 16진수 문자열을 바이트로 변환
        try:
            data_bytes = bytes.fromhex(request.data)
        except ValueError:
            raise HTTPException(status_code=400, detail="잘못된 16진수 형식입니다.")

        # 메시지 전송 및 응답 수신
        replies = j2534.write_read(
            channel["internal_id"],
            data_bytes,
            request.timeout_ms,
        )

        # 응답 형식 변환
        reply_list = [
            {"source": reply["source"], "data": reply["data"].hex().upper()}
            for reply in replies
        ]

        logger.debug(
            f"메시지 전송: 채널 {request.channel_id}, "
            f"명령 {request.data}, 응답 {len(reply_list)}개"
        )

        return MessageSendResponse(replies=reply_list)

    except J2534Error as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"메시지 전송 실패: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    import os
    import uvicorn

    # 설정
    port = int(os.environ.get("BRIDGE_PORT", "5000"))
    host = os.environ.get("BRIDGE_HOST", "0.0.0.0")

    # Windows 확인
    if sys.platform != "win32":
        logger.error("J2534 브리지는 Windows에서만 실행할 수 있습니다.")
        sys.exit(1)

    logger.info(f"J2534 브리지 서버 시작: http://{host}:{port}")

    uvicorn.run(app, host=host, port=port, log_level="info")
