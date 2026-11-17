"""add ML quality analysis (v2.2.22 Phase 1)

Revision ID: 20261117_120000
Revises: 20261117_110000
Create Date: 2026-11-17 12:00:00.000000

Phase 1: Scan error analysis and admin-approval improvement loop.

Tables:
- scan_quality_signals: structured quality signals per scan
- improvement_proposals: ML-driven proposals with evidence and config deltas
- proposal_audit_log: approval/rejection/rollback audit trail
- versioned_configs: runtime config storage for approved proposals
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '20261117_120000'
down_revision = '20261117_110000'
branch_labels = None
depends_on = None


def upgrade():
    # scan_quality_signals: structured quality signals collected after each scan
    op.create_table('scan_quality_signals',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('scan_id', sa.Integer(), nullable=False),
        sa.Column('collected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        # Decode failures
        sa.Column('decode_failures', sa.JSON(), nullable=True),  # {did: reason}
        
        # Unmeasurable items
        sa.Column('unmeasurable_items', sa.JSON(), nullable=True),  # {item: reason}
        
        # Out-of-range values
        sa.Column('out_of_range_values', sa.JSON(), nullable=True),  # {signal: {value, range}}
        
        # SOH reasons
        sa.Column('soh_unavailable_reason', sa.String(200), nullable=True),
        
        # Consistency score
        sa.Column('consistency_score', sa.Numeric(5, 2), nullable=True),
        
        # Excluded steps
        sa.Column('excluded_steps', sa.JSON(), nullable=True),  # [{command, reason}]
        
        # DTC status-unknown counts
        sa.Column('dtc_status_unknown_count', sa.Integer(), nullable=True),
        
        # Contradictions
        sa.Column('contradictions', sa.JSON(), nullable=True),  # [{field1, field2, reason}]
        
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['scan_id'], ['scans.id'], ondelete='CASCADE'),
        sa.Index('ix_scan_quality_signals_scan_id', 'scan_id'),
        sa.Index('ix_scan_quality_signals_collected_at', 'collected_at')
    )
    
    # improvement_proposals: ML-driven proposals for config improvements
    op.create_table('improvement_proposals',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        # Status: pending, approved, rejected, rolled_back
        sa.Column('status', sa.String(20), nullable=False),
        
        # Scope
        sa.Column('manufacturer', sa.String(50), nullable=True),
        sa.Column('model', sa.String(100), nullable=True),
        
        # Proposal type (decoder_mapping, threshold, soh_parameter, etc.)
        sa.Column('proposal_type', sa.String(50), nullable=False),
        
        # Evidence (scan ids, counts, patterns)
        sa.Column('evidence', sa.JSON(), nullable=False),
        
        # Proposed change as structured config delta
        sa.Column('config_delta', sa.JSON(), nullable=False),
        
        # Expected effect
        sa.Column('expected_effect', sa.Text(), nullable=True),
        
        # Generation method (rule_based or ai_assisted)
        sa.Column('generation_method', sa.String(20), nullable=False),
        
        # AI metadata (only if ai_assisted)
        sa.Column('ai_metadata', sa.JSON(), nullable=True),
        
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'rolled_back')", name='ck_proposal_status_valid'),
        sa.CheckConstraint("generation_method IN ('rule_based', 'ai_assisted')", name='ck_generation_method_valid'),
        sa.Index('ix_improvement_proposals_status', 'status'),
        sa.Index('ix_improvement_proposals_manufacturer', 'manufacturer'),
        sa.Index('ix_improvement_proposals_model', 'model')
    )
    
    # proposal_audit_log: audit trail for proposal lifecycle
    op.create_table('proposal_audit_log',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('proposal_id', sa.BigInteger(), nullable=False),
        sa.Column('action', sa.String(20), nullable=False),  # approve, reject, rollback
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('user_email', sa.String(255), nullable=True),
        sa.Column('action_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('previous_status', sa.String(20), nullable=True),
        
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['proposal_id'], ['improvement_proposals.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.CheckConstraint("action IN ('approve', 'reject', 'rollback')", name='ck_audit_action_valid'),
        sa.Index('ix_proposal_audit_log_proposal_id', 'proposal_id'),
        sa.Index('ix_proposal_audit_log_action_at', 'action_at')
    )
    
    # versioned_configs: runtime config storage for approved proposals
    op.create_table('versioned_configs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('config_type', sa.String(50), nullable=False),
        sa.Column('manufacturer', sa.String(50), nullable=True),
        sa.Column('model', sa.String(100), nullable=True),
        sa.Column('config_key', sa.String(100), nullable=False),
        sa.Column('config_value', sa.JSON(), nullable=False),
        sa.Column('proposal_id', sa.BigInteger(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True),
        
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['proposal_id'], ['improvement_proposals.id'], ondelete='SET NULL'),
        sa.Index('ix_versioned_configs_active', 'active'),
        sa.Index('ix_versioned_configs_type_mfg_model', 'config_type', 'manufacturer', 'model'),
        sa.Index('ix_versioned_configs_type_key', 'config_type', 'config_key')
    )


def downgrade():
    op.drop_table('versioned_configs')
    op.drop_table('proposal_audit_log')
    op.drop_table('improvement_proposals')
    op.drop_table('scan_quality_signals')
