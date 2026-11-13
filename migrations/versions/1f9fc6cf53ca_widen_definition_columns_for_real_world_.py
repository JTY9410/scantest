"""widen definition columns for real-world data

Revision ID: 1f9fc6cf53ca
Revises: c53aed26aba6
Create Date: 2026-11-13 08:28:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '1f9fc6cf53ca'
down_revision = 'c53aed26aba6'
branch_labels = None
depends_on = None


def upgrade():
    # DBC signals: widen columns for long German/international signal names and units
    op.alter_column('dbc_signals', 'signal_name',
                    existing_type=sa.String(length=100),
                    type_=sa.Text(),
                    existing_nullable=False)
    
    op.alter_column('dbc_signals', 'unit',
                    existing_type=sa.String(length=20),
                    type_=sa.String(length=50),
                    existing_nullable=True)
    
    op.alter_column('dbc_signals', 'receivers',
                    existing_type=sa.String(length=200),
                    type_=sa.Text(),
                    existing_nullable=True)
    
    # DBC messages: widen for long message names
    op.alter_column('dbc_messages', 'message_name',
                    existing_type=sa.String(length=100),
                    type_=sa.Text(),
                    existing_nullable=False)
    
    op.alter_column('dbc_messages', 'sender',
                    existing_type=sa.String(length=50),
                    type_=sa.String(length=100),
                    existing_nullable=True)
    
    # Diagnostic commands: widen for expressions and descriptions
    op.alter_column('diagnostic_commands', 'ecu_name',
                    existing_type=sa.String(length=100),
                    type_=sa.Text(),
                    existing_nullable=True)
    
    op.alter_column('diagnostic_commands', 'pid',
                    existing_type=sa.String(length=20),
                    type_=sa.String(length=50),
                    existing_nullable=False)
    
    op.alter_column('diagnostic_commands', 'label',
                    existing_type=sa.String(length=200),
                    type_=sa.Text(),
                    existing_nullable=False)
    
    op.alter_column('diagnostic_commands', 'unit',
                    existing_type=sa.String(length=20),
                    type_=sa.String(length=50),
                    existing_nullable=True)


def downgrade():
    # Reverse changes (may fail if data exceeds old limits)
    op.alter_column('diagnostic_commands', 'unit',
                    existing_type=sa.String(length=50),
                    type_=sa.String(length=20),
                    existing_nullable=True)
    
    op.alter_column('diagnostic_commands', 'label',
                    existing_type=sa.Text(),
                    type_=sa.String(length=200),
                    existing_nullable=False)
    
    op.alter_column('diagnostic_commands', 'pid',
                    existing_type=sa.String(length=50),
                    type_=sa.String(length=20),
                    existing_nullable=False)
    
    op.alter_column('diagnostic_commands', 'ecu_name',
                    existing_type=sa.Text(),
                    type_=sa.String(length=100),
                    existing_nullable=True)
    
    op.alter_column('dbc_messages', 'sender',
                    existing_type=sa.String(length=100),
                    type_=sa.String(length=50),
                    existing_nullable=True)
    
    op.alter_column('dbc_messages', 'message_name',
                    existing_type=sa.Text(),
                    type_=sa.String(length=100),
                    existing_nullable=False)
    
    op.alter_column('dbc_signals', 'receivers',
                    existing_type=sa.Text(),
                    type_=sa.String(length=200),
                    existing_nullable=True)
    
    op.alter_column('dbc_signals', 'unit',
                    existing_type=sa.String(length=50),
                    type_=sa.String(length=20),
                    existing_nullable=True)
    
    op.alter_column('dbc_signals', 'signal_name',
                    existing_type=sa.Text(),
                    type_=sa.String(length=100),
                    existing_nullable=False)
