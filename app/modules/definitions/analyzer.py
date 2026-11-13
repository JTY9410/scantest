"""Scan analyzer using vehicle definitions with real CAN/OBD-II decoding."""
from typing import Any
from collections import defaultdict
import csv
from pathlib import Path

from app.extensions import db
from app.modules.definitions.models import (
    DiagnosticCommand,
    VehicleDefinition,
    DbcMessage,
    DbcSignal,
    ScanObservation,
)
from app.modules.definitions.decoder import (
    parse_can_frame,
    reassemble_isotp_frames,
    decode_mode01_response,
    decode_mode09_response,
    decode_uds22_response,
    decode_kwp21_response,
    apply_formula,
    extract_bits,
)
from app.modules.scans.models import Scan
from app.core.formulas import safe_eval


def analyze_scan_with_definitions(scan: Scan) -> dict[str, Any]:
    """스캔에 정의 적용하여 WESCAN 스타일 결과 생성 (실제 디코딩 포함).
    
    Args:
        scan: 분석할 스캔
    
    Returns:
        분석 결과 딕셔너리 (battery, powertrain, dtcs, definitions_applied 등)
    """
    result = {
        'vehicle': {
            'maker': scan.car_maker,
            'model': scan.car_model,
            'year': scan.car_year,
            'vin': scan.car_vin,
        },
        'battery': {},
        'powertrain': {},
        'vehicle_info': {},
        'dtcs': [],
        'definitions_applied': {
            'total_commands': 0,
            'verified_commands': 0,
            'successful_decodes': 0,
            'failed_decodes': 0,
            'frames_processed': 0,
            'isotp_reassembled': 0,
        }
    }
    
    # raw 데이터에서 CAN 프레임 추출
    can_frames = []
    if scan.raw and isinstance(scan.raw, dict):
        can_frames = scan.raw.get('can_frames', [])
    
    if not can_frames:
        return result
    
    result['definitions_applied']['frames_processed'] = len(can_frames)
    
    # 1. 요청/응답 프레임 그룹화 (타임스탬프 기준)
    request_response_groups = group_request_responses(can_frames)
    
    # 2. ISO-TP 재조립
    for group in request_response_groups:
        reassembled = reassemble_isotp_frames(group['responses'])
        if reassembled:
            result['definitions_applied']['isotp_reassembled'] += len(reassembled)
            group['reassembled'] = reassembled
    
    # 3. 차량 정의 조회 (제조사 매칭)
    # DiagnosticCommand와 VehicleDefinition은 vehicle_definition_id FK로 연결
    vehicle_defs = db.session.query(VehicleDefinition).filter_by(
        maker=scan.car_maker
    ).all()
    
    vehicle_def_ids = [vd.id for vd in vehicle_defs]
    
    if vehicle_def_ids:
        commands = db.session.query(DiagnosticCommand).filter(
            DiagnosticCommand.vehicle_definition_id.in_(vehicle_def_ids)
        ).all()
    else:
        commands = []
    
    result['definitions_applied']['total_commands'] = len(commands)
    
    # 4. 각 그룹 디코딩
    for group in request_response_groups:
        if 'reassembled' not in group:
            continue
        
        request_data = parse_can_frame(group['request']['data'])
        
        # Mode 판별
        if len(request_data) >= 2:
            mode = request_data[1]
            pid_or_did = request_data[2] if len(request_data) >= 3 else None
            
            for ecu_id, response_bytes in group['reassembled'].items():
                decoded_values = {}
                
                # Mode 01: 현재 데이터
                if mode == 0x01:
                    decoded_values = decode_mode01_response(response_bytes)
                    if decoded_values:
                        result['vehicle_info'].update(decoded_values)
                        result['definitions_applied']['successful_decodes'] += 1
                        
                        # ScanObservation 기록
                        for key, value in decoded_values.items():
                            obs = ScanObservation(
                                scan_id=scan.id,
                                definition_type='diagnostic',
                                definition_id=0,  # 표준 Mode 01 (정의 없음)
                                applied=True,
                                success=True,
                                raw_request=group['request']['data'],
                                raw_response=response_bytes.hex(),
                                decoded_value=str(value),
                            )
                            db.session.add(obs)
                
                # Mode 09: 차량 정보
                elif mode == 0x09:
                    decoded_values = decode_mode09_response(response_bytes)
                    if decoded_values:
                        result['vehicle_info'].update(decoded_values)
                        result['definitions_applied']['successful_decodes'] += 1
                        
                        obs = ScanObservation(
                            scan_id=scan.id,
                            definition_type='diagnostic',
                            definition_id=0,
                            applied=True,
                            success=True,
                            raw_request=group['request']['data'],
                            raw_response=response_bytes.hex(),
                            decoded_value=str(decoded_values),
                        )
                        db.session.add(obs)
                
                # UDS 0x22: ReadDataByIdentifier
                elif mode == 0x22 and pid_or_did is not None:
                    did = (pid_or_did << 8) | request_data[3] if len(request_data) >= 4 else 0
                    decoded_values = decode_uds22_response(response_bytes, did)
                    if decoded_values:
                        # BMS 데이터는 battery로
                        for key, value in decoded_values.items():
                            if 'bms' in key or 'cell' in key or 'soc' in key or 'soh' in key:
                                result['battery'][key] = value
                            else:
                                result['vehicle_info'][key] = value
                        
                        result['definitions_applied']['successful_decodes'] += 1
                        
                        obs = ScanObservation(
                            scan_id=scan.id,
                            definition_type='diagnostic',
                            definition_id=0,
                            applied=True,
                            success=True,
                            raw_request=group['request']['data'],
                            raw_response=response_bytes.hex(),
                            decoded_value=str(decoded_values),
                        )
                        db.session.add(obs)
                
                # KWP2000 0x21: ReadDataByLocalId
                elif mode == 0x21 and pid_or_did is not None:
                    decoded_values = decode_kwp21_response(response_bytes, pid_or_did)
                    if decoded_values:
                        # BMS 데이터는 battery로
                        for key, value in decoded_values.items():
                            if 'bms' in key or 'cell' in key or 'soc' in key or 'soh' in key:
                                result['battery'][key] = value
                            else:
                                result['vehicle_info'][key] = value
                        
                        result['definitions_applied']['successful_decodes'] += 1
                        
                        obs = ScanObservation(
                            scan_id=scan.id,
                            definition_type='diagnostic',
                            definition_id=0,
                            applied=True,
                            success=True,
                            raw_request=group['request']['data'],
                            raw_response=response_bytes.hex(),
                            decoded_value=str(decoded_values),
                        )
                        db.session.add(obs)
    
    # 5. DTC (기존 로직)
    result['dtcs'] = [
        {
            'code': sc.code.code,
            'description': sc.code.desc,
            'unit_name': sc.code.unit_name,
        }
        for sc in scan.scan_codes
    ] if scan.scan_codes else []
    
    db.session.commit()
    
    return result


