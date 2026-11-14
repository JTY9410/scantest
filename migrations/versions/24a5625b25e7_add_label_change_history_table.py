"""add label_change_history table

Revision ID: 24a5625b25e7
Revises: b67b02dd9931
Create Date: 2026-11-14 07:33:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '24a5625b25e7'
down_revision = 'b67b02dd9931'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'label_change_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('command_id', sa.Integer(), nullable=False),
        sa.Column('old_label', sa.Text(), nullable=False),
        sa.Column('new_label', sa.Text(), nullable=False),
        sa.Column('operation', sa.String(50), nullable=False),  # 'canze_reimport', etc.
        sa.Column('changed_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('reverted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['command_id'], ['diagnostic_commands.id'], ondelete='CASCADE')
    )
    
    op.create_index('ix_label_change_history_command_id', 'label_change_history', ['command_id'])
    op.create_index('ix_label_change_history_operation', 'label_change_history', ['operation'])
    op.create_index('ix_label_change_history_reverted_at', 'label_change_history', ['reverted_at'])


def downgrade():
    op.drop_index('ix_label_change_history_reverted_at', table_name='label_change_history')
    op.drop_index('ix_label_change_history_operation', table_name='label_change_history')
    op.drop_index('ix_label_change_history_command_id', table_name='label_change_history')
    op.drop_table('label_change_history')
