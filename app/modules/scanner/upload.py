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
        # 간단한 형식 체크: CAN ID나 일반적인 로그 패턴이 있는지
        if ("7E" not in text.upper() and "0x" not in text.lower() and 
            "ID" not in text and "CAN" not in text.upper()):
            raise UploadError(f"올바른 CAN 로그 형식이 아닙니다: {exc}")
        # 형식은 맞는 것 같지만 파싱 실패
        raise UploadError(f"CAN 로그를 파싱하지 못했습니다: {exc}")
    
    # 파싱 성공했지만 유효한 프레임이 없음
    if not trace.frames:
        raise UploadError("유효한 CAN 로그 프레임이 없습니다.")
    
    # Tesla broadcast는 UDS transactions 없이 frames만 있음
    # load_trace가 성공하면 유효한 데이터로 간주
    if not trace.transactions:
        try:
            current_app.logger.warning("No UDS transactions found; may be broadcast-only (e.g. Tesla)")
        except RuntimeError:
            pass  # No app context in tests
    
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
    
    # Tesla broadcast 등 transactions가 없으면 frames를 간단한 observation으로 변환
    if not trace.transactions and trace.frames:
        steps = []
        for i, frame in enumerate(trace.frames[:100]):  # 최대 100개
            steps.append({
                "index": i,
                "time_ms": frame.time_ms if hasattr(frame, 'time_ms') else i * 100,
                "direction": "rx",
                "data": f"{frame.can_id:03X} {frame.data.hex().upper()}",
                "header": f"{frame.can_id:03X}",
                "command": "",
                "reply": frame.data.hex().upper()
            })
        return steps
    
    # (header, command) → step 매핑. 마지막 긍정 응답만 유지
    # 브로드캐스트도 (ecu_physical_id, command)로 중복 제거
    step_map: dict[tuple[str | None, str], dict] = {}
    broadcast_map: dict[tuple[str, str], dict] = {}  # 브로드캐스트 중복 제거용
    
    for i, tx in enumerate(trace.transactions):
        # 요청 데이터 (8바이트 초과도 허용)
        request_data = tx.request.hex().upper() if tx.request else ""
        command = " ".join(request_data[i:i+2] for i in range(0, len(request_data), 2)) if request_data else ""
        
        # 세션 제어(10 xx) / Tester Present(3E xx)는 ECU당 1건만
        # 첫 2자리가 10 또는 3E인지 확인
        is_session_or_tester = False
        if len(request_data) >= 2:
            service = request_data[:2]
            is_session_or_tester = service in ('10', '3E')
        
        # 브로드캐스트(7DF) 요청인 경우 ecu_physical_id로 별도 step 생성
        if tx.ecu_physical_id is not None:
            header = f"{tx.ecu_physical_id:03X}"
            
            # 세션 제어/Tester Present는 ECU당 1건만: 키를 service만으로
            if is_session_or_tester:
                key = (header, request_data[:2])  # ECU + service
            else:
                key = (header, command)
            
            reply = None
            if tx.response and tx.response_id:
                hex_str = tx.response.hex().upper()
                resp_addr = f"{tx.response_id:03X}"
                data = " ".join(hex_str[i:i+2] for i in range(0, len(hex_str), 2))
                reply = f"{resp_addr} {data}"
            
            # 키가 없거나, 긍정 응답이면 갱신
            if key not in broadcast_map or tx.positive:
                broadcast_map[key] = {
                    "command": command,
                    "header": header,
                    "reply": reply,
                    "optional": False,
                    "probe": False,
                    "bus": "can",
                    "tMs": getattr(tx, "response_t_ms", None) or i * 100,
                }
            
            # extra_responders도 동일하게 처리
            for extra_id in tx.extra_responders:
                if 0x500 <= extra_id <= 0x7FF:
                    extra_header = f"{extra_id:03X}"
                    if is_session_or_tester:
                        extra_key = (extra_header, request_data[:2])
                    else:
                        extra_key = (extra_header, command)
                    
                    if extra_key not in broadcast_map or tx.positive:
                        broadcast_map[extra_key] = {
                            "command": command,
                            "header": extra_header,
                            "reply": reply,
                            "optional": False,
                            "probe": False,
                            "bus": "can",
                            "tMs": getattr(tx, "response_t_ms", None) or i * 100,
                        }
            continue
        
        # 일반 요청 처리
        header = f"{tx.request_id:03X}"
        command = " ".join(request_data[i:i+2] for i in range(0, len(request_data), 2)) if request_data else ""
        
        # 응답 처리 (ELM 형식: 응답 주소 + 데이터, 2자리마다 공백)
        reply = None
        if tx.response and tx.response_id:
            hex_str = tx.response.hex().upper()
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
        
        # 세션 제어/Tester Present는 ECU당 1건만
        if is_session_or_tester:
            key = (header, request_data[:2])
        else:
            key = (header, command)
        
        if key not in step_map:
            # 처음 나온 명령
            step_map[key] = {
                "command": command,
                "header": header,
                "reply": reply,
                "optional": False,
                "probe": False,
                "bus": "can",
                "tMs": getattr(tx, "response_t_ms", None) or i * 100,
            }
        elif tx.positive:
            # 긍정 응답이면 덮어씀
            step_map[key]["reply"] = reply
            step_map[key]["tMs"] = getattr(tx, "response_t_ms", None) or i * 100
    
    # broadcast_map과 step_map을 합쳐서 ID 부여
    all_steps = list(step_map.values()) + list(broadcast_map.values())
    for i, step in enumerate(all_steps, start=1):
        step["id"] = i
    
    return all_steps


