"""SOH Inference Admin Routes."""

from datetime import datetime
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user

from app.extensions import db
from app.modules.soh_inference.models import (
    SOHInferenceModel, InferenceModelAudit, InferenceModelStatus
)
from app.modules.auth.access import admin_required


bp = Blueprint('soh_inference', __name__, url_prefix='/admin/soh/inference')


@bp.route('/models', methods=['GET'])
@login_required
@admin_required
def list_models():
    """List all inference models."""
    status_filter = request.args.get('status')
    
    query = db.session.query(SOHInferenceModel)
    
    if status_filter:
        query = query.filter(SOHInferenceModel.status == status_filter)
    
    models = query.order_by(SOHInferenceModel.created_at.desc()).all()
    
    return jsonify({
        'models': [
            {
                'id': m.id,
                'version': m.version,
                'status': m.status,
                'scope_maker': m.scope_maker,
                'scope_model': m.scope_model,
                'model_type': m.model_type,
                'created_at': m.created_at.isoformat() if m.created_at else None,
                'approved_at': m.approved_at.isoformat() if m.approved_at else None,
                'training_metrics': m.training_metrics,
                'validation_metrics': m.validation_metrics,
                'backtest_metrics': m.backtest_metrics
            }
            for m in models
        ]
    })


@bp.route('/models/<int:model_id>', methods=['GET'])
@login_required
@admin_required
def get_model(model_id):
    """Get model details."""
    model = db.session.get(SOHInferenceModel, model_id)
    
    if not model:
        return jsonify({'error': 'Model not found'}), 404
    
    return jsonify({
        'id': model.id,
        'version': model.version,
        'status': model.status,
        'scope_maker': model.scope_maker,
        'scope_model': model.scope_model,
        'model_type': model.model_type,
        'model_config': model.model_config,
        'model_weights': model.model_weights,
        'feature_names': model.feature_names,
        'feature_importance': model.feature_importance,
        'training_sample_count': model.training_sample_count,
        'training_metrics': model.training_metrics,
        'validation_metrics': model.validation_metrics,
        'backtest_metrics': model.backtest_metrics,
        'created_at': model.created_at.isoformat() if model.created_at else None,
        'approved_at': model.approved_at.isoformat() if model.approved_at else None,
        'approval_notes': model.approval_notes,
        'retired_at': model.retired_at.isoformat() if model.retired_at else None,
        'retirement_reason': model.retirement_reason
    })


@bp.route('/models/<int:model_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_model(model_id):
    """Approve a pending inference model."""
    model = db.session.get(SOHInferenceModel, model_id)
    
    if not model:
        return jsonify({'error': 'Model not found'}), 404
    
    if model.status == InferenceModelStatus.APPROVED.value:
        return jsonify({'error': 'Model already approved'}), 400
    
    if model.status == InferenceModelStatus.RETIRED.value:
        return jsonify({'error': 'Cannot approve retired model'}), 400
    
    data = request.get_json() or {}
    notes = data.get('notes', '').strip()
    
    if not notes:
        return jsonify({'error': 'Approval notes required'}), 400
    
    # Update model status
    previous_status = model.status
    model.status = InferenceModelStatus.APPROVED.value
    model.approved_by_user_id = current_user.id
    model.approved_at = datetime.utcnow()
    model.approval_notes = notes
    
    # Create audit log
    audit = InferenceModelAudit(
        model_id=model.id,
        action='approve',
        user_id=current_user.id,
        user_email=current_user.tid,
        previous_status=previous_status,
        new_status=model.status,
        reason=notes
    )
    
    db.session.add(audit)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'model_id': model.id,
        'version': model.version,
        'status': model.status,
        'approved_at': model.approved_at.isoformat()
    })


@bp.route('/models/<int:model_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_model(model_id):
    """Reject a pending inference model."""
    model = db.session.get(SOHInferenceModel, model_id)
    
    if not model:
        return jsonify({'error': 'Model not found'}), 404
    
    if model.status not in [InferenceModelStatus.DRAFT.value, InferenceModelStatus.PENDING_APPROVAL.value]:
        return jsonify({'error': 'Can only reject draft or pending models'}), 400
    
    data = request.get_json() or {}
    reason = data.get('reason', '').strip()
    
    if not reason:
        return jsonify({'error': 'Rejection reason required'}), 400
    
    # Delete the model (rejection = permanent removal)
    previous_status = model.status
    
    # Create audit log before deletion
    audit = InferenceModelAudit(
        model_id=model.id,
        action='reject',
        user_id=current_user.id,
        user_email=current_user.tid,
        previous_status=previous_status,
        new_status='deleted',
        reason=reason
    )
    
    db.session.add(audit)
    db.session.delete(model)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'model_id': model_id,
        'action': 'rejected_and_deleted',
        'reason': reason
    })


@bp.route('/models/<int:model_id>/retire', methods=['POST'])
@login_required
@admin_required
def retire_model(model_id):
    """Retire an approved inference model."""
    model = db.session.get(SOHInferenceModel, model_id)
    
    if not model:
        return jsonify({'error': 'Model not found'}), 404
    
    if model.status != InferenceModelStatus.APPROVED.value:
        return jsonify({'error': 'Can only retire approved models'}), 400
    
    data = request.get_json() or {}
    reason = data.get('reason', '').strip()
    
    if not reason:
        return jsonify({'error': 'Retirement reason required'}), 400
    
    # Update model status
    previous_status = model.status
    model.status = InferenceModelStatus.RETIRED.value
    model.retired_by_user_id = current_user.id
    model.retired_at = datetime.utcnow()
    model.retirement_reason = reason
    
    # Create audit log
    audit = InferenceModelAudit(
        model_id=model.id,
        action='retire',
        user_id=current_user.id,
        user_email=current_user.tid,
        previous_status=previous_status,
        new_status=model.status,
        reason=reason
    )
    
    db.session.add(audit)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'model_id': model.id,
        'version': model.version,
        'status': model.status,
        'retired_at': model.retired_at.isoformat()
    })


@bp.route('/models/<int:model_id>/audit', methods=['GET'])
@login_required
@admin_required
def get_model_audit(model_id):
    """Get audit log for a model."""
    model = db.session.get(SOHInferenceModel, model_id)
    
    if not model:
        return jsonify({'error': 'Model not found'}), 404
    
    audits = db.session.query(InferenceModelAudit).filter(
        InferenceModelAudit.model_id == model_id
    ).order_by(InferenceModelAudit.created_at.desc()).all()
    
    return jsonify({
        'model_id': model_id,
        'model_version': model.version,
        'audit_log': [
            {
                'id': a.id,
                'action': a.action,
                'user_email': a.user_email,
                'previous_status': a.previous_status,
                'new_status': a.new_status,
                'reason': a.reason,
                'created_at': a.created_at.isoformat() if a.created_at else None
            }
            for a in audits
        ]
    })
