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
    models_list = db.session.query(MLModel).order_by(MLModel.created_at.desc()).limit(100).all()
    return render_template("admin/ml/models.html", models=models_list)


@bp.post("/models/<int:model_id>/promote")
@login_required
@admin_required
def promote_model(model_id):
    """모델을 active로 승격."""
    model = db.session.get(MLModel, model_id)
    if not model:
        flash("모델을 찾을 수 없습니다.", "error")
        return redirect(url_for("ml_admin.models"))
    
    if model.status != 'candidate':
        flash("candidate 상태인 모델만 승격할 수 있습니다.", "error")
        return redirect(url_for("ml_admin.models"))
    
    # 기존 active 모델을 retired로
    old_active = db.session.query(MLModel).filter_by(
        model_type=model.model_type,
        status='active'
    ).first()
    
    if old_active:
        old_active.status = 'retired'
    
    model.status = 'active'
    db.session.commit()
    
    flash(f"모델 {model.model_version}을 활성화했습니다.", "success")
    return redirect(url_for("ml_admin.models"))


@bp.get("/anomalies")
@login_required
@admin_required
def anomalies():
    """이상 탐지 결과 목록."""
    detections = db.session.query(MLAnomalyDetection).filter(
        MLAnomalyDetection.is_anomaly == True
    ).order_by(MLAnomalyDetection.created_at.desc()).limit(100).all()
    return render_template("admin/ml/anomalies.html", detections=detections)


@bp.get("/decoder-proposals")
@login_required
@admin_required
def decoder_proposals():
    """디코더 제안 목록."""
    proposals = db.session.query(MLDecoderProposal).filter(
        MLDecoderProposal.status == 'pending'
    ).order_by(MLDecoderProposal.confidence_score.desc()).limit(100).all()
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
    """피드백 목록."""
    feedbacks = db.session.query(MLFeedback).order_by(MLFeedback.created_at.desc()).limit(100).all()
    return render_template("admin/ml/feedback.html", feedbacks=feedbacks)
