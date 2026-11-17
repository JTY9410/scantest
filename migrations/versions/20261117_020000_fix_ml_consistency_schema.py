"""Fix ml_consistency_scores schema mismatch

Revision ID: 20261117_020000
Revises: 20261116_160000
Create Date: 2026-11-17 02:00:00.000000

DEFECT 3 FIX: The ORM model uses `issues` but the table has `issues_detected`.
The ORM also has sufficiency columns that don't exist in the table.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20261117_020000'
down_revision = '20261116_160000'
branch_labels = None
depends_on = None


def upgrade():
    # Rename issues_detected to issues
    op.alter_column('ml_consistency_scores', 'issues_detected',
                    new_column_name='issues',
                    existing_type=postgresql.JSON(astext_type=sa.Text()),
                    existing_nullable=True)
    
    # Add sufficiency columns
    op.add_column('ml_consistency_scores', sa.Column('sufficient_data', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('ml_consistency_scores', sa.Column('min_samples_required', sa.Integer(), nullable=True))
    op.add_column('ml_consistency_scores', sa.Column('actual_samples', sa.Integer(), nullable=True))


def downgrade():
    # Remove sufficiency columns
    op.drop_column('ml_consistency_scores', 'actual_samples')
    op.drop_column('ml_consistency_scores', 'min_samples_required')
    op.drop_column('ml_consistency_scores', 'sufficient_data')
    
    # Rename issues back to issues_detected
    op.alter_column('ml_consistency_scores', 'issues',
                    new_column_name='issues_detected',
                    existing_type=postgresql.JSON(astext_type=sa.Text()),
                    existing_nullable=True)
