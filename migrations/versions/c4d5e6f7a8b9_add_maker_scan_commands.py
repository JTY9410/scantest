"""add maker_scan_commands

제조사·차종에서 응답한 읽기 명령을 다음 스캔에 다시 쓴다.

Revision ID: c4d5e6f7a8b9
Revises: a1b2c3d4e5f6
Create Date: 2026-10-18 09:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c4d5e6f7a8b9"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "maker_scan_commands",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("maker", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("header", sa.String(length=8), nullable=True),
        sa.Column("command", sa.String(length=32), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("last_scan_id", sa.BigInteger(), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_maker_scan_commands")),
    )
    with op.batch_alter_table("maker_scan_commands", schema=None) as batch_op:
        batch_op.create_index("ix_maker_scan_commands_maker", ["maker"], unique=False)
        batch_op.create_index(
            "uq_maker_scan_commands", ["maker", "model", "header", "command"],
            unique=True, postgresql_nulls_not_distinct=True,
        )
    op.execute('ALTER TABLE "maker_scan_commands" ENABLE ROW LEVEL SECURITY')


def downgrade():
    op.drop_table("maker_scan_commands")
