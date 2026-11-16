"""ML learning models for continuous improvement."""

from datetime import datetime
from sqlalchemy import Index
from app.extensions import db


class MLScanFeature(db.Model):
    """익명화된 스캔 특징 (ML 학습용)."""
    
    __tablename__ = 'ml_scan_features'
    
    id = db.Column(db.Integer, primary_key=True)
    scan_id = db.Column(db.Integer, nullable=True, comment='익명화: NULL')
    
    # 차량 정보 (익명화)
    maker = db.Column(db.String(50), nullable=False, index=True)
    model = db.Column(db.String(100), nullable=False)
    year = db.Column(db.Integer, nullable=True)
    fuel_type = db.Column(db.String(20), nullable=True, index=True)
    
    # 진단 결과
    overall_judgment = db.Column(db.String(50), nullable=True)
    dtc_count = db.Column(db.Integer, nullable=False, default=0)
    significant_dtc_count = db.Column(db.Integer, nullable=False, default=0)
    
    # 신호 커버리지 (JSON: {signal_name: bool})
    signals_read = db.Column(db.JSON, nullable=True)
    
    # 디코딩된 값 (익명화, JSON)
    decoded_values = db.Column(db.JSON, nullable=True)
    
    # 측정불가 항목
    unmeasurable_items = db.Column(db.JSON, nullable=True)
    unmeasurable_count = db.Column(db.Integer, nullable=False, default=0)
    
    # 디코더 정보
    decoder_sources = db.Column(db.JSON, nullable=True, comment='사용된 디코더 출처')
    decoder_version = db.Column(db.String(50), nullable=True)
    
    # 앱/장치 정보
    device_type = db.Column(db.String(50), nullable=True)
    app_version = db.Column(db.String(50), nullable=True)
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        Index('ix_ml_features_maker_model_year', 'maker', 'model', 'year'),
    )
    
    def __repr__(self):
        return f'<MLScanFeature {self.id} {self.maker} {self.model} {self.fuel_type}>'


class MLModelRun(db.Model):
    """ML 모델 학습 실행 기록."""
    
    __tablename__ = 'ml_model_runs'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # 실행 정보
    run_type = db.Column(db.String(50), nullable=False, comment='scheduled/manual/event-triggered')
    trigger_reason = db.Column(db.String(200), nullable=True, comment='daily/N-rows/manual')
    
    # 데이터셋
    training_samples = db.Column(db.Integer, nullable=False)
    validation_samples = db.Column(db.Integer, nullable=False)
    test_samples = db.Column(db.Integer, nullable=False)
    
    # 모델 성능
    accuracy = db.Column(db.Float, nullable=True)
    precision = db.Column(db.Float, nullable=True)
    recall = db.Column(db.Float, nullable=True)
    f1_score = db.Column(db.Float, nullable=True)
    
    # 상세 메트릭 (JSON)
    detailed_metrics = db.Column(db.JSON, nullable=True)
    
    # 승진 여부
    promoted_to_active = db.Column(db.Boolean, nullable=False, default=False)
    promotion_reason = db.Column(db.Text, nullable=True)
    
    # 실행 상태
    status = db.Column(db.String(50), nullable=False, default='running', comment='running/completed/failed')
    error_message = db.Column(db.Text, nullable=True)
    
    # 실행 시간
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)
    
    def __repr__(self):
        return f'<MLModelRun {self.id} {self.status} promoted={self.promoted_to_active}>'


class MLActiveModel(db.Model):
    """현재 활성 ML 모델 (싱글톤)."""
    
    __tablename__ = 'ml_active_model'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # 모델 실행 참조
    model_run_id = db.Column(db.Integer, db.ForeignKey('ml_model_runs.id'), nullable=False)
    model_run = db.relationship('MLModelRun', backref='active_deployments')
    
    # 활성화 시간
    activated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    activated_by = db.Column(db.String(100), nullable=True, comment='system/admin-user-id')
    
    # 모델 파일 경로
    model_path = db.Column(db.String(500), nullable=True)
    
    def __repr__(self):
        return f'<MLActiveModel run_id={self.model_run_id}>'


class MLConsistencyScore(db.Model):
    """스캔별 데이터 정합성 점수."""
    
    __tablename__ = 'ml_consistency_scores'
    
    id = db.Column(db.Integer, primary_key=True)
    scan_id = db.Column(db.Integer, db.ForeignKey('scans.id'), nullable=False, unique=True)
    
    # 정합성 점수 (0-100)
    score = db.Column(db.Integer, nullable=False)
    
    # 점수 상세
    distribution_match = db.Column(db.Float, nullable=True, comment='같은 차종 분포 대비')
    physical_plausibility = db.Column(db.Float, nullable=True, comment='물리적 타당성')
    
    # 검출된 이슈 (JSON list)
    issues = db.Column(db.JSON, nullable=True)
    
    # 데이터 충분성
    sufficient_data = db.Column(db.Boolean, nullable=False, default=True)
    min_samples_required = db.Column(db.Integer, nullable=True)
    actual_samples = db.Column(db.Integer, nullable=True)
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<MLConsistencyScore scan_id={self.scan_id} score={self.score}>'


class MLDecoderProposal(db.Model):
    """ML이 제안한 디코더 개선 (관리자 승인 대기)."""
    
    __tablename__ = 'ml_decoder_proposals'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # 제안 내용
    maker = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(100), nullable=False)
    did_hex = db.Column(db.String(20), nullable=False)
    signal_name = db.Column(db.String(200), nullable=False)
    
    # 제안 상세 (JSON)
    proposed_decoder = db.Column(db.JSON, nullable=False, comment='제안된 디코더 정의')
    confidence = db.Column(db.Float, nullable=False, comment='0.0-1.0')
    supporting_samples = db.Column(db.Integer, nullable=False)
    
    # 승인 상태
    status = db.Column(db.String(50), nullable=False, default='pending', 
                      comment='pending/approved/rejected')
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        Index('ix_ml_proposals_pending', 'status', 'created_at'),
    )
    
    def __repr__(self):
        return f'<MLDecoderProposal {self.id} {self.maker} {self.signal_name} {self.status}>'
