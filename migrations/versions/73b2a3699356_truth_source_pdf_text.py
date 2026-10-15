"""truth source pdf_text

Revision ID: 73b2a3699356
Revises: b092d83b1947
Create Date: 2026-10-15 06:30:38.377894

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '73b2a3699356'
down_revision = 'b092d83b1947'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(op.f('ck_ground_truth_values_source_valid'), 'ground_truth_values', type_='check')
    op.create_check_constraint(op.f('ck_ground_truth_values_source_valid'), 'ground_truth_values',
                               "source IN ('ai_ocr', 'manual', 'pdf_text')")


def downgrade():
    op.execute("UPDATE ground_truth_values SET source = 'ai_ocr' WHERE source = 'pdf_text'")
    op.drop_constraint(op.f('ck_ground_truth_values_source_valid'), 'ground_truth_values', type_='check')
    op.create_check_constraint(op.f('ck_ground_truth_values_source_valid'), 'ground_truth_values',
                               "source IN ('ai_ocr', 'manual')")
