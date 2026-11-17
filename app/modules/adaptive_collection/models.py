"""Adaptive Collection Models."""

from datetime import datetime
from enum import Enum

from sqlalchemy import JSON

from app.extensions import db


class CollectionProfileStatus(str, Enum):
    """Collection profile lifecycle status."""
    DRAFT = 'draft'
    PENDING_APPROVAL = 'pending_approval'
    APPROVED = 'approved'
    RETIRED = 'retired'


class SignalUsageTracking(db.Model):
    """Per-signal usage tracking for learning."""
    __tablename__ = 'signal_usage_tracking'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Signal identification
    maker = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(100), nullable=True)  # NULL = manufacturer-level
    signal_name = db.Column(db.String(100), nullable=False)  # e.g. 'dtc_status', 'cell_voltages'
    
    # Usage counts
    requested_count = db.Column(db.Integer, default=0, nullable=False)
    responded_count = db.Column(db.Integer, default=0, nullable=False)
    decoded_count = db.Column(db.Integer, default=0, nullable=False)
    
    # Usage by purpose
    used_for_report = db.Column(db.Integer, default=0, nullable=False)
    used_for_soh = db.Column(db.Integer, default=0, nullable=False)
    used_for_verdict = db.Column(db.Integer, default=0, nullable=False)
    used_for_ml = db.Column(db.Integer, default=0, nullable=False)
    used_for_inference = db.Column(db.Integer, default=0, nullable=False)
    
    # Response time stats (milliseconds)
    total_response_time_ms = db.Column(db.Integer, default=0, nullable=False)
    
    # Timestamps
    first_seen = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<SignalUsageTracking {self.maker}/{self.model or "ALL"} {self.signal_name}>'
    
    @property
    def response_rate(self) -> float:
        """Response rate: responded / requested."""
        if self.requested_count == 0:
            return 0.0
        return self.responded_count / self.requested_count
    
    @property
    def decode_rate(self) -> float:
        """Decode rate: decoded / responded."""
        if self.responded_count == 0:
            return 0.0
        return self.decoded_count / self.responded_count
    
    @property
    def usage_rate(self) -> float:
        """Usage rate: total_used / decoded."""
        if self.decoded_count == 0:
            return 0.0
        total_used = (
            self.used_for_report + self.used_for_soh + self.used_for_verdict +
            self.used_for_ml + self.used_for_inference
        )
        return total_used / self.decoded_count
    
    @property
    def avg_response_time_ms(self) -> float:
        """Average response time in milliseconds."""
        if self.responded_count == 0:
            return 0.0
        return self.total_response_time_ms / self.responded_count


class CollectionProfile(db.Model):
    """Versioned data collection profile."""
    __tablename__ = 'collection_profiles'
    
    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.String(50), nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default=CollectionProfileStatus.DRAFT.value)
    
    # Scope: NULL model = manufacturer-level
    scope_maker = db.Column(db.String(50), nullable=False)
    scope_model = db.Column(db.String(100), nullable=True)
    
    # Profile definition
    signals_to_skip = db.Column(JSON, nullable=False)  # List of signal names to skip
    skip_reason = db.Column(JSON, nullable=True)  # Reason per signal: {'signal_name': 'never used', ...}
    
    # Learning metadata
    generation_method = db.Column(db.String(50), nullable=False)  # 'threshold_based', 'ml_based'
    learning_sample_count = db.Column(db.Integer, nullable=True)
    learning_metrics = db.Column(JSON, nullable=True)  # Usage rates, response times
    
    # Impact estimation
    estimated_time_saved_ms = db.Column(db.Integer, nullable=True)
    estimated_signals_reduced = db.Column(db.Integer, nullable=True)
    
    # Approval workflow
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    approval_notes = db.Column(db.Text, nullable=True)
    
    # Retirement / rollback
    retired_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    retired_at = db.Column(db.DateTime, nullable=True)
    retirement_reason = db.Column(db.Text, nullable=True)
    
    # Relationships
    audit_logs = db.relationship('CollectionProfileAudit', back_populates='profile', lazy='dynamic')
    
    def __repr__(self):
        return f'<CollectionProfile {self.version} {self.status}>'


class CollectionProfileAudit(db.Model):
    """Audit log for collection profile lifecycle."""
    __tablename__ = 'collection_profile_audit'
    
    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey('collection_profiles.id'), nullable=False)
    
    action = db.Column(db.String(50), nullable=False)  # 'create', 'approve', 'retire', 'rollback'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    user_email = db.Column(db.String(255), nullable=True)
    
    previous_status = db.Column(db.String(20), nullable=True)
    new_status = db.Column(db.String(20), nullable=True)
    
    reason = db.Column(db.Text, nullable=True)
    changes = db.Column(JSON, nullable=True)
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    profile = db.relationship('CollectionProfile', back_populates='audit_logs')
    
    def __repr__(self):
        return f'<CollectionProfileAudit profile={self.profile_id} action={self.action}>'


class ProtectedSignal(db.Model):
    """Protected whitelist: signals never skipped."""
    __tablename__ = 'protected_signals'
    
    id = db.Column(db.Integer, primary_key=True)
    signal_name = db.Column(db.String(100), nullable=False, unique=True)
    reason = db.Column(db.Text, nullable=False)  # Why this signal is protected
    added_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    added_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<ProtectedSignal {self.signal_name}>'


class FullScanSample(db.Model):
    """Track full re-scan samples for re-enabling proposals."""
    __tablename__ = 'full_scan_samples'
    
    id = db.Column(db.Integer, primary_key=True)
    scan_id = db.Column(db.Integer, db.ForeignKey('scans.id'), nullable=False, unique=True)
    maker = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(100), nullable=True)
    
    # Why this was a full scan
    reason = db.Column(db.String(50), nullable=False)  # 'nth_sample', 'admin_forced', 'profile_disabled'
    
    # Findings
    skipped_signals_used = db.Column(JSON, nullable=True)  # Signals that were skipped but turned out useful
    new_signals_found = db.Column(JSON, nullable=True)  # New signals not in profile
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<FullScanSample scan={self.scan_id} reason={self.reason}>'
