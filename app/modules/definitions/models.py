"""Vehicle definition models for DBC, diagnostic commands, and verification."""
from datetime import datetime
from typing import Literal

from sqlalchemy import CheckConstraint, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.makers import normalize_maker
from app.extensions import db

DefinitionType = Literal["dbc", "obdb", "wican", "torque", "canze"]
VerificationStatus = Literal["needs_verification", "verified", "failed"]


class DefinitionSource(db.Model):
    """정의파일 출처 메타데이터."""
    __tablename__ = "definition_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    # 파일 정보
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # dbc|obdb|wican|torque|canze
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    file_size: Mapped[int] = mapped_column(nullable=False)
    
    # 출처 및 라이선스
    origin_repo: Mapped[str | None] = mapped_column(String(200))
    origin_commit: Mapped[str | None] = mapped_column(String(40))
    license: Mapped[str | None] = mapped_column(String(100))
    license_text: Mapped[str | None] = mapped_column(Text)
    attribution: Mapped[str | None] = mapped_column(Text)
    
    # 메타데이터
    imported_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    
    __table_args__ = (
        CheckConstraint("source_type IN ('dbc', 'obdb', 'wican', 'torque', 'canze')", 
                       name="ck_definition_sources_type"),
        Index("ix_definition_sources_type", "source_type"),
    )


class VehicleDefinition(db.Model):
    """차량-정의파일 매핑."""
    __tablename__ = "vehicle_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    source_id: Mapped[int] = mapped_column(db.ForeignKey("definition_sources.id", ondelete="CASCADE"), 
                                          nullable=False, index=True)
    
    # 차량 정보
    maker: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(Text)
    submodel: Mapped[str | None] = mapped_column(String(100))
    year_from: Mapped[int | None]
    year_to: Mapped[int | None]
    
    # 추가 메타데이터
    powertrain: Mapped[str | None] = mapped_column(String(20))  # BEV|PHEV|HEV|ICE
    notes: Mapped[str | None] = mapped_column(Text)
    battery_spec_id: Mapped[int | None] = mapped_column(db.ForeignKey("battery_specs.id", ondelete="SET NULL"))
    
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    
    @validates("maker")
    def _normalize_maker(self, _key, value):
        return normalize_maker(value)
    
    __table_args__ = (
        Index("ix_vehicle_definitions_maker_model", "maker", "model"),
        Index("ix_vehicle_definitions_source", "source_id"),
    )


class DbcMessage(db.Model):
    """DBC CAN 메시지."""
    __tablename__ = "dbc_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    source_id: Mapped[int] = mapped_column(db.ForeignKey("definition_sources.id", ondelete="CASCADE"), 
                                          nullable=False, index=True)
    
    # DBC 메시지 정보
    can_id: Mapped[int] = mapped_column(db.BigInteger, nullable=False)  # CAN ID (29-bit extended)
    message_name: Mapped[str] = mapped_column(Text, nullable=False)
    dlc: Mapped[int] = mapped_column(nullable=False)  # Data Length Code
    sender: Mapped[str | None] = mapped_column(String(100))
    
    # 메타데이터
    comment: Mapped[str | None] = mapped_column(Text)
    
    __table_args__ = (
        Index("ix_dbc_messages_source_can_id", "source_id", "can_id"),
        Index("ix_dbc_messages_can_id", "can_id"),
    )


class DbcSignal(db.Model):
    """DBC CAN 신호."""
    __tablename__ = "dbc_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    message_id: Mapped[int] = mapped_column(db.ForeignKey("dbc_messages.id", ondelete="CASCADE"), 
                                            nullable=False, index=True)
    
    # 신호 정보
    signal_name: Mapped[str] = mapped_column(Text, nullable=False)
    start_bit: Mapped[int] = mapped_column(nullable=False)
    bit_length: Mapped[int] = mapped_column(nullable=False)
    byte_order: Mapped[str] = mapped_column(String(10), nullable=False)  # little|big
    value_type: Mapped[str] = mapped_column(String(10), nullable=False)  # signed|unsigned
    
    # 변환 정보
    factor: Mapped[float] = mapped_column(default=1.0, nullable=False)
    offset: Mapped[float] = mapped_column(default=0.0, nullable=False)
    min_value: Mapped[float | None]
    max_value: Mapped[float | None]
    unit: Mapped[str | None] = mapped_column(String(50))
    
    # 메타데이터
    comment: Mapped[str | None] = mapped_column(Text)
    receivers: Mapped[str | None] = mapped_column(Text)  # comma-separated ECU names
    
    # Classification
    protocol: Mapped[str | None] = mapped_column(String(20))  # CAN, CAN-FD
    ecu_module: Mapped[str | None] = mapped_column(String(50))  # BMS, MCU, OBC, VCU
    signal_category: Mapped[str | None] = mapped_column(String(30))  # battery_soc, battery_soh
    
    __table_args__ = (
        Index("ix_dbc_signals_message", "message_id"),
        Index("ix_dbc_signals_name", "signal_name"),
        Index("ix_dbc_signals_protocol", "protocol"),
        Index("ix_dbc_signals_ecu_module", "ecu_module"),
        Index("ix_dbc_signals_signal_category", "signal_category"),
    )


