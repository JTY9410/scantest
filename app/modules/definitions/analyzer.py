"""Scan analyzer using vehicle definitions."""
from typing import Any

from app.extensions import db
from app.modules.definitions.models import ScanObservation
from app.modules.definitions.service import (
    decode_diagnostic_response,
    decode_signal,
    find_applicable_definitions,
    record_observation,
    update_command_stats,
)
from app.modules.scans.models import Scan


def analyze_scan_with_definitions(scan: Scan) -> dict[str, Any]:
    """스캔에 정의 적용하여 WESCAN 스타일 결과 생성.
    
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
        'dtcs': [],
        'definitions_applied': {
            'total_commands': 0,
            'verified_commands': 0,
            'successful_decodes': 0,
            'failed_decodes': 0,
        }
    }
    
    # 적용 가능한 정의 검색
    definitions = find_applicable_definitions(scan)
    
    result['definitions_applied']['total_commands'] = len(definitions['diagnostic_commands'])
    result['definitions_applied']['verified_commands'] = sum(
        1 for c in definitions['diagnostic_commands'] if c.verification_status == 'verified'
    )
    
    # raw 데이터에서 응답 추출 (scan.raw는 dict 형태)
    if scan.raw and isinstance(scan.raw, dict):
        responses = scan.raw.get('responses', {})
        
        # 각 명령에 대해 응답 디코딩 시도
        for cmd in definitions['diagnostic_commands']:
            command_key = f"{cmd.ecu_address}_{cmd.command_bytes}".replace(' ', '_')
            
            if command_key in responses or cmd.command_bytes in responses:
                response_hex = responses.get(command_key) or responses.get(cmd.command_bytes)
                
                if response_hex:
                    try:
                        # hex string을 bytes로 변환
                        if isinstance(response_hex, str):
                            response_bytes = bytes.fromhex(response_hex.replace(' ', ''))
                        else:
                            response_bytes = response_hex
                        
                        # 디코딩 시도
                        decoded_value = decode_diagnostic_response(cmd, response_bytes)
                        
                        if decoded_value is not None:
                            # 성공
                            result['definitions_applied']['successful_decodes'] += 1
                            
                            # 배터리/파워트레인 분류
                            label_lower = cmd.label.lower()
                            if any(kw in label_lower for kw in ['battery', 'soc', 'soh', 'cell', 'voltage', 'bms']):
                                result['battery'][cmd.label] = {
                                    'value': decoded_value,
                                    'unit': cmd.unit,
                                    'verified': cmd.verification_status == 'verified'
                                }
                            elif any(kw in label_lower for kw in ['motor', 'speed', 'rpm', 'power', 'torque']):
                                result['powertrain'][cmd.label] = {
                                    'value': decoded_value,
                                    'unit': cmd.unit,
                                    'verified': cmd.verification_status == 'verified'
                                }
                            
                            # 관찰 기록
                            record_observation(
                                scan_id=scan.id,
                                definition_type='diagnostic',
                                definition_id=cmd.id,
                                applied=True,
                                success=True,
                                raw_request=cmd.command_bytes,
                                raw_response=response_hex,
                                decoded_value=decoded_value,
                            )
                            
                            # 통계 업데이트
                            update_command_stats(cmd.id, success=True)
                        else:
                            # 디코딩 실패
                            result['definitions_applied']['failed_decodes'] += 1
                            
                            record_observation(
                                scan_id=scan.id,
                                definition_type='diagnostic',
                                definition_id=cmd.id,
                                applied=True,
                                success=False,
                                raw_request=cmd.command_bytes,
                                raw_response=response_hex,
                                mismatch_reason='Decoding returned None'
                            )
                            
                            update_command_stats(cmd.id, success=False)
                    
                    except Exception as e:
                        result['definitions_applied']['failed_decodes'] += 1
                        
                        record_observation(
                            scan_id=scan.id,
                            definition_type='diagnostic',
                            definition_id=cmd.id,
                            applied=True,
                            success=False,
                            raw_request=cmd.command_bytes,
                            raw_response=str(response_hex),
                            mismatch_reason=f'Exception: {e}'
                        )
                        
                        update_command_stats(cmd.id, success=False)
    
    # DTC (기존 로직 유지)
    result['dtcs'] = [
        {
            'code': sc.code.code,
            'description': sc.code.desc,
            'unit_name': sc.code.unit_name,
        }
        for sc in scan.scan_codes
    ] if scan.scan_codes else []
    
    return result
