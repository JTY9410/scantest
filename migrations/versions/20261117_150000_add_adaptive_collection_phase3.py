"""Add adaptive data collection (v2.2.24 Phase 3)

Revision ID: 20261117_150000
Revises: 20261117_140000
Create Date: 2026-11-17 15:00:00.000000

Phase 3: Adaptive data collection
- Track per-signal usage per manufacturer and model
- Collection profiles with versioning and approval workflow
- Protected whitelist of required signals
- Automatic full-scan sampling every Nth scan
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '20261117_150000'
down_revision = '20261117_130000'
branch_labels = None
depends_on = None


def upgrade():
    # signal_usage_stats: Track per-signal usage statistics
    op.create_table('signal_usage_stats',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column('manufacturer', sa.String(50), nullable=False),
        sa.Column('model', sa.String(100), nullable=True),  # NULL = manufacturer-level
        sa.Column('signal_identifier', sa.String(200), nullable=False),  # e.g., "did:2101"
        
        # Usage counters
        sa.Column('requested_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('responded_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('decoded_count', sa.Integer(), nullable=False, server_default='0'),
        
        # Usage in different contexts (bitflags or JSON)
        sa.Column('used_in_report_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('used_in_soh_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('used_in_verdict_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('used_in_ml_quality_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('used_in_soh_inference_count', sa.Integer(), nullable=False, server_default='0'),
        
        # Performance metrics
        sa.Column('avg_response_time_ms', sa.Float(), nullable=True),
        sa.Column('total_response_time_ms', sa.BigInteger(), nullable=False, server_default='0'),
        
        # Metadata
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        sa.UniqueConstraint('manufacturer', 'model', 'signal_identifier', name='uq_signal_usage_scope'),
        sa.Index('idx_signal_usage_manufacturer', 'manufacturer'),
        sa.Index('idx_signal_usage_model', 'manufacturer', 'model'),
        sa.Index('idx_signal_usage_signal', 'signal_identifier')
    )
    
    # collection_profiles: Versioned collection profiles
    op.create_table('collection_profiles',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column('version', sa.String(50), nullable=False, unique=True),
        sa.Column('status', sa.String(20), nullable=False),  # draft, pending_approval, approved, rolled_back
        
        # Scope
        sa.Column('manufacturer', sa.String(50), nullable=False),
        sa.Column('model', sa.String(100), nullable=True),  # NULL = manufacturer-level
        
        # Configuration
        sa.Column('skip_threshold_scans', sa.Integer(), nullable=False, server_default='20'),  # N scans
        sa.Column('full_rescan_interval', sa.Integer(), nullable=False, server_default='10'),  # Every Nth scan
        
        # Profile data
        sa.Column('signals_to_skip', postgresql.JSON(astext_type=sa.Text()), nullable=False),  # List of signal identifiers
        sa.Column('generation_evidence', postgresql.JSON(astext_type=sa.Text()), nullable=True),  # Stats that led to this profile
        
        # Approval workflow
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('approved_by_user_id', sa.Integer(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approval_notes', sa.Text(), nullable=True),
        sa.Column('rolled_back_by_user_id', sa.Integer(), nullable=True),
        sa.Column('rolled_back_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rollback_reason', sa.Text(), nullable=True),
        
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['approved_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['rolled_back_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.CheckConstraint("status IN ('draft', 'pending_approval', 'approved', 'rolled_back')", name='ck_profile_status_valid'),
        sa.Index('idx_collection_profiles_status', 'status'),
        sa.Index('idx_collection_profiles_scope', 'manufacturer', 'model')
    )
    
    # collection_profile_audit: Audit log for profile lifecycle
    op.create_table('collection_profile_audit',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column('profile_id', sa.BigInteger(), nullable=True),  # Nullable for deleted profiles
        sa.Column('action', sa.String(50), nullable=False),  # create, approve, rollback, reenable_signal
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('user_email', sa.String(255), nullable=True),
        sa.Column('action_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('previous_status', sa.String(20), nullable=True),
        sa.Column('new_status', sa.String(20), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('changes', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        
        sa.ForeignKeyConstraint(['profile_id'], ['collection_profiles.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.CheckConstraint("action IN ('create', 'approve', 'rollback', 'reenable_signal', 'update')", name='ck_profile_audit_action_valid'),
        sa.Index('idx_collection_profile_audit_profile', 'profile_id'),
        sa.Index('idx_collection_profile_audit_action', 'action')
    )
    
    # signal_whitelist: Protected signals that can never be skipped
    op.create_table('signal_whitelist',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('signal_identifier', sa.String(200), nullable=False, unique=True),
        sa.Column('reason', sa.String(200), nullable=False),  # e.g., "required_for_soh", "required_for_verdict"
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('added_by_user_id', sa.Integer(), nullable=True),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        sa.ForeignKeyConstraint(['added_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.Index('idx_signal_whitelist_active', 'is_active'),
        sa.Index('idx_signal_whitelist_reason', 'reason')
    )
    
    # signal_whitelist_audit: Audit log for whitelist changes
    op.create_table('signal_whitelist_audit',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('whitelist_id', sa.Integer(), nullable=True),
        sa.Column('signal_identifier', sa.String(200), nullable=False),
        sa.Column('action', sa.String(20), nullable=False),  # add, remove, update
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('user_email', sa.String(255), nullable=True),
        sa.Column('action_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('changes', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        
        sa.ForeignKeyConstraint(['whitelist_id'], ['signal_whitelist.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.CheckConstraint("action IN ('add', 'remove', 'update')", name='ck_whitelist_audit_action_valid'),
        sa.Index('idx_signal_whitelist_audit_signal', 'signal_identifier')
    )
    
    # Add fields to scans table to track collection profile usage
    op.add_column('scans', sa.Column('collection_profile_id', sa.BigInteger(), nullable=True))
    op.add_column('scans', sa.Column('was_full_scan', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('scans', sa.Column('force_full_scan', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('scans', sa.Column('is_rescan_sample', sa.Boolean(), nullable=False, server_default='false'))
    
    op.create_foreign_key('fk_scans_collection_profile', 'scans', 'collection_profiles', ['collection_profile_id'], ['id'], ondelete='SET NULL')
    op.create_index('idx_scans_collection_profile', 'scans', ['collection_profile_id'])


def downgrade():
    op.drop_index('idx_scans_collection_profile', table_name='scans')
    op.drop_constraint('fk_scans_collection_profile', 'scans', type_='foreignkey')
    op.drop_column('scans', 'is_rescan_sample')
    op.drop_column('scans', 'force_full_scan')
    op.drop_column('scans', 'was_full_scan')
    op.drop_column('scans', 'collection_profile_id')
    
    op.drop_table('signal_whitelist_audit')
    op.drop_table('signal_whitelist')
    op.drop_table('collection_profile_audit')
    op.drop_table('collection_profiles')
    op.drop_table('signal_usage_stats')
