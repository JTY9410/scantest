"""ML Learning 데이터 모델.

익명화된 특징 저장, 피드백, 학습된 모델 메타데이터.
"""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class MLScanFeature(db.Model):
    """익명화된 스캔 특징 (차량번호/VIN 없음)."""
    __tablename__ = "ml_scan_features"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    scan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Anonymized: NULL
    
    # 차량 정보 (익명화)
    maker: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fuel_type: Mapped[str] = mapped_column(String(20), nullable=False)  # ev, hev, ice
    
    # 스캔 결과
    overall_judgment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    dtc_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    significant_dtc_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # 신호 커버리지
    signals_read: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    
    # 디코딩된 값
    decoded_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    
    # 측정불가 항목
    unmeasurable_items: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    unmeasurable_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # 디코더 정보
    decoder_sources: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    decoder_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    
    # 앱/장치 정보
    device_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    
    __table_args__ = (
        Index("ix_ml_scan_features_maker_model", "maker", "model"),
        Index("ix_ml_scan_features_created_at", "created_at"),
        Index("ix_ml_scan_features_judgment", "overall_judgment"),
    )


class MLFeedback(db.Model):
    """관리자 피드백 (labelled training data)."""
    __tablename__ = "ml_feedback"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    admin_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    scan_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("scans.id", ondelete="SET NULL"), nullable=True)
    feature_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("ml_scan_features.id", ondelete="CASCADE"), nullable=True)
    
    # 피드백 타입
    feedback_type: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # 원래 값과 수정 값
    original_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    signal_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    
    # 설명/근거
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    __table_args__ = (
        Index("ix_ml_feedback_created_at", "created_at"),
        Index("ix_ml_feedback_type", "feedback_type"),
    )


class MLModel(db.Model):
    """학습된 모델 메타데이터."""
    __tablename__ = "ml_models"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    model_type: Mapped[str] = mapped_column(String(50), nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # training, candidate, active, retired
    
    # 학습 정보
    training_sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    training_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    training_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # 메트릭
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    validation_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    
    # 모델 파라미터
    hyperparameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    
    # 모델 파일 경로
    model_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    # 승인 정보
    approved_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    __table_args__ = (
        Index("ix_ml_models_type_status", "model_type", "status"),
        Index("ix_ml_models_version", "model_version"),
        UniqueConstraint("model_type", "model_version", name="uq_ml_models_type_version"),
    )


class MLAnomalyDetection(db.Model):
    """이상 탐지 결과."""
    __tablename__ = "ml_anomaly_detections"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    scan_id: Mapped[int] = mapped_column(Integer, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    model_id: Mapped[int] = mapped_column(Integer, ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=False)
    
    # 이상 탐지 결과
    is_anomaly: Mapped[bool] = mapped_column(Boolean, nullable=False)
    anomaly_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    anomaly_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    
    affected_signals: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    
    # 관리자 확인
    reviewed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    __table_args__ = (
        Index("ix_ml_anomaly_scan", "scan_id"),
        Index("ix_ml_anomaly_created_at", "created_at"),
    )


class MLDecoderProposal(db.Model):
    """미지의 CAN ID/신호 후보."""
    __tablename__ = "ml_decoder_proposals"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    model_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("ml_models.id", ondelete="SET NULL"), nullable=True)
    
    # 차량 정보
    maker: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    year_range: Mapped[str | None] = mapped_column(String(20), nullable=True)
    
    # CAN 정보
    can_id: Mapped[str] = mapped_column(String(10), nullable=False)
    signal_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    byte_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bit_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scale: Mapped[float | None] = mapped_column(Float, nullable=True)
    offset: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    
    # 신뢰도
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # 발견된 값 범위
    observed_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_values_sample: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    
    # 상태
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    
    # 관리자 검토
    reviewed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    __table_args__ = (
        Index("ix_ml_decoder_maker_model", "maker", "model"),
        Index("ix_ml_decoder_status", "status"),
        Index("ix_ml_decoder_can_id", "can_id"),
    )
