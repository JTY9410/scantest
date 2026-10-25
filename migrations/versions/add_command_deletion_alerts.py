"""Add command_health and command_deletion_alerts (additive).

Revision ID: add_command_deletion_alerts
Revises: restore_verified_commands
"""
import sqlalchemy as sa
from alembic import op

revision = "add_command_deletion_alerts"
down_revision = "restore_verified_commands"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "command_health",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("command_id", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_status", sa.String(20)),
        sa.Column("last_scan_id", sa.Integer()),
        sa.Column("last_ok_at", sa.DateTime()),
        sa.Column("last_failed_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("command_id", name="uq_command_health_command_id"),
    )
    op.create_table(
        "command_deletion_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("command_id", sa.Integer(), nullable=False),
        sa.Column("maker", sa.String(50)),
        sa.Column("header", sa.String(10)),
        sa.Column("command", sa.String(200), nullable=False),
        sa.Column("label", sa.String(200)),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_status", sa.String(20)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime()),
        sa.Column("resolved_by", sa.Integer()),
    )
    op.create_index("ix_command_deletion_alerts_status", "command_deletion_alerts", ["status"])
    op.create_index("ix_command_deletion_alerts_command", "command_deletion_alerts", ["command_id"])


def downgrade():
    op.drop_index("ix_command_deletion_alerts_command", table_name="command_deletion_alerts")
    op.drop_index("ix_command_deletion_alerts_status", table_name="command_deletion_alerts")
    op.drop_table("command_deletion_alerts")
    op.drop_table("command_health")
