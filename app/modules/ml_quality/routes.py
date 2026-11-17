"""Admin routes for ML quality analysis (v2.2.22 Phase 1)."""
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import current_user
from sqlalchemy import select, desc

from app.extensions import db
from app.modules.auth.decorators import admin_required
from app.modules.ml_quality.models import ImprovementProposal, ProposalAuditLog, VersionedConfig
from app.modules.ml_quality.proposal_generator import generate_proposals


bp = Blueprint("ml_quality", __name__, url_prefix="/admin/ml/quality")


@bp.route("/proposals")
@admin_required
def proposal_list():
    """List improvement proposals."""
    status = request.args.get("status")
    manufacturer = request.args.get("manufacturer")
    
    query = select(ImprovementProposal).order_by(desc(ImprovementProposal.created_at))
    
    if status:
        query = query.where(ImprovementProposal.status == status)
    if manufacturer:
        query = query.where(ImprovementProposal.manufacturer == manufacturer)
    
    proposals = db.session.execute(query).scalars().all()
    
    return render_template("ml_quality/proposals.html", proposals=proposals)


@bp.route("/proposals/<int:proposal_id>")
@admin_required
def proposal_detail(proposal_id):
    """Show proposal details."""
    proposal = db.session.get(ImprovementProposal, proposal_id)
    if not proposal:
        flash("제안을 찾을 수 없습니다", "error")
        return redirect(url_for("ml_quality.proposal_list"))
    
    return render_template("ml_quality/proposal_detail.html", proposal=proposal)


@bp.route("/proposals/<int:proposal_id>/approve", methods=["POST"])
@admin_required
def approve_proposal(proposal_id):
    """Approve a proposal."""
    proposal = db.session.get(ImprovementProposal, proposal_id)
    if not proposal:
        return jsonify({"error": "제안을 찾을 수 없습니다"}), 404
    
    if proposal.status != "pending":
        return jsonify({"error": f"상태가 pending이 아닙니다 (현재: {proposal.status})"}), 400
    
    reason = request.form.get("reason")
    
    # Update status
    previous_status = proposal.status
    proposal.status = "approved"
    proposal.updated_at = datetime.now(timezone.utc)
    
    # Create audit log
    audit = ProposalAuditLog(
        proposal_id=proposal.id,
        action="approve",
        user_id=current_user.id,
        user_email=current_user.email,
        reason=reason,
        previous_status=previous_status
    )
    db.session.add(audit)
    
    # Apply config delta to versioned_configs
    _apply_config_delta(proposal)
    
    db.session.commit()
    
    flash(f"제안 #{proposal.id}이 승인되었습니다", "success")
    return redirect(url_for("ml_quality.proposal_detail", proposal_id=proposal.id))


@bp.route("/proposals/<int:proposal_id>/reject", methods=["POST"])
@admin_required
def reject_proposal(proposal_id):
    """Reject a proposal."""
    proposal = db.session.get(ImprovementProposal, proposal_id)
    if not proposal:
        return jsonify({"error": "제안을 찾을 수 없습니다"}), 404
    
    if proposal.status != "pending":
        return jsonify({"error": f"상태가 pending이 아닙니다 (현재: {proposal.status})"}), 400
    
    reason = request.form.get("reason")
    if not reason:
        return jsonify({"error": "거부 사유를 입력하세요"}), 400
    
    # Update status
    previous_status = proposal.status
    proposal.status = "rejected"
    proposal.updated_at = datetime.now(timezone.utc)
    
    # Create audit log
    audit = ProposalAuditLog(
        proposal_id=proposal.id,
        action="reject",
        user_id=current_user.id,
        user_email=current_user.email,
        reason=reason,
        previous_status=previous_status
    )
    db.session.add(audit)
    
    db.session.commit()
    
    flash(f"제안 #{proposal.id}이 거부되었습니다", "warning")
    return redirect(url_for("ml_quality.proposal_detail", proposal_id=proposal.id))


@bp.route("/proposals/<int:proposal_id>/rollback", methods=["POST"])
@admin_required
def rollback_proposal(proposal_id):
    """Rollback an approved proposal."""
    proposal = db.session.get(ImprovementProposal, proposal_id)
    if not proposal:
        return jsonify({"error": "제안을 찾을 수 없습니다"}), 404
    
    if proposal.status != "approved":
        return jsonify({"error": f"승인된 제안만 롤백할 수 있습니다 (현재: {proposal.status})"}), 400
    
    reason = request.form.get("reason")
    if not reason:
        return jsonify({"error": "롤백 사유를 입력하세요"}), 400
    
    # Update status
    previous_status = proposal.status
    proposal.status = "rolled_back"
    proposal.updated_at = datetime.now(timezone.utc)
    
    # Deactivate configs
    for config in proposal.configs:
        if config.active:
            config.active = False
            config.deactivated_at = datetime.now(timezone.utc)
    
    # Create audit log
    audit = ProposalAuditLog(
        proposal_id=proposal.id,
        action="rollback",
        user_id=current_user.id,
        user_email=current_user.email,
        reason=reason,
        previous_status=previous_status
    )
    db.session.add(audit)
    
    db.session.commit()
    
    flash(f"제안 #{proposal.id}이 롤백되었습니다", "info")
    return redirect(url_for("ml_quality.proposal_detail", proposal_id=proposal.id))


@bp.route("/proposals/generate", methods=["POST"])
@admin_required
def generate_new_proposals():
    """Generate new proposals based on recent quality signals."""
    manufacturer = request.form.get("manufacturer")
    model = request.form.get("model")
    
    try:
        proposals = generate_proposals(manufacturer, model)
        
        for proposal in proposals:
            db.session.add(proposal)
        
        db.session.commit()
        
        flash(f"{len(proposals)}개의 새 제안이 생성되었습니다", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"제안 생성 실패: {str(e)}", "error")
    
    return redirect(url_for("ml_quality.proposal_list"))


def _apply_config_delta(proposal: ImprovementProposal):
    """Apply approved proposal's config delta to versioned_configs."""
    delta = proposal.config_delta
    config_type = proposal.proposal_type
    
    # Create versioned config entry
    config = VersionedConfig(
        config_type=config_type,
        manufacturer=proposal.manufacturer,
        model=proposal.model,
        config_key=f"{config_type}_{proposal.id}",
        config_value=delta,
        proposal_id=proposal.id,
        active=True,
        activated_at=datetime.now(timezone.utc)
    )
    
    db.session.add(config)
