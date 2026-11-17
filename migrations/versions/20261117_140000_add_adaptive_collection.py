"""Add adaptive data collection with signal usage tracking.

Revision ID: 20261117_140000
Revises: 20261117_130000
Create Date: 2026-11-17 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20261117_140000'
down_revision = '20261117_130000'
branch_labels = None
depends_on = None


def upgrade():
    # ### Adaptive Collection Tables ###
    
    # signal_usage_tracking table
    op.create_table('signal_usage_tracking',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('maker', sa.String(length=50), nullable=False),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('signal_name', sa.String(length=100), nullable=False),
        sa.Column('requested_count', sa.Integer(), nullable=False),
        sa.Column('responded_count', sa.Integer(), nullable=False),
        sa.Column('decoded_count', sa.Integer(), nullable=False),
        sa.Column('used_for_report', sa.Integer(), nullable=False),
        sa.Column('used_for_soh', sa.Integer(), nullable=False),
        sa.Column('used_for_verdict', sa.Integer(), nullable=False),
        sa.Column('used_for_ml', sa.Integer(), nullable=False),
        sa.Column('used_for_inference', sa.Integer(), nullable=False),
        sa.Column('total_response_time_ms', sa.Integer(), nullable=False),
        sa.Column('first_seen', sa.DateTime(), nullable=False),
        sa.Column('last_seen', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_signal_usage_maker_model', 'signal_usage_tracking', ['maker', 'model'], unique=False)
    op.create_index('idx_signal_usage_signal', 'signal_usage_tracking', ['signal_name'], unique=False)
    
    # collection_profiles table
    op.create_table('collection_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('version', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('scope_maker', sa.String(length=50), nullable=False),
        sa.Column('scope_model', sa.String(length=100), nullable=True),
        sa.Column('signals_to_skip', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('skip_reason', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('generation_method', sa.String(length=50), nullable=False),
        sa.Column('learning_sample_count', sa.Integer(), nullable=True),
        sa.Column('learning_metrics', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('estimated_time_saved_ms', sa.Integer(), nullable=True),
        sa.Column('estimated_signals_reduced', sa.Integer(), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('approved_by_user_id', sa.Integer(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('approval_notes', sa.Text(), nullable=True),
        sa.Column('retired_by_user_id', sa.Integer(), nullable=True),
        sa.Column('retired_at', sa.DateTime(), nullable=True),
        sa.Column('retirement_reason', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['approved_by_user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['retired_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('version')
    )
    op.create_index('idx_collection_profiles_status', 'collection_profiles', ['status'], unique=False)
    op.create_index('idx_collection_profiles_scope', 'collection_profiles', ['scope_maker', 'scope_model'], unique=False)
    
    # collection_profile_audit table
    op.create_table('collection_profile_audit',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('user_email', sa.String(length=255), nullable=True),
        sa.Column('previous_status', sa.String(length=20), nullable=True),
        sa.Column('new_status', sa.String(length=20), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('changes', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['profile_id'], ['collection_profiles.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_collection_profile_audit_profile', 'collection_profile_audit', ['profile_id'], unique=False)
    op.create_index('idx_collection_profile_audit_action', 'collection_profile_audit', ['action'], unique=False)
    
    # protected_signals table
    op.create_table('protected_signals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('signal_name', sa.String(length=100), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('added_by_user_id', sa.Integer(), nullable=True),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['added_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('signal_name')
    )
    
    # full_scan_samples table
    op.create_table('full_scan_samples',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scan_id', sa.Integer(), nullable=False),
        sa.Column('maker', sa.String(length=50), nullable=False),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('reason', sa.String(length=50), nullable=False),
        sa.Column('skipped_signals_used', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('new_signals_found', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['scan_id'], ['scans.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('scan_id')
    )
    op.create_index('idx_full_scan_samples_maker_model', 'full_scan_samples', ['maker', 'model'], unique=False)


def downgrade():
    op.drop_index('idx_full_scan_samples_maker_model', table_name='full_scan_samples')
    op.drop_table('full_scan_samples')
    
    op.drop_table('protected_signals')
    
    op.drop_index('idx_collection_profile_audit_action', table_name='collection_profile_audit')
    op.drop_index('idx_collection_profile_audit_profile', table_name='collection_profile_audit')
    op.drop_table('collection_profile_audit')
    
    op.drop_index('idx_collection_profiles_scope', table_name='collection_profiles')
    op.drop_index('idx_collection_profiles_status', table_name='collection_profiles')
    op.drop_table('collection_profiles')
    
    op.drop_index('idx_signal_usage_signal', table_name='signal_usage_tracking')
    op.drop_index('idx_signal_usage_maker_model', table_name='signal_usage_tracking')
    op.drop_table('signal_usage_tracking')
