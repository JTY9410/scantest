"""Service functions for vehicle definitions and analysis."""
from typing import Any

from sqlalchemy import and_, or_

from app.extensions import db
from app.modules.definitions.models import (
    DbcMessage,
    DbcSignal,
    DiagnosticCommand,
    ScanObservation,
    VehicleDefinition,
)
from app.modules.scans.models import Scan


def find_applicable_definitions(scan: Scan) -> dict[str, Any]:
    """스캔에 적용 가능한 정의 찾기."""
    result = {
        'dbc_signals': [],
        'diagnostic_commands': [],
    }
    
    maker = scan.car_maker
    model = scan.car_model
    year = scan.car_year
    
    # Vehicle definitions 검색
    query = db.session.query(VehicleDefinition)
    
    if maker:
        query = query.filter(
            or_(
                VehicleDefinition.maker == maker,
                VehicleDefinition.maker.is_(None)
            )
        )
    
    if model:
        query = query.filter(
            or_(
                VehicleDefinition.model == model,
                VehicleDefinition.model.is_(None)
            )
        )
    
    if year:
        query = query.filter(
            or_(
                VehicleDefinition.year_from.is_(None),
                VehicleDefinition.year_from <= year
            )
        ).filter(
            or_(
                VehicleDefinition.year_to.is_(None),
                VehicleDefinition.year_to >= year
            )
        )
    
    vehicle_defs = query.all()
    source_ids = [vd.source_id for vd in vehicle_defs]
    
    # DBC signals 검색
    if source_ids:
        messages = db.session.query(DbcMessage).filter(
            DbcMessage.source_id.in_(source_ids)
        ).all()
        
        for msg in messages:
            signals = db.session.query(DbcSignal).filter_by(message_id=msg.id).all()
            for sig in signals:
                result['dbc_signals'].append({
                    'can_id': msg.can_id,
                    'message_name': msg.message_name,
                    'signal': sig,
                })
    
    # Diagnostic commands 검색
    cmd_query = db.session.query(DiagnosticCommand)
    
    if maker:
        cmd_query = cmd_query.filter(
            or_(
                DiagnosticCommand.maker == maker,
                DiagnosticCommand.maker.is_(None)
            )
        )
    
    if model:
        cmd_query = cmd_query.filter(
            or_(
                DiagnosticCommand.model == model,
                DiagnosticCommand.model.is_(None)
            )
        )
    
    if year:
        cmd_query = cmd_query.filter(
            or_(
                DiagnosticCommand.year_from.is_(None),
                DiagnosticCommand.year_from <= year
            )
        ).filter(
            or_(
                DiagnosticCommand.year_to.is_(None),
                DiagnosticCommand.year_to >= year
            )
        )
    
    result['diagnostic_commands'] = cmd_query.all()
    
    return result


def decode_signal(signal: DbcSignal, raw_bytes: bytes) -> float | None:
    """DBC signal 디코딩."""
    try:
        # 바이트에서 비트 추출
        start_byte = signal.start_bit // 8
        bit_offset = signal.start_bit % 8
        
        # 간단한 구현 (little endian, unsigned만)
        value = 0
        for i in range((signal.bit_length + 7) // 8):
            if start_byte + i < len(raw_bytes):
                value |= raw_bytes[start_byte + i] << (i * 8)
        
        # 비트 마스크 적용
        value >>= bit_offset
        value &= (1 << signal.bit_length) - 1
        
        # signed 처리
        if signal.value_type == 'signed' and (value & (1 << (signal.bit_length - 1))):
            value -= (1 << signal.bit_length)
        
        # factor/offset 적용
        return value * signal.factor + signal.offset
    except Exception:
        return None


def decode_diagnostic_response(command: DiagnosticCommand, response_bytes: bytes) -> Any:
    """진단 명령 응답 디코딩."""
    from app.modules.definitions.formula_eval import evaluate_formula
    
    try:
        if command.formula:
            # 응답에서 값 추출
            if command.response_start_byte is not None:
                start = command.response_start_byte
                length = command.response_length or 1
                
                if start + length <= len(response_bytes):
                    raw_value = int.from_bytes(
                        response_bytes[start:start+length],
                        byteorder='big'
                    )
                    
                    # 안전한 formula 평가
                    try:
                        result = evaluate_formula(command.formula, {"value": raw_value})
                        return result
                    except ValueError:
                        # formula 평가 실패 시 raw 값 반환
                        return raw_value
            
            return None
        else:
            # formula가 없으면 raw bytes 반환
            return response_bytes.hex()
    except Exception:
        return None


def record_observation(scan_id: int, definition_type: str, definition_id: int,
                      applied: bool, success: bool | None, 
                      raw_request: str | None = None,
                      raw_response: str | None = None,
                      decoded_value: Any = None,
                      mismatch_reason: str | None = None):
    """스캔 관찰 결과 기록."""
    from app.core.time import utcnow
    
    obs = ScanObservation(
        scan_id=scan_id,
        definition_type=definition_type,
        definition_id=definition_id,
        applied=applied,
        success=success,
        raw_request=raw_request,
        raw_response=raw_response,
        decoded_value=str(decoded_value) if decoded_value is not None else None,
        mismatch_reason=mismatch_reason,
        observed_at=utcnow(),
    )
    db.session.add(obs)
    db.session.commit()


def update_command_stats(command_id: int, success: bool):
    """명령어 통계 업데이트."""
    cmd = db.session.query(DiagnosticCommand).get(command_id)
    if cmd:
        cmd.verification_count += 1
        if success:
            cmd.success_count += 1
        else:
            cmd.failure_count += 1
        
        # 자동 검증 승격: 성공률이 80% 이상이고 10회 이상 시도
        if cmd.verification_count >= 10:
            success_rate = cmd.success_count / cmd.verification_count
            if success_rate >= 0.8 and cmd.verification_status == 'needs_verification':
                cmd.verification_status = 'verified'
            elif success_rate < 0.2 and cmd.verification_status == 'needs_verification':
                cmd.verification_status = 'failed'
        
        db.session.commit()


def get_learning_summary(command_id: int) -> dict[str, Any]:
    """특정 명령어의 학습 요약."""
    cmd = db.session.query(DiagnosticCommand).get(command_id)
    if not cmd:
        return {}
    
    observations = db.session.query(ScanObservation).filter_by(
        definition_type='diagnostic',
        definition_id=command_id
    ).all()
    
    return {
        'command': cmd,
        'total_observations': len(observations),
        'successful': sum(1 for o in observations if o.success),
        'failed': sum(1 for o in observations if o.success is False),
        'verification_status': cmd.verification_status,
        'success_rate': cmd.success_count / cmd.verification_count if cmd.verification_count > 0 else 0,
    }
