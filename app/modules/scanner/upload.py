"""스캔 데이터 업로드 및 처리.

CSV(PCAN), TRC 파일을 업로드하면 run_scan과 동일한 효과(해석, 보고서 생성)를 냅니다.
"""

import hashlib
from datetime import datetime
from typing import BinaryIO

from flask import current_app
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.modules.accounts.models import User
from app.modules.canlab.engine.decode import load_trace
from app.modules.scanner.service import run_scan, ServiceError
from app.modules.scans.car_info import normalize_car_no, normalize_dto


# 업로드 제한
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_EXTENSIONS = {".csv", ".trc", ".txt", ".log"}


class UploadError(Exception):
    """업로드 처리 오류."""
    pass


def validate_upload(file: FileStorage) -> None:
    """업로드 파일 검증."""
    if not file or not file.filename:
        raise UploadError("파일을 선택해주세요.")
    
    # 확장자 확인
    filename = file.filename.lower()
    if not any(filename.endswith(ext) for ext in ALLOWED_EXTENSIONS):
        raise UploadError(f"지원하지 않는 파일 형식입니다. 허용: {', '.join(ALLOWED_EXTENSIONS)}")
    
    # 파일 크기 확인
    file.seek(0, 2)  # Seek to end
    size = file.tell()
    file.seek(0)  # Reset
    
    if size == 0:
        raise UploadError("빈 파일입니다.")
    
    if size > MAX_UPLOAD_SIZE:
        raise UploadError(f"파일 크기가 너무 큽니다. 최대 {MAX_UPLOAD_SIZE // 1024 // 1024}MB까지 업로드 가능합니다.")


def parse_uploaded_trace(content: bytes, filename: str) -> str:
    """업로드된 파일을 WeCar ELM 형식으로 변환."""
    try:
        text = content.decode("utf-8", errors="replace")
    except Exception as exc:
        raise UploadError(f"파일을 읽을 수 없습니다: {exc}")
    
    if not text.strip():
        raise UploadError("빈 파일입니다.")
    
    # load_trace로 파싱 시도
    try:
        trace = load_trace(text)
    except Exception as exc:
        # 간단한 형식 체크
        if "7E" not in text.upper() and "ID" not in text:
            raise UploadError(f"올바른 CAN 로그 형식이 아닙니다: {exc}")
        # 형식은 맞는 것 같지만 파싱 실패
        raise UploadError(f"CAN 로그를 파싱하지 못했습니다: {exc}")
    
    # Tesla broadcast는 UDS transactions 없이 frames만 있음
    if not trace.transactions and not trace.frames:
        raise UploadError("유효한 CAN 데이터가 없습니다.")
    
    # WeCar ELM 형식으로 변환
    # (이미 text가 load_trace로 파싱되었으므로, 원본을 그대로 사용)
    return text