class DiagnosticCommand(db.Model):
    """진단 명령 (OBDb, WiCAN, Torque, CanZE 통합)."""
    __tablename__ = "diagnostic_commands"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    source_id: Mapped[int] = mapped_column(db.ForeignKey("definition_sources.id", ondelete="CASCADE"), 
                                          nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # obdb|wican|torque|canze
    
    # 차량 범위 (optional scoping)
    maker: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(Text)
    year_from: Mapped[int | None]
    year_to: Mapped[int | None]
    
    # 명령 정보
    ecu_address: Mapped[str | None] = mapped_column(String(10))  # 7E4, 7E0 등
    ecu_name: Mapped[str | None] = mapped_column(Text)
    service: Mapped[str] = mapped_column(String(10), nullable=False)  # 22, 01 등
    pid: Mapped[str] = mapped_column(String(50), nullable=False)  # DID/PID
    command_bytes: Mapped[str] = mapped_column(String(100), nullable=False)  # 전체 명령 (22 1050)
    
    # 응답 해석
    label: Mapped[str] = mapped_column(Text, nullable=False)
    formula: Mapped[str | None] = mapped_column(Text)  # 계산식
    unit: Mapped[str | None] = mapped_column(String(50))
    
    # 응답 위치 (OBDb, CanZE 등)
    response_start_byte: Mapped[int | None]
    response_bit_offset: Mapped[int | None]
    response_length: Mapped[int | None]  # bits or bytes
    
    # 메타데이터
    frequency: Mapped[float | None]  # OBDb freq
    min_value: Mapped[float | None]
    max_value: Mapped[float | None]
    notes: Mapped[str | None] = mapped_column(Text)
    
    verification_status: Mapped[str] = mapped_column(String(20), 
                                                     default="needs_verification", 
                                                     nullable=False)
    verification_count: Mapped[int] = mapped_column(default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(default=0, nullable=False)
    
    # Classification
    protocol: Mapped[str | None] = mapped_column(String(20))  # OBD-II, UDS, KWP2000
    ecu_module: Mapped[str | None] = mapped_column(String(50))  # BMS, MCU, ECM, TCM
    
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now(), nullable=False)
    
    @validates("maker")
    def _normalize_maker(self, _key, value):
        return normalize_maker(value)
    
    __table_args__ = (
        CheckConstraint("source_type IN ('obdb', 'wican', 'torque', 'canze')", 
                       name="ck_diagnostic_commands_source_type"),
        CheckConstraint("verification_status IN ('needs_verification', 'verified', 'failed')", 
                       name="ck_diagnostic_commands_verification_status"),
        Index("ix_diagnostic_commands_source", "source_id"),
        Index("ix_diagnostic_commands_maker_model", "maker", "model"),
        Index("ix_diagnostic_commands_ecu_service_pid", "ecu_address", "service", "pid"),
        Index("ix_diagnostic_commands_verification", "verification_status"),
        Index("ix_diagnostic_commands_protocol", "protocol"),
        Index("ix_diagnostic_commands_ecu_module", "ecu_module"),
    )


class ScanObservation(db.Model):
    """스캔별 정의 적용 관찰 결과 (학습용)."""
    __tablename__ = "scan_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    scan_id: Mapped[int] = mapped_column(db.ForeignKey("scans.id", ondelete="CASCADE"), 
                                        nullable=False, index=True)
    
    # 적용된 정의
    definition_type: Mapped[str] = mapped_column(String(20), nullable=False)  # dbc|diagnostic
    definition_id: Mapped[int] = mapped_column(nullable=False)  # DbcSignal.id or DiagnosticCommand.id
    
    # 관찰 결과
    applied: Mapped[bool] = mapped_column(default=True, nullable=False)
    success: Mapped[bool | None]  # None = 시도 안 함
    raw_request: Mapped[str | None] = mapped_column(String(500))  # Increased for long ISO-TP requests
    raw_response: Mapped[str | None] = mapped_column(Text)
    decoded_value: Mapped[str | None] = mapped_column(Text)  # Changed to Text for long decoded values
    
    # 불일치 플래그
    mismatch_reason: Mapped[str | None] = mapped_column(Text)
    
    observed_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    
    __table_args__ = (
        Index("ix_scan_observations_scan", "scan_id"),
        Index("ix_scan_observations_definition", "definition_type", "definition_id"),
        Index("ix_scan_observations_success", "success"),
    )