def process_upload(
    actor: User | int,
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
    
    # 4. Tesla 감지 (broadcast-only 데이터)
    from app.modules.canlab.engine.decode import load_trace
    from app.modules.tesla import detect as tesla_detect
    
    trace = load_trace(trace_text)
    
    # UDS transactions가 없고 Tesla 시그니처가 있으면 Tesla 경로
    is_tesla = False
    extracted_vin = None
    if not trace.transactions and trace.frames:
        # frames를 (timestamp, can_id, data) 튜플로 변환
        frame_tuples = [(f.t_ms / 1000.0, f.can_id, f.data) for f in trace.frames]
        is_tesla = tesla_detect.is_tesla(frame_tuples, vin=None)
        
        if is_tesla:
            extracted_vin = tesla_detect.extract_vin_from_frames(frame_tuples)
            if extracted_vin:
                current_app.logger.info(f"Tesla vehicle detected, VIN: {extracted_vin}")
    
    # 5. Tesla 경로: 디코딩 후 결과 저장
    if is_tesla:
        return _process_tesla_upload(
            actor=actor,
            trace=trace,
            car_no=car_no,
            vin=extracted_vin,
            device=device,
            filename=filename
        )
    
    # 6. 일반 UDS 경로: 스캔 스텝으로 변환
    try:
        steps = convert_to_scan_steps(trace_text)
    except Exception as exc:
        raise UploadError(f"스캔 데이터 변환 실패: {exc}")
    
    if not steps:
        raise UploadError("유효한 스캔 데이터가 없습니다.")
    
    # 7. run_scan 호출
    car_no = normalize_car_no(car_no)
    car = normalize_dto(car) if car else {}
    
    # car_no가 있지만 car 정보가 없으면 조회
    if car_no and not car:
        from app.modules.scans import car_info
        try:
            dto, _ = car_info.lookup(actor, car_no)
            car = car_info.normalize_dto(dto)
        except Exception:
            # 조회 실패해도 업로드는 계속 진행
            pass
    
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
    
    # 8. 원본 파일은 저장하지 않음 (run_scan이 이미 처리된 텍스트를 저장함)
    current_app.logger.info(f"Upload scan created: {scan.id} from {filename}")
    
    return scan.id


def _process_tesla_upload(
    actor: User | int,
    trace,
    car_no: str | None,
    vin: str | None,
    device: str,
    filename: str
) -> int:
    """
    Tesla 업로드 처리.
    
    Args:
        actor: 업로드 사용자 ID
        trace: 파싱된 Trace 객체
        car_no: 차량번호
        vin: 추출된 VIN
        device: 장비명
        filename: 파일명
    
    Returns:
        생성된 Scan ID
    """
    from app.modules.scans.models import Scan
    from app.modules.tesla import detect as tesla_detect
    from app.modules.tesla import decode as tesla_decode
    from app.modules.tesla import soh as tesla_soh
    
    # actor가 int면 그대로, 객체면 id 추출
    actor_id = actor if isinstance(actor, int) else actor.id
    
    # 1. 차량 정보
    car_no = normalize_car_no(car_no) if car_no else "Tesla업로드"
    
    # VIN으로 모델 감지
    frame_tuples = [(f.t_ms / 1000.0, f.can_id, f.data) for f in trace.frames]
    model = tesla_detect.detect_model(frame_tuples, vin)
    vin_info = tesla_detect.decode_vin(vin) if vin else {}
    
    manufacturer = "Tesla"
    model_name = model or vin_info.get('model', 'Unknown')
    year = vin_info.get('year')
    
    # 2. CAN 프레임 디코딩
    frames_by_id = {}
    for frame in trace.frames:
        if frame.can_id not in frames_by_id:
            frames_by_id[frame.can_id] = []
        frames_by_id[frame.can_id].append((frame.t_ms / 1000.0, frame.data))
    
    decoded = {}
    
    # 0x352: 에너지 상태
    if 0x352 in frames_by_id:
        decoded['energy'] = tesla_decode.decode_0x352_energy(frames_by_id[0x352])
    
    # 0x292: SOC
    if 0x292 in frames_by_id:
        decoded['soc'] = tesla_decode.decode_0x292_soc(frames_by_id[0x292])
    
    # 0x401: 브릭 전압
    if 0x401 in frames_by_id:
        decoded['bricks'] = tesla_decode.decode_0x401_brick_voltages(frames_by_id[0x401])
    
    # 0x332: 온도/전압 요약
    if 0x332 in frames_by_id:
        decoded['summary'] = tesla_decode.decode_0x332_summary(frames_by_id[0x332])
    
    # 0x132: 팩 전압/전류
    if 0x132 in frames_by_id:
        decoded['pack_vi'] = tesla_decode.decode_0x132_pack_vi(frames_by_id[0x132])
    
    # 0x2B4: LV/DC-DC
    if 0x2B4 in frames_by_id:
        decoded['lv_dcdc'] = tesla_decode.decode_0x2B4_lv_dcdc(frames_by_id[0x2B4])
    
    # 0x3D2: 누적 충방전
    if 0x3D2 in frames_by_id:
        decoded['cumulative'] = tesla_decode.decode_0x3D2_cumulative_energy(frames_by_id[0x3D2])
    
    # 3. SOH 계산
    soh_result = None
    current_full = decoded.get('energy', {}).get('nominal_full_pack_energy')
    bol_energy = decoded.get('soc', {}).get('bol_energy')
    
    if current_full:
        soh_result = tesla_soh.calculate_soh(
            current_nominal_full=current_full,
            manufacturer=manufacturer,
            model=model_name,
            year=year,
            pack_code='Long Range' if current_full > 60 else None,
            bol_energy=bol_energy
        )
        
        # 교차 검증
        soc_ave = decoded.get('soc', {}).get('soc_ave')
        nom_rem = decoded.get('energy', {}).get('nominal_energy_remaining')
        if soc_ave and nom_rem:
            soh_result = tesla_soh.cross_check_soh(soh_result, soc_ave, nom_rem)
    
    # 4. Scan 생성 (run_scan 패턴과 동일하게)
    tesla_data = {
        'source': 'tesla_upload',
        'vin': vin,
        'manufacturer': manufacturer,
        'model': model_name,
        'year': year,
        'decoded': decoded,
        'soh': soh_result,
        'status': '완료',
        'transport': 'file',
        'device': f"{device} ({filename})",
    }
    
    scan = Scan(
        type="ev",  # Tesla는 EV
        type_source="tesla_upload",
        device_type="file",
        device_uid=f"{device} ({filename})",
        tester_id=actor_id,
        car_no=car_no,
        car_vin=vin or "미확인",
        scan_vin=vin,
        car_maker=manufacturer,
        car_model=model_name or "Model 3",  # 기본값
        car_year=year,
        bms_data=tesla_data  # Tesla 데이터를 bms_data에 저장 (기존 필드 재사용)
    )
    
    # 판정보류 (community 출처 또는 기준 없음)
    if soh_result and not soh_result.get('soh_available'):
        tesla_data['judgment'] = '판정보류'
        tesla_data['judgment_reason'] = soh_result.get('calculation_note', 'SOH 기준 미확보')
    
    db.session.add(scan)
    db.session.commit()
    
    current_app.logger.info(f"Tesla upload scan created: {scan.id} from {filename}")
    
    return scan.id