def group_request_responses(can_frames: list[dict], window_ms: float = 500) -> list[dict]:
    """CAN 프레임을 요청-응답 그룹으로 묶기
    
    7DF (broadcast) → 7E8-7EF (ECU responses)
    타임스탬프 윈도우 내에서 매칭
    
    Returns:
        [{'request': frame, 'responses': [frames]}, ...]
    """
    groups = []
    
    # 요청 프레임 (7DF functional, 7E0-7E7 physical)
    REQUEST_IDS = {'000007DF', '000007E0', '000007E1', '000007E2', '000007E3',
                   '000007E4', '000007E5', '000007E6', '000007E7'}
    
    # 응답 프레임 (7E8-7EF)
    RESPONSE_IDS = {'000007E8', '000007E9', '000007EA', '000007EB',
                    '000007EC', '000007ED', '000007EE', '000007EF',
                    '0000074C', '0000074D', '0000074E', '0000074F'}  # Alternative ECU IDs
    
    i = 0
    while i < len(can_frames):
        frame = can_frames[i]
        can_id = frame.get('can_id', '').upper()
        
        # 요청 프레임인가?
        if can_id in REQUEST_IDS:
            request_ts = float(frame.get('timestamp', 0))
            responses = []
            
            # 윈도우 내의 응답 수집
            j = i + 1
            while j < len(can_frames):
                resp_frame = can_frames[j]
                resp_id = resp_frame.get('can_id', '').upper()
                resp_ts = float(resp_frame.get('timestamp', 0))
                
                if resp_ts - request_ts > window_ms / 1000:
                    break
                
                if resp_id in RESPONSE_IDS:
                    responses.append(resp_frame)
                
                j += 1
            
            if responses:
                groups.append({
                    'request': frame,
                    'responses': responses
                })
        
        i += 1
    
    return groups


def load_csv_and_analyze(csv_path: str | Path, scan: Scan) -> dict[str, Any]:
    """CSV 파일을 로드하고 스캔 분석 수행
    
    Args:
        csv_path: CSV 파일 경로
        scan: 스캔 객체 (can_frames를 raw에 저장)
    
    Returns:
        분석 결과
    """
    csv_path = Path(csv_path)
    
    can_frames = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            can_frames.append({
                'timestamp': row['Timestamp'],
                'can_id': row['CAN_ID'],
                'data': row['Data'],
            })
    
    # scan.raw에 저장
    scan.raw = {'can_frames': can_frames}
    db.session.commit()
    
    # 분석 실행
    return analyze_scan_with_definitions(scan)
