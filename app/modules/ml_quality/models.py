"""ML Quality Analysis models (v2.2.22 Phase 1).

Scan error analysis and admin-approval improvement loop.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.modules.scans.models import Scan
from app.modules.auth.models import User


class ScanQualitySignal(db.Model):
    """Structured quality signals collected after each scan."""
    
    __tablename__ = "scan_quality_signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=db.func.now())
    
    # Quality signals
    decode_failures: Mapped[dict | None] = mapped_column(JSON)  # {did: reason}
    unmeasurable_items: Mapped[dict | None] = mapped_column(JSON)  # {item: reason}
    out_of_range_values: Mapped[dict | None] = mapped_column(JSON)  # {signal: {value, range}}
    soh_unavailable_reason: Mapped[str | None] = mapped_column(String(200))
    consistency_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    excluded_steps: Mapped[list | None] = mapped_column(JSON)  # [{command, reason}]
    dtc_status_unknown_count: Mapped[int | None] = mapped_column(Integer)
    contradictions: Mapped[list | None] = mapped_column(JSON)  # [{field1, field2, reason}]
    
    # Relationships
    scan: Mapped[Scan] = relationship()


class ImprovementProposal(db.Model):
    """ML-driven proposals for config improvements."""
    
    __tablename__ = "improvement_proposals"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected', 'rolled_back')", name="ck_proposal_status_valid"),
        CheckConstraint("generation_method IN ('rule_based', 'ai_assisted')", name="ck_generation_method_valid"),
        Index("ix_improvement_proposals_status", "status"),
        Index("ix_improvement_proposals_manufacturer", "manufacturer"),
        Index("ix_improvement_proposals_model", "model"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=db.func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=db.func.now(), onupdate=db.func.now())
    
    # Status
    status: Mapped[str] = mapped_column(String(20))  # pending, approved, rejected, rolled_back
    
    # Scope
    manufacturer: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
    
    # Proposal details
    proposal_type: Mapped[str] = mapped_column(String(50))  # decoder_mapping, threshold, soh_parameter
    evidence: Mapped[dict] = mapped_column(JSON)  # scan ids, counts, patterns
    config_delta: Mapped[dict] = mapped_column(JSON)  # structured config change
    expected_effect: Mapped[str | None] = mapped_column(Text)
    
    # Generation method
    generation_method: Mapped[str] = mapped_column(String(20))  # rule_based, ai_assisted
    ai_metadata: Mapped[dict | None] = mapped_column(JSON)  # only if ai_assisted
    
    # Relationships
    audit_logs: Mapped[list["ProposalAuditLog"]] = relationship(back_populates="proposal", cascade="all, delete-orphan")
    configs: Mapped[list["VersionedConfig"]] = relationship(back_populates="proposal")


class ProposalAuditLog(db.Model):
    """Audit trail for proposal lifecycle (approve/reject/rollback)."""
    
    __tablename__ = "proposal_audit_log"
    __table_args__ = (
        CheckConstraint("action IN ('approve', 'reject', 'rollback')", name="ck_audit_action_valid"),
        Index("ix_proposal_audit_log_proposal_id", "proposal_id"),
        Index("ix_proposal_audit_log_action_at", "action_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("improvement_proposals.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(20))  # approve, reject, rollback
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    user_email: Mapped[str | None] = mapped_column(String(255))
    action_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=db.func.now())
    reason: Mapped[str | None] = mapped_column(Text)
    previous_status: Mapped[str | None] = mapped_column(String(20))
    
    # Relationships
    proposal: Mapped[ImprovementProposal] = relationship(back_populates="audit_logs")
    user: Mapped[User | None] = relationship()


class VersionedConfig(db.Model):
    """Runtime config storage for approved proposals."""
    
    __tablename__ = "versioned_configs"
    __table_args__ = (
        Index("ix_versioned_configs_active", "active"),
        Index("ix_versioned_configs_type_mfg_model", "config_type", "manufacturer", "model"),
        Index("ix_versioned_configs_type_key", "config_type", "config_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    config_type: Mapped[str] = mapped_column(String(50))  # decoder_mapping, threshold, soh_parameter
    manufacturer: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
    config_key: Mapped[str] = mapped_column(String(100))
    config_value: Mapped[dict] = mapped_column(JSON)
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("improvement_proposals.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=db.func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Relationships
    proposal: Mapped[ImprovementProposal | None] = relationship(back_populates="configs")
