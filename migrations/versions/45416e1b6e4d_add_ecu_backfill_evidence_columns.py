"""add_ecu_backfill_evidence_columns

Revision ID: 45416e1b6e4d
Revises: b4c23c19e171
Create Date: 2026-11-14 05:52:26.701873

Adds evidence columns to diagnostic_commands and dbc_signals to track
the source of ECU module and signal category backfill decisions.

Evidence format:
{
    "rule": "dbc_transmitter" | "uds_can_id" | "file_path",
    "matched_text": "actual text that triggered the rule",
    "timestamp": "ISO 8601 timestamp"
}
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '45416e1b6e4d'
down_revision = 'b4c23c19e171'
branch_labels = None
depends_on = None


def upgrade():
    # Add evidence column to diagnostic_commands for ecu_module backfill
    op.add_column('diagnostic_commands', 
        sa.Column('ecu_backfill_evidence', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    
    # Add evidence columns to dbc_signals for both ecu_module and signal_category backfill
    op.add_column('dbc_signals',
        sa.Column('ecu_backfill_evidence', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.add_column('dbc_signals',
        sa.Column('category_backfill_evidence', postgresql.JSON(astext_type=sa.Text()), nullable=True))


def downgrade():
    op.drop_column('dbc_signals', 'category_backfill_evidence')
    op.drop_column('dbc_signals', 'ecu_backfill_evidence')
    op.drop_column('diagnostic_commands', 'ecu_backfill_evidence')
