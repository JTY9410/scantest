"""Adaptive collection admin routes (v2.2.24 Phase 3)."""

from flask import Blueprint, request, jsonify, render_template
from flask_login import current_user
from datetime import datetime, timezone

from app.extensions import db
from app.modules.auth.access import admin_required, login_required
from app.modules.adaptive_collection.models import (
    CollectionProfile, CollectionProfileAudit, SignalWhitelist, SignalWhitelistAudit,
    ProfileStatus
)
from app.modules.adaptive_collection.profile_generator import generate_collection_profile, check_reenable_signals


bp = Blueprint('adaptive_collection', __name__, url_prefix='/admin/adaptive')


@bp.route('/profiles', methods=['GET'])
@login_required
@admin_required
def list_profiles():
    """List collection profiles."""
    profiles = db.session.query(CollectionProfile).order_by(CollectionProfile.created_at.desc()).all()
    return render_template('adaptive_collection/profiles_list.html', profiles=profiles)


@bp.route('/profiles/<int:profile_id>', methods=['GET'])
@login_required
@admin_required
def view_profile(profile_id):
    """View collection profile detail."""
    profile = db.session.get(CollectionProfile, profile_id)
    if not profile:
        return "Profile not found", 404
    
    return render_template('adaptive_collection/profile_detail.html', profile=profile)


@bp.route('/profiles/<int:profile_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_profile(profile_id):
    """Approve a collection profile."""
    profile = db.session.get(CollectionProfile, profile_id)
    
    if not profile:
        return jsonify({'error': 'Profile not found'}), 404
    
    if profile.status not in [ProfileStatus.DRAFT.value, ProfileStatus.PENDING_APPROVAL.value]:
        return jsonify({'error': 'Only draft or pending profiles can be approved'}), 400
    
    data = request.get_json() or {}
    notes = data.get('notes', '').strip()
    
    if not notes:
        return jsonify({'error': 'Approval notes required'}), 400
    
    # Approve profile
    previous_status = profile.status
    profile.status = ProfileStatus.APPROVED.value
    profile.approved_by_user_id = current_user.id
    profile.approved_at = datetime.now(timezone.utc)
    profile.approval_notes = notes
    
    # Create audit log
    audit = CollectionProfileAudit(
        profile_id=profile.id,
        action='approve',
        user_id=current_user.id,
        user_email=current_user.email or current_user.tid,
        previous_status=previous_status,
        new_status=ProfileStatus.APPROVED.value,
        reason=notes
    )
    
    db.session.add(audit)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'profile_id': profile.id,
        'version': profile.version,
        'status': profile.status
    })


@bp.route('/profiles/<int:profile_id>/rollback', methods=['POST'])
@login_required
@admin_required
def rollback_profile(profile_id):
    """Rollback an approved profile."""
    profile = db.session.get(CollectionProfile, profile_id)
    
    if not profile:
        return jsonify({'error': 'Profile not found'}), 404
    
    if profile.status != ProfileStatus.APPROVED.value:
        return jsonify({'error': 'Only approved profiles can be rolled back'}), 400
    
    data = request.get_json() or {}
    reason = data.get('reason', '').strip()
    
    if not reason:
        return jsonify({'error': 'Rollback reason required'}), 400
    
    # Rollback profile
    previous_status = profile.status
    profile.status = ProfileStatus.ROLLED_BACK.value
    profile.rolled_back_by_user_id = current_user.id
    profile.rolled_back_at = datetime.now(timezone.utc)
    profile.rollback_reason = reason
    
    # Create audit log
    audit = CollectionProfileAudit(
        profile_id=profile.id,
        action='rollback',
        user_id=current_user.id,
        user_email=current_user.email or current_user.tid,
        previous_status=previous_status,
        new_status=ProfileStatus.ROLLED_BACK.value,
        reason=reason
    )
    
    db.session.add(audit)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'profile_id': profile.id,
        'version': profile.version,
        'status': profile.status
    })


@bp.route('/whitelist', methods=['GET'])
@login_required
@admin_required
def list_whitelist():
    """List signal whitelist."""
    whitelist = db.session.query(SignalWhitelist).filter_by(is_active=True).all()
    return render_template('adaptive_collection/whitelist.html', whitelist=whitelist)


@bp.route('/whitelist', methods=['POST'])
@login_required
@admin_required
def add_to_whitelist():
    """Add signal to whitelist."""
    data = request.get_json() or {}
    signal_id = data.get('signal_identifier', '').strip()
    reason = data.get('reason', '').strip()
    description = data.get('description', '').strip()
    
    if not signal_id or not reason:
        return jsonify({'error': 'Signal identifier and reason required'}), 400
    
    # Check if already exists
    existing = db.session.query(SignalWhitelist).filter_by(signal_identifier=signal_id).first()
    if existing:
        return jsonify({'error': 'Signal already in whitelist'}), 400
    
    # Add to whitelist
    whitelist_entry = SignalWhitelist(
        signal_identifier=signal_id,
        reason=reason,
        description=description,
        added_by_user_id=current_user.id
    )
    
    db.session.add(whitelist_entry)
    db.session.flush()
    
    # Create audit log
    audit = SignalWhitelistAudit(
        whitelist_id=whitelist_entry.id,
        signal_identifier=signal_id,
        action='add',
        user_id=current_user.id,
        user_email=current_user.email or current_user.tid,
        reason=f"Added: {reason}"
    )
    
    db.session.add(audit)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'whitelist_id': whitelist_entry.id,
        'signal_identifier': signal_id
    })


@bp.route('/whitelist/<int:whitelist_id>', methods=['DELETE'])
@login_required
@admin_required
def remove_from_whitelist(whitelist_id):
    """Remove signal from whitelist."""
    entry = db.session.get(SignalWhitelist, whitelist_id)
    
    if not entry:
        return jsonify({'error': 'Whitelist entry not found'}), 404
    
    data = request.get_json() or {}
    reason = data.get('reason', '').strip()
    
    if not reason:
        return jsonify({'error': 'Removal reason required'}), 400
    
    # Create audit log before removal
    audit = SignalWhitelistAudit(
        whitelist_id=entry.id,
        signal_identifier=entry.signal_identifier,
        action='remove',
        user_id=current_user.id,
        user_email=current_user.email or current_user.tid,
        reason=reason
    )
    
    db.session.add(audit)
    
    # Mark as inactive (soft delete)
    entry.is_active = False
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'whitelist_id': whitelist_id
    })


@bp.route('/profiles/<int:profile_id>/reenable-check', methods=['GET'])
@login_required
@admin_required
def check_reenable(profile_id):
    """Check for signals that should be re-enabled."""
    profile = db.session.get(CollectionProfile, profile_id)
    
    if not profile:
        return jsonify({'error': 'Profile not found'}), 404
    
    proposals = check_reenable_signals(
        manufacturer=profile.manufacturer,
        model=profile.model,
        profile_id=profile.id
    )
    
    return jsonify({
        'profile_id': profile.id,
        'reenable_proposals': proposals
    })
