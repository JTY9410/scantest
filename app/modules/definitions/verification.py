"""Verification metrics 자동 업데이트

분석 저장 시 DiagnosticCommand의 검증 상태를 자동 갱신.

규칙 (기존):
- 10회 이상 시도, 성공률 80% 이상: verified
- 성공률 20% 미만: failed
- 그 외: experimental
"""
from sqlalchemy import func

from app.extensions import db
from app.modules.definitions.models import DiagnosticCommand, ScanObservation


def update_verification_metrics(scan_id: int) -> dict[str, int]:
    """스캔의 관찰 결과로 command 검증 상태 업데이트
    
    Args:
        scan_id: 스캔 ID
    
    Returns:
        {'promoted': ..., 'demoted': ..., 'unchanged': ...}
    """
    # 이 스캔에서 사용된 command들 조회
    observations = db.session.query(ScanObservation).filter_by(scan_id=scan_id).all()
    
    command_ids = set()
    for obs in observations:
        if obs.definition_type == 'diagnostic' and obs.definition_id > 0:
            command_ids.add(obs.definition_id)
    
    stats = {'promoted': 0, 'demoted': 0, 'unchanged': 0}
    
    for command_id in command_ids:
        command = db.session.query(DiagnosticCommand).get(command_id)
        if not command:
            continue
        
        # 모든 관찰 통계 계산
        all_obs = db.session.query(ScanObservation).filter_by(
            definition_type='diagnostic',
            definition_id=command_id
        ).all()
        
        total_tries = len(all_obs)
        successful = sum(1 for o in all_obs if o.success)
        
        if total_tries == 0:
            continue
        
        success_rate = successful / total_tries
        
        # 기존 상태
        old_status = command.verification_status
        new_status = old_status
        
        # 상태 결정
        if total_tries >= 10 and success_rate >= 0.8:
            new_status = 'verified'
        elif success_rate < 0.2:
            new_status = 'failed'
        else:
            new_status = 'experimental'
        
        # 업데이트
        if old_status != new_status:
            command.verification_status = new_status
            if new_status == 'verified':
                stats['promoted'] += 1
            elif new_status == 'failed':
                stats['demoted'] += 1
            else:
                stats['unchanged'] += 1
        else:
            stats['unchanged'] += 1
        
        # verification_metrics 업데이트
        if command.verification_metrics is None:
            command.verification_metrics = {}
        
        command.verification_metrics.update({
            'total_tries': total_tries,
            'successful_tries': successful,
            'success_rate': round(success_rate, 3),
            'last_updated': func.now(),
        })
        
        db.session.add(command)
    
    return stats
