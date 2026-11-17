"""SOH Inference Models."""

from datetime import datetime
from enum import Enum

from sqlalchemy import JSON

from app.extensions import db


class InferenceModelStatus(str, Enum):
    """Inference model lifecycle status."""
    DRAFT = 'draft'
    PENDING_APPROVAL = 'pending_approval'
    APPROVED = 'approved'
    RETIRED = 'retired'


class SOHInferenceModel(db.Model):
    """Versioned SOH inference model."""
    __tablename__ = 'soh_inference_models'
    
    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.String(50), nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default=InferenceModelStatus.DRAFT.value)
    
    # Scope: None = global, maker = manufacturer-level, maker+model = model-specific
    scope_maker = db.Column(db.String(50), nullable=True)
    scope_model = db.Column(db.String(100), nullable=True)
    
    # Model definition
    model_type = db.Column(db.String(50), nullable=False)  # 'linear', 'polynomial', 'neural', etc.
    model_config = db.Column(JSON, nullable=False)  # Model hyperparameters
    model_weights = db.Column(JSON, nullable=True)  # Trained weights/coefficients
    
    # Training metadata
    training_sample_count = db.Column(db.Integer, nullable=True)
    training_metrics = db.Column(JSON, nullable=True)  # MAE, RMSE, R², etc.
    validation_metrics = db.Column(JSON, nullable=True)
    backtest_metrics = db.Column(JSON, nullable=True)  # Against measured SOH
    
    # Feature importance
    feature_names = db.Column(JSON, nullable=False)  # List of input features used
    feature_importance = db.Column(JSON, nullable=True)  # Feature importance scores
    
    # Approval workflow
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    approval_notes = db.Column(db.Text, nullable=True)
    
    # Retirement
    retired_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    retired_at = db.Column(db.DateTime, nullable=True)
    retirement_reason = db.Column(db.Text, nullable=True)
    
    # Relationships
    inferences = db.relationship('SOHInference', back_populates='model', lazy='dynamic')
    audit_logs = db.relationship('InferenceModelAudit', back_populates='model', lazy='dynamic')
    
    def __repr__(self):
        return f'<SOHInferenceModel {self.version} {self.status}>'


class SOHInference(db.Model):
    """SOH inference result for a scan."""
    __tablename__ = 'soh_inferences'
    
    id = db.Column(db.Integer, primary_key=True)
    scan_id = db.Column(db.Integer, db.ForeignKey('scans.id'), nullable=False)
    model_id = db.Column(db.Integer, db.ForeignKey('soh_inference_models.id'), nullable=False)
    
    # Inference result
    estimated_soh = db.Column(db.Float, nullable=False)
    soh_range_min = db.Column(db.Float, nullable=True)  # Confidence interval
    soh_range_max = db.Column(db.Float, nullable=True)
    confidence_score = db.Column(db.Float, nullable=True)  # 0.0-1.0
    
    # Method and inputs
    inference_method = db.Column(db.String(50), nullable=False)
    input_features = db.Column(JSON, nullable=False)  # Features used for this inference
    calculation_details = db.Column(JSON, nullable=True)  # Intermediate calculations
    
    # Fallback chain (scope resolution)
    resolution_chain = db.Column(JSON, nullable=True)  # ['model_specific', 'manufacturer', 'global']
    
    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    scan = db.relationship('Scan', backref='soh_inferences')
    model = db.relationship('SOHInferenceModel', back_populates='inferences')
    
    def __repr__(self):
        return f'<SOHInference scan={self.scan_id} soh={self.estimated_soh}%>'


class InferenceModelAudit(db.Model):
    """Audit log for inference model lifecycle events."""
    __tablename__ = 'soh_inference_model_audit'
    
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.Integer, db.ForeignKey('soh_inference_models.id'), nullable=False)
    
    action = db.Column(db.String(50), nullable=False)  # 'create', 'approve', 'retire', 'update'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    user_email = db.Column(db.String(255), nullable=True)
    
    previous_status = db.Column(db.String(20), nullable=True)
    new_status = db.Column(db.String(20), nullable=True)
    
    reason = db.Column(db.Text, nullable=True)
    changes = db.Column(JSON, nullable=True)  # What changed
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    model = db.relationship('SOHInferenceModel', back_populates='audit_logs')
    
    def __repr__(self):
        return f'<InferenceModelAudit model={self.model_id} action={self.action}>'
