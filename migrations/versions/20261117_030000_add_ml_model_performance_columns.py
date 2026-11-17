"""Add performance metrics columns to ml_model_runs

Add ORM fields that were defined but never migrated:
- accuracy, precision, recall, f1_score (model performance)
- detailed_metrics (JSON for additional metrics)
- promoted_to_active, promotion_reason (model promotion tracking)
- duration_seconds (training duration)

Revision ID: 20261117_030000
Revises: 20261117_020000
Create Date: 2026-11-17 03:31:19.549229

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261117_030000'
down_revision = '20261117_020000'
branch_labels = None
depends_on = None


def upgrade():
    # Add performance metric columns
    op.add_column('ml_model_runs', sa.Column('accuracy', sa.Float(), nullable=True))
    op.add_column('ml_model_runs', sa.Column('precision', sa.Float(), nullable=True))
    op.add_column('ml_model_runs', sa.Column('recall', sa.Float(), nullable=True))
    op.add_column('ml_model_runs', sa.Column('f1_score', sa.Float(), nullable=True))
    
    # Add detailed metrics JSON
    op.add_column('ml_model_runs', sa.Column('detailed_metrics', sa.JSON(), nullable=True))
    
    # Add promotion tracking
    op.add_column('ml_model_runs', sa.Column('promoted_to_active', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('ml_model_runs', sa.Column('promotion_reason', sa.Text(), nullable=True))
    
    # Add duration
    op.add_column('ml_model_runs', sa.Column('duration_seconds', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('ml_model_runs', 'duration_seconds')
    op.drop_column('ml_model_runs', 'promotion_reason')
    op.drop_column('ml_model_runs', 'promoted_to_active')
    op.drop_column('ml_model_runs', 'detailed_metrics')
    op.drop_column('ml_model_runs', 'f1_score')
    op.drop_column('ml_model_runs', 'recall')
    op.drop_column('ml_model_runs', 'precision')
    op.drop_column('ml_model_runs', 'accuracy')
