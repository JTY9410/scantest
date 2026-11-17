"""ML learning 관리자 페이지."""

from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required

from app.modules.auth.access import admin_required
from app.extensions import db
from app.modules.ml_learning.models import (
    MLModelRun, MLActiveModel, MLDecoderProposal, MLConsistencyScore
)

bp = Blueprint("ml_admin", __name__, url_prefix="/admin/ml")


@bp.get("/models")
@login_required
@admin_required
def models():
    """학습된 모델 목록."""
    models_list = db.session.query(MLModelRun).order_by(MLModelRun.started_at.desc()).limit(100).all()
    return render_template("admin/ml/models.html", models=models_list)


@bp.post("/models/<int:model_id>/promote")
@login_required
@admin_required
def promote_model(model_id):
    """모델을 active로 승격."""
    model = db.session.get(MLModelRun, model_id)
    if not model:
        flash("모델을 찾을 수 없습니다.", "error")
        return redirect(url_for("ml_admin.models"))
    
    if model.status != 'completed':
        flash("completed 상태인 모델만 승격할 수 있습니다.", "error")
        return redirect(url_for("ml_admin.models"))
    
    # Create or update active model record
    active = db.session.query(MLActiveModel).first()
    if not active:
        active = MLActiveModel(model_run_id=model.id, activated_by='admin')
        db.session.add(active)
    else:
        active.model_run_id = model.id
        active.activated_at = db.func.now()
    
    model.promoted_to_active = True
    db.session.commit()
    
    flash(f"모델 {model.id}를 활성화했습니다.", "success")
    return redirect(url_for("ml_admin.models"))


@bp.get("/anomalies")
@login_required
@admin_required
def anomalies():
    """이상 탐지 결과 목록 (placeholder - feature not yet implemented)."""
    # MLAnomalyDetection model doesn't exist yet - return empty list
    detections = []
    return render_template("admin/ml/anomalies.html", detections=detections)


@bp.get("/decoder-proposals")
@login_required
@admin_required
def decoder_proposals():
    """디코더 제안 목록."""
    proposals = db.session.query(MLDecoderProposal).filter(
        MLDecoderProposal.status == 'pending'
    ).order_by(MLDecoderProposal.confidence.desc()).limit(100).all()
    return render_template("admin/ml/decoder_proposals.html", proposals=proposals)


@bp.post("/decoder-proposals/<int:proposal_id>/approve")
@login_required
@admin_required
def approve_proposal(proposal_id):
    """디코더 제안 승인."""
    proposal = db.session.get(MLDecoderProposal, proposal_id)
    if not proposal:
        flash("제안을 찾을 수 없습니다.", "error")
        return redirect(url_for("ml_admin.decoder_proposals"))
    
    proposal.status = 'approved'
    db.session.commit()
    
    flash(f"CAN ID {proposal.can_id} 제안을 승인했습니다.", "success")
    return redirect(url_for("ml_admin.decoder_proposals"))


@bp.get("/feedback")
@login_required
@admin_required
def feedback_list():
    """피드백 목록 (placeholder - feature not yet implemented)."""
    # MLFeedback model doesn't exist yet - return empty list
    feedbacks = []
    return render_template("admin/ml/feedback.html", feedbacks=feedbacks)
