"""배터리 사양 및 SOH 학습 모델."""
from datetime import datetime
from typing import Literal

from sqlalchemy import CheckConstraint, Index, String, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.makers import normalize_maker
from app.extensions import db


class BatterySpec(db.Model):
    """차량별 배터리 사양 (출시 당시 공식 제원)."""
    __tablename__ = "battery_specs"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    # 차량 식별
    maker: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    trim_grade: Mapped[str | None] = mapped_column(String(100))  # Long Range, Standard 등
    model_year: Mapped[int | None]  # 모델년도
    generation: Mapped[str | None] = mapped_column(String(50))  # 1세대, 2세대 등
    market: Mapped[str | None] = mapped_column(String(50))  # KR, US, EU 등
    
    # 배터리 제원
    gross_kwh: Mapped[float | None]  # 총 용량 (kWh)
    usable_kwh: Mapped[float | None]  # 사용 가능 용량 (kWh)
    nominal_voltage_v: Mapped[float | None]  # 공칭 전압 (V)
    capacity_ah: Mapped[float | None]  # 용량 (Ah)
    
    # 셀 정보
    cell_chemistry: Mapped[str | None] = mapped_column(String(20))  # NMC, NCA, LFP 등
    cell_count: Mapped[int | None]  # 셀 개수
    cell_config: Mapped[str | None] = mapped_column(String(50))  # 96S2P 등
    
    # 출처 (필수)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)  # 공식 스펙시트, ev-database.org 등
    source_note: Mapped[str | None] = mapped_column(Text)  # 추가 메모
    source_type: Mapped[str | None] = mapped_column(String(20))  # 'manufacturer' or 'third_party'
    
    # 메타데이터
    verified_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now(), nullable=False)
    
    @validates("maker")
    def _normalize_maker(self, _key, value):
        return normalize_maker(value)
    
    __table_args__ = (
        Index("ix_battery_specs_maker_model", "maker", "model"),
        Index("ix_battery_specs_year", "model_year"),
    )


class SOHResult(db.Model):
    """스캔별 SOH 계산 결과 및 학습 데이터."""
    __tablename__ = "soh_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    scan_id: Mapped[int] = mapped_column(db.ForeignKey("scans.id", ondelete="CASCADE"), 
                                        nullable=False, index=True)
    
    # SOH 값
    soh_pct: Mapped[float] = mapped_column(nullable=False)  # 계산된 SOH (%)
    method: Mapped[str] = mapped_column(String(50), nullable=False)  # bms_direct, capacity_based, coulomb_counting 등
    confidence: Mapped[float] = mapped_column(nullable=False)  # 신뢰도 0.0-1.0
    
    # 입력 데이터 (학습용)
    input_features: Mapped[dict] = mapped_column(JSON, nullable=False)  # 계산에 사용된 입력값들
    
    # 배터리 사양 참조 (capacity_based 방법인 경우)
    battery_spec_id: Mapped[int | None] = mapped_column(db.ForeignKey("battery_specs.id", ondelete="SET NULL"))
    
    # Ground truth (BMS 직접 읽기가 있는 경우)
    bms_soh_pct: Mapped[float | None]  # BMS에서 직접 읽은 SOH (있는 경우)
    
    # 학습 메타데이터
    formula_version_id: Mapped[int | None] = mapped_column(db.ForeignKey("learned_formulas.id", ondelete="SET NULL"))
    error_pct: Mapped[float | None]  # |predicted - bms_soh| (ground truth 있을 때만)
    
    # 계산 상세 (디버깅용)
    calculation_details: Mapped[dict | None] = mapped_column(JSON)
    
    computed_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    
    __table_args__ = (
        Index("ix_soh_results_scan", "scan_id"),
        Index("ix_soh_results_method", "method"),
        Index("ix_soh_results_bms_soh", "bms_soh_pct"),  # Ground truth 쿼리용
    )


class LearnedFormula(db.Model):
    """학습된 SOH 추정 공식 버전."""
    __tablename__ = "learned_formulas"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    # 공식 정보
    method: Mapped[str] = mapped_column(String(50), nullable=False)  # coulomb_counting_v2, capacity_based_calibrated 등
    version: Mapped[str] = mapped_column(String(20), nullable=False)  # v1.0, v1.1 등
    
    # 적용 범위
    maker: Mapped[str | None] = mapped_column(String(50))  # 특정 제조사에만 적용
    platform: Mapped[str | None] = mapped_column(String(50))  # E-GMP, IMA 등
    
    # 공식 파라미터 (JSON으로 저장)
    coefficients: Mapped[dict] = mapped_column(JSON, nullable=False)  # 보정 계수들
    
    # 학습 메트릭
    sample_count: Mapped[int] = mapped_column(nullable=False)  # 학습 샘플 수
    mae: Mapped[float] = mapped_column(nullable=False)  # Mean Absolute Error
    rmse: Mapped[float | None]  # Root Mean Squared Error
    r_squared: Mapped[float | None]  # R² score
    
    # 검증 데이터 성능
    validation_mae: Mapped[float | None]
    validation_sample_count: Mapped[int | None]
    
    # 활성화 상태
    is_active: Mapped[bool] = mapped_column(default=False, nullable=False)  # 현재 사용 중인지
    
    # 메타데이터
    trained_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    
    @validates("maker")
    def _normalize_maker(self, _key, value):
        if value:
            return normalize_maker(value)
        return value
    
    __table_args__ = (
        Index("ix_learned_formulas_method_version", "method", "version"),
        Index("ix_learned_formulas_maker", "maker"),
        Index("ix_learned_formulas_active", "is_active"),
    )
