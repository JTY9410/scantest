"""Add SOH inference models with versioned approval workflow.

Revision ID: 20261117_130000
Revises: 20261117_120000
Create Date: 2026-11-17 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20261117_130000'
down_revision = '20261117_120000'
branch_labels = None
depends_on = None


def upgrade():
    # ### SOH Inference Models ###
    
    # soh_inference_models table
    op.create_table('soh_inference_models',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('version', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('scope_maker', sa.String(length=50), nullable=True),
        sa.Column('scope_model', sa.String(length=100), nullable=True),
        sa.Column('model_type', sa.String(length=50), nullable=False),
        sa.Column('model_config', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('model_weights', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('training_sample_count', sa.Integer(), nullable=True),
        sa.Column('training_metrics', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('validation_metrics', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('backtest_metrics', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('feature_names', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('feature_importance', postgresql.JSON(astext_type=sa.Text()), nullable=True),
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
    op.create_index('idx_soh_inference_models_status', 'soh_inference_models', ['status'], unique=False)
    op.create_index('idx_soh_inference_models_scope', 'soh_inference_models', ['scope_maker', 'scope_model'], unique=False)
    
    # soh_inferences table
    op.create_table('soh_inferences',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('scan_id', sa.Integer(), nullable=False),
        sa.Column('model_id', sa.Integer(), nullable=False),
        sa.Column('estimated_soh', sa.Float(), nullable=False),
        sa.Column('soh_range_min', sa.Float(), nullable=True),
        sa.Column('soh_range_max', sa.Float(), nullable=True),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('inference_method', sa.String(length=50), nullable=False),
        sa.Column('input_features', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('calculation_details', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('resolution_chain', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['scan_id'], ['scans.id'], ),
        sa.ForeignKeyConstraint(['model_id'], ['soh_inference_models.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_soh_inferences_scan', 'soh_inferences', ['scan_id'], unique=False)
    op.create_index('idx_soh_inferences_model', 'soh_inferences', ['model_id'], unique=False)
    
    # soh_inference_model_audit table
    op.create_table('soh_inference_model_audit',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('model_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('user_email', sa.String(length=255), nullable=True),
        sa.Column('previous_status', sa.String(length=20), nullable=True),
        sa.Column('new_status', sa.String(length=20), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('changes', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['model_id'], ['soh_inference_models.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_soh_inference_audit_model', 'soh_inference_model_audit', ['model_id'], unique=False)
    op.create_index('idx_soh_inference_audit_action', 'soh_inference_model_audit', ['action'], unique=False)


def downgrade():
    op.drop_index('idx_soh_inference_audit_action', table_name='soh_inference_model_audit')
    op.drop_index('idx_soh_inference_audit_model', table_name='soh_inference_model_audit')
    op.drop_table('soh_inference_model_audit')
    
    op.drop_index('idx_soh_inferences_model', table_name='soh_inferences')
    op.drop_index('idx_soh_inferences_scan', table_name='soh_inferences')
    op.drop_table('soh_inferences')
    
    op.drop_index('idx_soh_inference_models_scope', table_name='soh_inference_models')
    op.drop_index('idx_soh_inference_models_status', table_name='soh_inference_models')
    op.drop_table('soh_inference_models')
