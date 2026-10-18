"""add knowledge base tables

Revision ID: 87819b247758
Revises: d5e6f7a8b9c0
Create Date: 2026-10-18 01:42:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '87819b247758'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade():
    # Knowledge Commands
    op.create_table(
        'knowledge_commands',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('maker', sa.String(length=50), nullable=True),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('year_from', sa.Integer(), nullable=True),
        sa.Column('year_to', sa.Integer(), nullable=True),
        sa.Column('ecu_name', sa.String(length=100), nullable=True),
        sa.Column('header', sa.String(length=10), nullable=True),
        sa.Column('command', sa.String(length=200), nullable=False),
        sa.Column('label', sa.String(length=200), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.Column('source_detail', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('verified_by', sa.Integer(), nullable=True),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_knowledge_commands_maker', 'knowledge_commands', ['maker'])
    op.create_index('ix_knowledge_commands_ecu_name', 'knowledge_commands', ['ecu_name'])
    op.create_index('ix_knowledge_commands_command', 'knowledge_commands', ['command'])
    op.create_index('ix_knowledge_commands_source', 'knowledge_commands', ['source'])
    op.create_index('ix_knowledge_commands_status', 'knowledge_commands', ['status'])
    op.create_index('ix_knowledge_commands_scope', 'knowledge_commands', ['maker', 'model', 'ecu_name'])

    # Knowledge Formulas
    op.create_table(
        'knowledge_formulas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('maker', sa.String(length=50), nullable=True),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('year_from', sa.Integer(), nullable=True),
        sa.Column('year_to', sa.Integer(), nullable=True),
        sa.Column('ecu_name', sa.String(length=100), nullable=True),
        sa.Column('command', sa.String(length=200), nullable=True),
        sa.Column('pid', sa.String(length=20), nullable=True),
        sa.Column('label', sa.String(length=200), nullable=False),
        sa.Column('formula', sa.Text(), nullable=False),
        sa.Column('unit', sa.String(length=20), nullable=True),
        sa.Column('example_input', sa.String(length=500), nullable=True),
        sa.Column('example_output', sa.String(length=200), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.Column('source_detail', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('verified_by', sa.Integer(), nullable=True),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_knowledge_formulas_maker', 'knowledge_formulas', ['maker'])
    op.create_index('ix_knowledge_formulas_ecu_name', 'knowledge_formulas', ['ecu_name'])
    op.create_index('ix_knowledge_formulas_command', 'knowledge_formulas', ['command'])
    op.create_index('ix_knowledge_formulas_pid', 'knowledge_formulas', ['pid'])
    op.create_index('ix_knowledge_formulas_source', 'knowledge_formulas', ['source'])
    op.create_index('ix_knowledge_formulas_status', 'knowledge_formulas', ['status'])
    op.create_index('ix_knowledge_formulas_scope', 'knowledge_formulas', ['maker', 'model', 'ecu_name'])

    # Knowledge DTCs
    op.create_table(
        'knowledge_dtcs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('maker', sa.String(length=50), nullable=True),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('year_from', sa.Integer(), nullable=True),
        sa.Column('year_to', sa.Integer(), nullable=True),
        sa.Column('ecu_name', sa.String(length=100), nullable=True),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.Column('source_detail', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('verified_by', sa.Integer(), nullable=True),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_knowledge_dtcs_maker', 'knowledge_dtcs', ['maker'])
    op.create_index('ix_knowledge_dtcs_ecu_name', 'knowledge_dtcs', ['ecu_name'])
    op.create_index('ix_knowledge_dtcs_code', 'knowledge_dtcs', ['code', 'maker'])
    op.create_index('ix_knowledge_dtcs_source', 'knowledge_dtcs', ['source'])
    op.create_index('ix_knowledge_dtcs_status', 'knowledge_dtcs', ['status'])
    op.create_index('ix_knowledge_dtcs_scope', 'knowledge_dtcs', ['maker', 'model', 'ecu_name'])

    # Knowledge Terms
    op.create_table(
        'knowledge_terms',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('term', sa.String(length=100), nullable=False),
        sa.Column('abbreviation', sa.String(length=20), nullable=True),
        sa.Column('definition', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('related_terms', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.Column('source_detail', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('verified_by', sa.Integer(), nullable=True),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('term')
    )
    op.create_index('ix_knowledge_terms_term', 'knowledge_terms', ['term'])
    op.create_index('ix_knowledge_terms_category', 'knowledge_terms', ['category'])
    op.create_index('ix_knowledge_terms_source', 'knowledge_terms', ['source'])
    op.create_index('ix_knowledge_terms_status', 'knowledge_terms', ['status'])


def downgrade():
    op.drop_table('knowledge_terms')
    op.drop_table('knowledge_dtcs')
    op.drop_table('knowledge_formulas')
    op.drop_table('knowledge_commands')
