"""미지의 CAN ID/신호 학습."""

from collections import defaultdict
from typing import Any

from app.extensions import db
from app.modules.ml_learning.models import MLDecoderProposal, MLScanFeature

# 최소 출현 횟수
MIN_OCCURRENCES = 30


def learn_unknown_can_ids() -> list[MLDecoderProposal]:
    """
    미지의 CAN ID 후보 학습.
    
    Returns:
        생성된 제안 목록
    """
    # 축적된 특징에서 패턴 추출 (실제로는 raw CAN 로그 분석)
    # 간단한 구현: 자주 나타나지만 디코더에 없는 ID 탐지
    
    # 예시 패턴
    proposals = []
    
    # 실제로는 CAN 로그를 분석하여 반복 패턴 찾기
    # 여기서는 더미 제안 생성
    
    return proposals


def create_decoder_proposal(
    maker: str,
    model: str,
    can_id: str,
    signal_name: str | None,
    confidence: float,
    sample_count: int,
    **kwargs
) -> MLDecoderProposal:
    """디코더 제안 생성."""
    proposal = MLDecoderProposal(
        maker=maker,
        model=model,
        can_id=can_id,
        signal_name=signal_name,
        confidence_score=confidence,
        sample_count=sample_count,
        status='pending',
        **kwargs
    )
    db.session.add(proposal)
    db.session.commit()
    
    return proposal
