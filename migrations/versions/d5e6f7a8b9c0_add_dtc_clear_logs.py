"""add dtc_clear_logs and users.can_clear_dtc

고장코드 지우기(2026-10-18 대표 결정): 권한 컬럼과 감사용 지우기 기록.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-10-18 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("can_clear_dtc", sa.Boolean(), server_default="false", nullable=False))
    op.create_table(
        "dtc_clear_logs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("scan_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("car_no", sa.String(length=20), nullable=True),
        sa.Column("vin", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("targets", sa.JSON(), nullable=False),
        sa.Column("dtcs_before", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("steps", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('issued', 'ok', 'partial', 'failed', 'aborted', 'expired')",
                           name=op.f("ck_dtc_clear_logs_status_valid")),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], name=op.f("fk_dtc_clear_logs_scan_id_scans"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_dtc_clear_logs_user_id_users"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dtc_clear_logs")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_dtc_clear_logs_token_hash")),
    )
    with op.batch_alter_table("dtc_clear_logs", schema=None) as batch_op:
        batch_op.create_index("ix_dtc_clear_logs_scan_id", ["scan_id"], unique=False)
        batch_op.create_index("ix_dtc_clear_logs_user_id", ["user_id"], unique=False)
        batch_op.create_index("ix_dtc_clear_logs_created_at", ["created_at"], unique=False)
    op.execute('ALTER TABLE "dtc_clear_logs" ENABLE ROW LEVEL SECURITY')


def downgrade():
    op.drop_table("dtc_clear_logs")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("can_clear_dtc")