def convert_to_scan_steps(trace_text: str) -> list[dict]:
    """Trace를 스캔 스텝으로 변환.
    
    run_scan이 기대하는 steps 형식으로 변환합니다.
    같은 (header, command)는 마지막 긍정 응답만 유지하여 단계 수를 줄입니다.
    """
    from app.modules.canlab.engine.decode import load_trace
    
    trace = load_trace(trace_text)
    
    # (header, command) → step 매핑. 마지막 긍정 응답만 유지
    step_map: dict[tuple[str | None, str], dict] = {}
    
    for i, tx in enumerate(trace.transactions):
        # 요청 데이터 (8바이트 초과도 허용)
        request_data = tx.request.hex().upper() if tx.request else ""
        
        # 헤더 설정: pair_transactions가 이미 request_id를 조정했으므로
        # (기능주소 응답은 응답 ID - 8로 설정됨)
        # 모든 request_id를 header로 사용
        header = f"{tx.request_id:03X}"
        
        # 명령 (ELM 형식: 2자리마다 공백)
        command = " ".join(request_data[i:i+2] for i in range(0, len(request_data), 2)) if request_data else ""
        
        # 응답 처리 (ELM 형식: 응답 주소 + 데이터, 2자리마다 공백)
        reply = None
        if tx.response and tx.response_id:
            hex_str = tx.response.hex().upper()
            # ELM 형식: 응답 주소를 앞에 붙임
            resp_addr = f"{tx.response_id:03X}"
            data = " ".join(hex_str[i:i+2] for i in range(0, len(hex_str), 2))
            reply = f"{resp_addr} {data}"
        elif tx.negative_code is not None and tx.response_id:
            nrc_hex = f"7F{tx.service:02X}{tx.negative_code:02X}"
            resp_addr = f"{tx.response_id:03X}"
            nrc_data = " ".join(nrc_hex[i:i+2] for i in range(0, len(nrc_hex), 2))
            reply = f"{resp_addr} {nrc_data}"
        elif not tx.expects_response:
            # suppressPosRsp: 응답이 없는 것이 정상
            reply = None
        
        # (header, command)가 같으면 마지막 긍정 응답으로 덮어씀
        key = (header, command)
        if key in step_map and tx.positive:
            # 긍정 응답이면 덮어씀
            step_map[key]["reply"] = reply
            step_map[key]["tMs"] = getattr(tx, "response_t_ms", None) or i * 100
        elif key not in step_map:
            # 처음 나온 명령
            step_map[key] = {
                "id": len(step_map) + 1,
                "command": command,
                "header": header,
                "reply": reply,
                "optional": False,
                "probe": False,
                "bus": "can",  # load_trace는 CAN 버스 데이터를 파싱
                "tMs": getattr(tx, "response_t_ms", None) or i * 100,
            }
    
    # 순서를 유지하기 위해 id 순으로 정렬
    steps = sorted(step_map.values(), key=lambda x: x["id"])
    
    return steps


def process_upload(
    actor: User,
    file: FileStorage,
    car_no: str | None = None,
    car: dict | None = None,
    device: str = "파일 업로드"
) -> int:
    """
    업로드 파일을 처리하고 스캔 결과를 생성합니다.
    
    Args:
        actor: 업로드 사용자
        file: 업로드 파일
        car_no: 차량번호 (선택)
        car: 차종 정보 (선택)
        device: 장비명
    
    Returns:
        생성된 Scan ID
    
    Raises:
        UploadError: 파일 처리 오류
        ServiceError: 스캔 생성 오류
    """
    # 1. 파일 검증
    validate_upload(file)
    
    # 2. 파일 읽기
    content = file.read()
    filename = file.filename or "unknown.txt"
    
    # 3. Trace 파싱
    try:
        trace_text = parse_uploaded_trace(content, filename)
    except UploadError:
        raise
    except Exception as exc:
        raise UploadError(f"파일 처리 중 오류가 발생했습니다: {exc}")
    
    # 4. 스캔 스텝으로 변환
    try:
        steps = convert_to_scan_steps(trace_text)
    except Exception as exc:
        raise UploadError(f"스캔 데이터 변환 실패: {exc}")
    
    if not steps:
        raise UploadError("유효한 스캔 데이터가 없습니다.")
    
    # 5. run_scan 호출
    car_no = normalize_car_no(car_no)
    car = normalize_dto(car) if car else {}
    
    try:
        scan = run_scan(
            actor,
            car_no=car_no or "파일업로드",
            car=car,
            steps=steps,
            transport="file",
            device=f"{device} ({filename})",
            source="upload"
        )
    except ServiceError:
        raise
    except Exception as exc:
        current_app.logger.exception("업로드 파일 스캔 생성 실패")
        raise UploadError(f"스캔 생성 중 오류가 발생했습니다: {exc}")
    
    # 6. 원본 파일은 저장하지 않음 (run_scan이 이미 처리된 텍스트를 저장함)
    current_app.logger.info(f"Upload scan created: {scan.id} from {filename}")
    
    return scan.id
