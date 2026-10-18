"""지식 명령·수식·고장코드에 세부 명칭을 둔다.

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-10-18 13:20:00.000000

"""
import sqlalchemy as sa
from alembic import op


revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("knowledge_commands", sa.Column("detail_name", sa.String(length=200), nullable=True))
    op.add_column("knowledge_formulas", sa.Column("detail_name", sa.String(length=200), nullable=True))
    op.add_column("knowledge_dtcs", sa.Column("detail_name", sa.String(length=200), nullable=True))


def downgrade():
    op.drop_column("knowledge_dtcs", "detail_name")
    op.drop_column("knowledge_formulas", "detail_name")
    op.drop_column("knowledge_commands", "detail_name")
