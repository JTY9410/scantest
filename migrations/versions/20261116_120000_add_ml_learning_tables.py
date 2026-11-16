"""add_ml_learning_tables

Revision ID: 20261116_120000
Revises: 3e8f9c4d1234
Create Date: 2026-11-16 12:00:00.000000

Adds tables for ML learning process:
- ml_scan_features: 익명화된 스캔 특징 저장
- ml_feedback: 관리자 피드백/수정 기록
- ml_models: 학습된 모델 메타데이터
- ml_anomaly_detections: 이상 탐지 결과
- ml_decoder_proposals: 미지의 CAN ID/신호 후보
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20261116_120000'
down_revision = '20261115_add_battery_reference_capacity'
branch_labels = None
depends_on = None


def upgrade():
    # ml_scan_features: 익명화된 스캔 특징
    op.create_table(
        'ml_scan_features',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('scan_id', sa.Integer(), nullable=True),  # NULL for anonymized
        
        # 차량 정보 (익명화)
        sa.Column('maker', sa.String(50), nullable=False),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('fuel_type', sa.String(20), nullable=False),  # ev, hev, ice
        
        # 스캔 결과
        sa.Column('overall_judgment', sa.String(20), nullable=True),  # 양호, 점검요, 판정보류
        sa.Column('dtc_count', sa.Integer(), nullable=True),
        sa.Column('significant_dtc_count', sa.Integer(), nullable=True),
        
        # 신호 커버리지 (어떤 신호를 읽었는가)
        sa.Column('signals_read', postgresql.JSONB(), nullable=True),  # {signal_name: True/False}
        
        # 디코딩된 값 (이상치 탐지용)
        sa.Column('decoded_values', postgresql.JSONB(), nullable=True),  # {signal: value}
        
        # 측정불가 항목
        sa.Column('unmeasurable_items', postgresql.JSONB(), nullable=True),  # [reasons]
        sa.Column('unmeasurable_count', sa.Integer(), nullable=True),
        
        # 디코더 정보
        sa.Column('decoder_sources', postgresql.JSONB(), nullable=True),  # {signal: source}
        sa.Column('decoder_version', sa.String(50), nullable=True),
        
        # 앱/장치 정보
        sa.Column('device_type', sa.String(50), nullable=True),  # web, app, lte
        sa.Column('app_version', sa.String(50), nullable=True),
        
        sa.PrimaryKeyConstraint('id'),
        sa.Index('ix_ml_scan_features_maker_model', 'maker', 'model'),
        sa.Index('ix_ml_scan_features_created_at', 'created_at'),
        sa.Index('ix_ml_scan_features_judgment', 'overall_judgment'),
    )
    
    # ml_feedback: 관리자 피드백 (labelled training data)
    op.create_table(
        'ml_feedback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('admin_id', sa.Integer(), nullable=False),
        sa.Column('scan_id', sa.Integer(), nullable=True),
        sa.Column('feature_id', sa.Integer(), nullable=True),
        
        # 피드백 타입
        sa.Column('feedback_type', sa.String(50), nullable=False),  
        # 'correct_soc', 'correct_soh', 'mark_signal_wrong', 'confirm_dtc_estimate', etc.
        
        # 원래 값과 수정 값
        sa.Column('original_value', sa.Text(), nullable=True),
        sa.Column('corrected_value', sa.Text(), nullable=True),
        sa.Column('signal_name', sa.String(100), nullable=True),
        
        # 설명/근거
        sa.Column('notes', sa.Text(), nullable=True),
        
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['admin_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['scan_id'], ['scans.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['feature_id'], ['ml_scan_features.id'], ondelete='CASCADE'),
        sa.Index('ix_ml_feedback_created_at', 'created_at'),
        sa.Index('ix_ml_feedback_type', 'feedback_type'),
    )
    
    # ml_models: 학습된 모델 메타데이터
    op.create_table(
        'ml_models',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('model_type', sa.String(50), nullable=False),  
        # 'anomaly_detection', 'soh_estimation', 'can_id_prediction'
        
        sa.Column('model_version', sa.String(50), nullable=False),  # v1, v2, etc.
        sa.Column('status', sa.String(20), nullable=False),  # training, candidate, active, retired
        
        # 학습 정보
        sa.Column('training_sample_count', sa.Integer(), nullable=False),
        sa.Column('training_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('training_completed_at', sa.DateTime(timezone=True), nullable=True),
        
        # 메트릭 (JSON)
        sa.Column('metrics', postgresql.JSONB(), nullable=True),  
        # {accuracy, precision, recall, f1_score, mae, rmse, etc.}
        
        # 검증 세트 메트릭
        sa.Column('validation_metrics', postgresql.JSONB(), nullable=True),
        
        # 모델 파라미터/설정
        sa.Column('hyperparameters', postgresql.JSONB(), nullable=True),
        
        # 모델 파일 경로 (실제 모델은 파일시스템에 저장)
        sa.Column('model_path', sa.String(500), nullable=True),
        
        # 승인 정보
        sa.Column('approved_by', sa.Integer(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approval_notes', sa.Text(), nullable=True),
        
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ondelete='SET NULL'),
        sa.Index('ix_ml_models_type_status', 'model_type', 'status'),
        sa.Index('ix_ml_models_version', 'model_version'),
        sa.UniqueConstraint('model_type', 'model_version', name='uq_ml_models_type_version'),
    )
    
    # ml_anomaly_detections: 이상 탐지 결과
    op.create_table(
        'ml_anomaly_detections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('scan_id', sa.Integer(), nullable=False),
        sa.Column('model_id', sa.Integer(), nullable=False),
        
        # 이상 탐지 결과
        sa.Column('is_anomaly', sa.Boolean(), nullable=False),
        sa.Column('anomaly_score', sa.Float(), nullable=True),  # 0-1 범위
        sa.Column('anomaly_type', sa.String(50), nullable=True),  
        # 'cell_voltage_spread', 'temperature_outlier', 'soc_voltage_inconsistency', etc.
        
        sa.Column('affected_signals', postgresql.JSONB(), nullable=True),  # [signal names]
        sa.Column('details', postgresql.JSONB(), nullable=True),  # {signal: {value, expected_range, deviation}}
        
        # 관리자 확인
        sa.Column('reviewed_by', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_result', sa.String(20), nullable=True),  # true_positive, false_positive, needs_investigation
        sa.Column('review_notes', sa.Text(), nullable=True),
        
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['scan_id'], ['scans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['model_id'], ['ml_models.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
        sa.Index('ix_ml_anomaly_scan', 'scan_id'),
        sa.Index('ix_ml_anomaly_created_at', 'created_at'),
    )
    
    # ml_decoder_proposals: 미지의 CAN ID/신호 후보
    op.create_table(
        'ml_decoder_proposals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('model_id', sa.Integer(), nullable=True),
        
        # 차량 정보
        sa.Column('maker', sa.String(50), nullable=False),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('year_range', sa.String(20), nullable=True),  # "2020-2023"
        
        # CAN 정보
        sa.Column('can_id', sa.String(10), nullable=False),  # e.g., "7E4"
        sa.Column('signal_name', sa.String(100), nullable=True),  # proposed signal name
        sa.Column('byte_offset', sa.Integer(), nullable=True),
        sa.Column('bit_length', sa.Integer(), nullable=True),
        sa.Column('scale', sa.Float(), nullable=True),
        sa.Column('offset', sa.Float(), nullable=True),
        sa.Column('unit', sa.String(20), nullable=True),
        
        # 신뢰도
        sa.Column('confidence_score', sa.Float(), nullable=True),  # 0-1
        sa.Column('sample_count', sa.Integer(), nullable=False),  # 몇 개 스캔에서 발견되었나
        
        # 발견된 값 범위
        sa.Column('observed_min', sa.Float(), nullable=True),
        sa.Column('observed_max', sa.Float(), nullable=True),
        sa.Column('observed_values_sample', postgresql.JSONB(), nullable=True),  # [샘플 값들]
        
        # 상태
        sa.Column('status', sa.String(20), nullable=False),  
        # 'pending', 'approved', 'rejected', 'needs_more_data'
        
        # 관리자 검토
        sa.Column('reviewed_by', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['model_id'], ['ml_models.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
        sa.Index('ix_ml_decoder_maker_model', 'maker', 'model'),
        sa.Index('ix_ml_decoder_status', 'status'),
        sa.Index('ix_ml_decoder_can_id', 'can_id'),
    )


def downgrade():
    op.drop_table('ml_decoder_proposals')
    op.drop_table('ml_anomaly_detections')
    op.drop_table('ml_models')
    op.drop_table('ml_feedback')
    op.drop_table('ml_scan_features')
