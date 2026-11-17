"""Adaptive collection models (v2.2.24 Phase 3)."""

from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Integer, String, Float, Boolean, Text, DateTime, ForeignKey, Index, CheckConstraint, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class ProfileStatus(str, Enum):
    """Collection profile status."""
    DRAFT = 'draft'
    PENDING_APPROVAL = 'pending_approval'
    APPROVED = 'approved'
    ROLLED_BACK = 'rolled_back'


class SignalUsageStats(db.Model):
    """Per-signal usage statistics for adaptive collection."""
    
    __tablename__ = 'signal_usage_stats'
    __table_args__ = (
        UniqueConstraint('manufacturer', 'model', 'signal_identifier', name='uq_signal_usage_scope'),
        Index('idx_signal_usage_manufacturer', 'manufacturer'),
        Index('idx_signal_usage_model', 'manufacturer', 'model'),
        Index('idx_signal_usage_signal', 'signal_identifier'),
    )
    
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True)
    manufacturer: Mapped[str] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))  # NULL = manufacturer-level
    signal_identifier: Mapped[str] = mapped_column(String(200))  # e.g., "did:2101"
    
    # Usage counters
    requested_count: Mapped[int] = mapped_column(Integer, server_default='0')
    responded_count: Mapped[int] = mapped_column(Integer, server_default='0')
    decoded_count: Mapped[int] = mapped_column(Integer, server_default='0')
    
    # Usage in different contexts
    used_in_report_count: Mapped[int] = mapped_column(Integer, server_default='0')
    used_in_soh_count: Mapped[int] = mapped_column(Integer, server_default='0')
    used_in_verdict_count: Mapped[int] = mapped_column(Integer, server_default='0')
    used_in_ml_quality_count: Mapped[int] = mapped_column(Integer, server_default='0')
    used_in_soh_inference_count: Mapped[int] = mapped_column(Integer, server_default='0')
    
    # Performance metrics
    avg_response_time_ms: Mapped[float | None] = mapped_column(Float)
    total_response_time_ms: Mapped[int] = mapped_column(BigInteger, server_default='0')
    
    # Metadata
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=db.func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=db.func.now(), onupdate=db.func.now())


class CollectionProfile(db.Model):
    """Versioned collection profile with approval workflow."""
    
    __tablename__ = 'collection_profiles'
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'pending_approval', 'approved', 'rolled_back')", name='ck_profile_status_valid'),
        Index('idx_collection_profiles_status', 'status'),
        Index('idx_collection_profiles_scope', 'manufacturer', 'model'),
    )
    
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True)
    version: Mapped[str] = mapped_column(String(50), unique=True)
    status: Mapped[str] = mapped_column(String(20))
    
    # Scope
    manufacturer: Mapped[str] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))  # NULL = manufacturer-level
    
    # Configuration
    skip_threshold_scans: Mapped[int] = mapped_column(Integer, server_default='20')
    full_rescan_interval: Mapped[int] = mapped_column(Integer, server_default='10')
    
    # Profile data
    signals_to_skip: Mapped[list] = mapped_column(JSON)  # List of signal identifiers
    generation_evidence: Mapped[dict | None] = mapped_column(JSON)  # Stats that led to this profile
    
    # Approval workflow
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=db.func.now())
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_notes: Mapped[str | None] = mapped_column(Text)
    rolled_back_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rollback_reason: Mapped[str | None] = mapped_column(Text)
    
    # Relationships
    audit_logs: Mapped[list["CollectionProfileAudit"]] = relationship(back_populates="profile", cascade="all, delete-orphan")


class CollectionProfileAudit(db.Model):
    """Audit log for collection profile lifecycle."""
    
    __tablename__ = 'collection_profile_audit'
    __table_args__ = (
        CheckConstraint("action IN ('create', 'approve', 'rollback', 'reenable_signal', 'update')", name='ck_profile_audit_action_valid'),
        Index('idx_collection_profile_audit_profile', 'profile_id'),
        Index('idx_collection_profile_audit_action', 'action'),
    )
    
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey('collection_profiles.id', ondelete='SET NULL'))
    action: Mapped[str] = mapped_column(String(50))
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    user_email: Mapped[str | None] = mapped_column(String(255))
    action_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=db.func.now())
    previous_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str | None] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(Text)
    changes: Mapped[dict | None] = mapped_column(JSON)
    
    # Relationships
    profile: Mapped["CollectionProfile | None"] = relationship(back_populates="audit_logs")


class SignalWhitelist(db.Model):
    """Protected signals that can never be skipped."""
    
    __tablename__ = 'signal_whitelist'
    __table_args__ = (
        Index('idx_signal_whitelist_active', 'is_active'),
        Index('idx_signal_whitelist_reason', 'reason'),
    )
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_identifier: Mapped[str] = mapped_column(String(200), unique=True)
    reason: Mapped[str] = mapped_column(String(200))  # e.g., "required_for_soh"
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default='true')
    added_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=db.func.now())


class SignalWhitelistAudit(db.Model):
    """Audit log for whitelist changes."""
    
    __tablename__ = 'signal_whitelist_audit'
    __table_args__ = (
        CheckConstraint("action IN ('add', 'remove', 'update')", name='ck_whitelist_audit_action_valid'),
        Index('idx_signal_whitelist_audit_signal', 'signal_identifier'),
    )
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    whitelist_id: Mapped[int | None] = mapped_column(ForeignKey('signal_whitelist.id', ondelete='SET NULL'))
    signal_identifier: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    user_email: Mapped[str | None] = mapped_column(String(255))
    action_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=db.func.now())
    reason: Mapped[str | None] = mapped_column(Text)
    changes: Mapped[dict | None] = mapped_column(JSON)
